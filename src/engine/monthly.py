# src/engine/monthly.py
"""Monthly scaffolding and the post-loop monthly-schedule assembly.

Finance-readable summary
------------------------
This module builds the calendar backbone of the model and turns the raw
day-by-day simulation results into the monthly schedule the business reads.
It works out which interest rate applies in each month, how far into the
future to project, the list of months to model, and a pre-digested per-month
view of the bank's payment and interest activity. After the daily engine has
walked the loan, this module assembles the final per-month table: the amounts
paid, the interest charged, the principal repaid, the interest posting dates,
and the month-end balances for both the model and the bank. These rows feed
the Monthly schedule sheet and the tax outputs.

Technical summary
-----------------
Holds the monthly scaffolding (``build_rate_lookup``, ``rate_lookup_for``,
``derive_modelling_end``, ``month_span``, ``month_tables``) and
``build_monthly_schedule``, the post-loop assembly that consumes the daily
loop's per-month collector dicts and produces the ``monthly`` DataFrame
(per-month frame, posting date/year, model and bank end-of-month balances).
Depends only on ``helpers`` and ``schema``; it must never import ``simulate``.

Phase 5 / S3 note: lifted verbatim out of ``simulate.py``. Behaviour is
unchanged; only the module location and imports differ. The golden master
still reads 46 passed, 2 skipped, plus the S1 characterization test.

Phase 7 / S2 note: ``build_monthly_schedule`` takes one extra collector,
``month_contractual`` (the agreed or projected contractual instalment per
month, computed read-only in the daily loop), and emits it as the new
``contractual_payment`` column. This is additive: it adds a single column and
leaves every existing column and value unchanged, so the golden master diffs
to exactly that one new column.

Phase 7 / S3 note: ``build_monthly_schedule`` now emits the principled
attribution split on top of the S2 baseline: ``total_paid`` (the full monthly
debit), ``overpayment`` (the agreed standing extra from ``overpay_rules``),
``payment_unattributed`` (the explicit Difference residual), and the
``overpayment_mismatch`` reconciliation flag. The split is derived entirely
from figures the daily loop already settled, so every conserved quantity (total
paid, interest, principal, balance, payoff) stays byte-identical to v1.7.0; only
the agreed-terms split is new and the merge flag no longer decides it. A
dedicated tolerance, ``payment_unattributed_ok_abs_eur`` (default one cent),
governs the mismatch flag.

Phase 7 / S4 note: the monthly schedule now emits the final attribution
vocabulary. ``contractual_payment`` is renamed to ``contractual``,
``lump_amount`` to ``lump``, and ``payment_unattributed`` to ``difference``;
``overpayment`` and ``total_paid`` keep their S3 names. The legacy
``payment_amount`` and ``extra_amount`` columns are retired: they were the
merge-flag-dependent split that the principled contractual / overpayment /
difference attribution now wholly supersedes. This is a pure rename plus the
removal of those two duplicated columns; every retained figure (total paid,
interest, principal, balance, payoff) stays byte-identical to S3, and only the
column names and the two dropped columns change.

Phase 10 / S2 note: the rate lookup and the recurring overpayment are repointed
onto the date-based contracts model. ``rate_lookup_for(inputs)`` builds the
month-to-rate lookup from each contract's start_date/end_date (converted to
1-based model months from drawdown), and ``month_tables`` expands each
contract's ``standing_overpayment`` date window into the per-month recurring
extra. Both keep a legacy fallback: a file with no contracts still reads
``rate_blocks`` and ``overpay_rules`` exactly as before, so the still-legacy
Property B/C samples stay byte-identical. Property A (converted to contracts)
reproduces its retired rate windows and its month-17 / EUR200 standing extra
exactly, so the Gandon golden does not move.

Phase 12 / S1 note: ``build_monthly_schedule`` takes one more collector,
``month_cap_allowance`` (the per-payment BOI overpayment-cap allowance in euro
resolved read-only in the daily loop from the contract in effect), and emits it
as the new ``overpayment_cap_allowance_eur`` column. Additive: it adds a single
column and changes no existing column or value, so the golden master diffs to
exactly that one new column (re-baselined at S3). A month with no resolvable
allowance carries a null, distinct from a real zero.

Phase 12 / S2 note: three more additive columns join the schedule beside the S1
allowance, and no collector or signature changes because all three derive from
figures the assembly already has. ``overpayment_cap_headroom_eur`` is that
month's allowance minus the month's recognised voluntary overpayment (the Phase
7 ``overpayment`` figure). The basis is per payment, not cumulative across a
year, because the BOI cap does not roll over and has no calendar reset, so each
month is measured against its own allowance. ``overpayment_cap_flag`` labels the
month ok / approaching / breached via ``overpayment_cap_flag`` using the single
``OVERPAYMENT_CAP_APPROACHING_THRESHOLD`` constant, so the amber trip point is
retuned in one place. ``overpayment_cumulative_eur`` is a lifetime running total
of the recognised voluntary overpayment, emitted for context only and never fed
back into the headroom or the flag. Both cap figures are null in months with no
resolvable allowance, keeping "unknown" distinct from a real zero. Additive:
three new columns, no conserved figure moves, re-baselined at S3.
"""

from __future__ import annotations

import sys
from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .helpers import (
    clamp_day,
    ensure_date,
    eom,
    month_index,
    ym_int,
)
from .schema import Inputs, RateBlock
from .calendar_ie import adjust_for_convention, CONVENTION_DAY_CLAMP


# =====================================================================
# Overpayment-cap flag policy (Phase 12 / S2)
# =====================================================================
# The "approaching" threshold for the per-payment overpayment-cap flag,
# expressed as a fraction of that month's allowance. A month whose recognised
# voluntary overpayment reaches this fraction of its allowance (without
# exceeding it) is flagged "approaching"; strictly above the allowance is
# "breached"; below the fraction is "ok". This is a display/policy knob, not a
# lender term, so it deliberately lives here as one named constant. To retune
# the amber trip point, change this single value (e.g. 0.80 for an earlier
# warning).
OVERPAYMENT_CAP_APPROACHING_THRESHOLD = 0.90

# The flag vocabulary, defined once so every consumer (the per-property summary
# sheet and the portfolio rollup) reads these labels off the monthly schedule
# rather than recomputing the flag or hard-coding the strings.
OVERPAYMENT_CAP_FLAG_OK = "ok"
OVERPAYMENT_CAP_FLAG_APPROACHING = "approaching"
OVERPAYMENT_CAP_FLAG_BREACHED = "breached"


# =====================================================================
# Monthly scaffolding
# =====================================================================

def build_rate_lookup(blocks: List[RateBlock]):
    """Return a callable mapping model month numbers to annual rates.

    Finance note: the loan's rate changes at refix dates. This turns the list of
    rate blocks into a quick "what rate applies in month N?" lookup that drives
    daily interest.

    Phase 10 / S2: retained unchanged as the legacy fallback. ``rate_lookup_for``
    is the going-forward entry point; it calls this only for files that carry no
    contracts (the still-legacy Property B/C samples).
    """
    def rate_of_month(m: int) -> float:
        for rb in blocks:
            if rb.start_month <= m <= rb.end_month:
                return rb.annual_rate
        return blocks[-1].annual_rate
    return rate_of_month


def _contract_month_ranges(inputs: Inputs) -> List[Tuple[int, int, float]]:
    """Convert each contract's date span to a ``(start_month, end_month, rate)``.

    Finance note: the engine counts months from drawdown (month 1 = the drawdown
    month), so a contract's start_date/end_date become 1-based model months and
    the date-based contracts reproduce the month-number rate windows exactly. An
    open-ended contract (no end_date) runs to a large sentinel month, so the
    final contract's rate applies to every remaining month, just as the last
    rate_block did.
    """
    ranges: List[Tuple[int, int, float]] = []
    for c in inputs.contracts:
        start_month = month_index(inputs.drawdown_date, c.start_date)
        end_month = month_index(inputs.drawdown_date, c.end_date) if c.end_date else 10 ** 6
        ranges.append((start_month, end_month, float(c.rate)))
    return ranges


def rate_lookup_for(inputs: Inputs):
    """Return a callable mapping model month numbers to annual rates.

    Finance note: the rate path is now contract-driven. Each contract's date
    span becomes a model-month window, giving the same "what rate applies in
    month N?" lookup the legacy rate_blocks provided. A file with no contracts
    (the still-legacy Property B/C samples) falls back to the rate_blocks path,
    so those runs stay byte-identical.
    """
    if inputs.contracts:
        ranges = _contract_month_ranges(inputs)
        last_rate = float(inputs.contracts[-1].rate)

        def rate_of_month(m: int) -> float:
            for start_month, end_month, rate in ranges:
                if start_month <= m <= end_month:
                    return rate
            return last_rate
        return rate_of_month
    return build_rate_lookup(inputs.rate_blocks)


def derive_modelling_end(inputs: Inputs) -> date:
    """Return the last date to simulate based on inputs and optional overrides.

    Finance note: this sets how far into the future the projection runs. It
    honours an explicit modelling end date, otherwise it falls back to the
    contractual end of term.
    """
    if inputs.modelling_end_date:
        return inputs.modelling_end_date
    y = inputs.drawdown_date.year + (inputs.drawdown_date.month - 1 + inputs.total_term_months) // 12
    m = (inputs.drawdown_date.month - 1 + inputs.total_term_months) % 12 + 1
    return date(y, m, 5)


def month_span(start: date, end: date) -> List[date]:
    """Return a list of first-of-month dates between ``start`` and ``end``.

    Finance note: this is the calendar backbone of the schedule, one entry per
    month from drawdown to the modelling horizon, so every month gets a row even
    when nothing happened in it.
    """
    out: List[date] = []
    cur = date(start.year, start.month, 1)
    lim = date(end.year, end.month, 1)
    while cur <= lim:
        out.append(cur)
        cur = date(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1)
    return out


def _payment_convention_on(inputs: Inputs, anchor: date) -> str:
    """Return the payment-date convention in force on ``anchor``.

    Finance note: the convention is a lender-profile rule (LP3/LP7): resolve
    the rule version in force on the scheduled date and read its
    payment_date_convention. A file with no resolved profile (legacy Property
    B/C, or any file without a lender key) falls back to 'day_clamp', the
    engine's historical behaviour, so only a profile that states
    modified_following moves any date.
    """
    profile = getattr(inputs, "profile", None)
    if profile is None:
        return CONVENTION_DAY_CLAMP
    try:
        return profile.rule_on(anchor).payment_date_convention
    except ValueError:
        # No rule version on or before the anchor: keep the safe default.
        return CONVENTION_DAY_CLAMP


def month_tables(inputs: Inputs, actuals: pd.DataFrame) -> pd.DataFrame:
    """Build a per-month summary table consumed by the daily engine.

    Finance note: this lines up each calendar month with the bank's payment and
    interest activity (and any standing overpayments), giving the day-by-day
    simulation a clean, pre-digested view of what should happen each month.

    The table distils raw bank activity into the bare minimum metadata the
    simulation needs.  Deriving this table up-front keeps the inner daily loop
    simple and fast.
    """
    end = derive_modelling_end(inputs)
    mstarts = month_span(inputs.drawdown_date, end)
    g = actuals.groupby("ym", dropna=False)

    # Expand standing extras into {month_num: amount}. Phase 10 / S2: the agreed
    # recurring overpayment now rides on each contract's standing_overpayment (a
    # date window). Its start_date/end_date are converted to model months and
    # expanded monthly, matching the legacy overpay_rules expansion exactly (an
    # open-ended window runs to the end of term). A file with no contracts
    # (Property B/C samples until their data is converted) falls back to the
    # legacy overpay_rules path, so those runs stay byte-identical.
    recurring_by_month: Dict[int, float] = {}
    if inputs.contracts:
        for c in inputs.contracts:
            so = c.standing_overpayment
            if so is None:
                continue
            s = month_index(inputs.drawdown_date, so.start_date)
            endm = month_index(inputs.drawdown_date, so.end_date) if so.end_date else None
            amt = float(so.amount)
            i = max(1, s)
            while i <= inputs.total_term_months and (endm is None or i <= endm):
                recurring_by_month[i] = recurring_by_month.get(i, 0.0) + amt
                i += 1
    else:
        for rule in inputs.overpay_rules:
            s = int(rule["start_month"])
            amt = float(rule["amount"])
            endm = rule.get("end_month", None)
            rep = str(rule.get("repeat", "monthly")).lower()
            if rep == "monthly":
                i = s
                while i <= inputs.total_term_months and (endm is None or i <= int(endm)):
                    recurring_by_month[i] = recurring_by_month.get(i, 0.0) + amt
                    i += 1
            else:
                recurring_by_month[s] = recurring_by_month.get(s, 0.0) + amt

    rows = []
    for ms in mstarts:
        ym = ym_int(ms)
        mnum = month_index(inputs.drawdown_date, ms)
        eom_d = eom(ms)
        grp = g.get_group(ym) if ym in g.groups else None

        pay_date = None
        pay_total = 0.0
        post_date = None
        post_amt = 0.0

        if grp is not None:
            pays = grp[grp["type"] == "Payment"]
            if not pays.empty:
                pay_date = ensure_date(min(pays["date"]))
                pay_total = float(-pays["amount"].sum())  # input has payments negative
            ints = grp[grp["type"] == "Interest"]
            if not ints.empty:
                post_date = ensure_date(min(ints["date"]))
                post_amt = float(ints["amount"].sum())

        # Default payment date only if no actual payment that month
        def_pay = None
        if ms >= date(inputs.first_payment_date.year, inputs.first_payment_date.month, 1):
            # Phase 10 / S4: clamp to the repayment day, then apply the lender
            # profile's payment-date convention (modified_following) so
            # projected debits land on Irish working days. day_clamp (or no
            # profile) preserves the prior behaviour.
            clamped = clamp_day(ms.year, ms.month, inputs.repayment_day_default)
            def_pay = adjust_for_convention(clamped, _payment_convention_on(inputs, clamped))

        rows.append(
            dict(
                month_start=ms,
                eom=eom_d,
                ym=ym,
                month_num=mnum,
                actual_payment_date=pay_date,
                actual_payment_total=pay_total,
                actual_interest_post_date=post_date,
                actual_interest_amount=post_amt,
                default_payment_date=def_pay,
                recurring_extra=recurring_by_month.get(mnum, 0.0),
            )
        )
    return pd.DataFrame(rows)


# =====================================================================
# Monthly schedule assembly (post daily loop)
# =====================================================================

def overpayment_cap_flag(overpayment_used: float, allowance_eur: Optional[float]) -> Optional[str]:
    """Return the per-payment overpayment-cap flag for a single month.

    Finance note: compares the month's recognised voluntary overpayment against
    that month's BOI allowance. The BOI cap is per payment, does not roll over,
    and has no calendar reset, so each month stands on its own: the month is
    "breached" once the overpayment exceeds the allowance, "approaching" once it
    reaches OVERPAYMENT_CAP_APPROACHING_THRESHOLD of the allowance (but does not
    exceed it), and "ok" below that. Returns None when the allowance is
    unresolvable, so "unknown" never reads as free headroom.

    Technical note: pure and read-only. It derives a label from two numbers and
    touches no simulation state. The amber trip point is the single module
    constant OVERPAYMENT_CAP_APPROACHING_THRESHOLD, so retuning it is a one-line
    edit that this and every consumer inherit.
    """
    # No resolvable allowance: the flag is unknown, kept distinct from "ok".
    if allowance_eur is None:
        return None
    used = float(overpayment_used or 0.0)
    # A non-positive allowance cannot be meaningfully approached: any positive
    # overpayment against it is a breach, otherwise there is nothing to flag.
    if allowance_eur <= 0.0:
        return OVERPAYMENT_CAP_FLAG_BREACHED if used > 0.0 else OVERPAYMENT_CAP_FLAG_OK
    # Strictly above the allowance is a breach.
    if used > allowance_eur:
        return OVERPAYMENT_CAP_FLAG_BREACHED
    # At or above the approaching fraction of the allowance (but not over it).
    if used >= OVERPAYMENT_CAP_APPROACHING_THRESHOLD * allowance_eur:
        return OVERPAYMENT_CAP_FLAG_APPROACHING
    # Comfortable headroom below the amber trip point.
    return OVERPAYMENT_CAP_FLAG_OK


def build_monthly_schedule(
    months: pd.DataFrame,
    events_df: pd.DataFrame,
    actuals: pd.DataFrame,
    month_paid: Dict[int, float],
    month_extras: Dict[int, float],
    month_lumps: Dict[int, float],
    month_interest_used: Dict[int, float],
    month_rate: Dict[int, float],
    month_contractual: Dict[int, float],
    month_cap_allowance: Dict[int, Optional[float]],
    payment_unattributed_ok_abs_eur: float = 0.01,
) -> pd.DataFrame:
    """Assemble the final per-month schedule after the daily loop has run.

    Finance note: this is where the day-by-day results become the monthly
    schedule a finance reader actually sees. For every month it totals the
    payment, any standing extra, any lump sum, and the interest charged, derives
    the principal repaid, records the interest posting date, and lines up the
    month-end balances for both the model and the bank so the two can be
    compared. It also reports the contractual baseline for the month (the agreed
    instalment where the bank has confirmed one, otherwise the model's projected
    payment), the per-payment BOI overpayment-cap allowance in euro, and, from
    Phase 12 / S2, how much of that allowance the month's voluntary overpayment
    uses (the headroom and an ok/approaching/breached flag). These rows drive the
    Monthly schedule sheet and the tax outputs.

    Technical note: pure relocation of the post-loop assembly from
    ``run_engine``, plus the Phase 7 / S2 additive contractual column, the Phase
    12 / S1 additive cap-allowance column, and the Phase 12 / S2 additive
    headroom / flag / cumulative columns. The per-month collector dicts
    (``month_paid``, ``month_extras``, ``month_lumps``, ``month_interest_used``,
    ``month_rate``, ``month_contractual``, ``month_cap_allowance``) are passed in
    explicitly so this module never reaches back into ``simulate``. As before,
    it mutates ``events_df`` in place by adding the ``ym`` helper column used to
    align events to their calendar month; this matches the pre-S3 behaviour
    exactly. The new columns are appended only; no existing column or value
    changes.

    Phase 7 / S3 note: this assembly now also emits the principled attribution
    split. ``total_paid`` is the full monthly debit (the sum of the legacy
    payment, extra, and lump amounts, so it is invariant to the merge flag and
    byte-identical to v1.7.0). ``overpayment`` is the agreed standing extra for
    the month taken from ``overpay_rules`` (``months.recurring_extra``),
    recognised only where a modelled instalment exists. ``payment_unattributed``
    is the explicit Difference residual, ``total_paid - (contractual_payment +
    overpayment + lump_amount)``, so the four agreed parts always reconstruct the
    debit to the cent and drift never silently inflates overpayment.
    ``overpayment_mismatch`` flags an actual-payment month whose Difference
    exceeds ``payment_unattributed_ok_abs_eur``. All four are derived from
    figures the daily loop already settled, so no conserved quantity moves.

    Phase 12 / S1 note: ``overpayment_cap_allowance_eur`` is the per-payment BOI
    overpayment-cap allowance in euro for the month, resolved in the daily loop
    from the contract in effect (max(percent * instalment, floor_eur) under the
    rule in force on the contract start_date). It is a null in months with no
    resolvable allowance (no profile, no stated instalment, no cap rule, or a
    non-payment month), keeping "unknown" distinct from a real zero.

    Phase 12 / S2 note: three more additive columns are emitted from figures
    already in hand, so the signature is unchanged. ``overpayment_cap_headroom_eur``
    is the month's allowance minus its recognised voluntary overpayment (the
    Phase 7 ``overpayment`` figure); a positive value is room left under the cap
    and a negative value is the amount over it. The basis is per payment (the
    BOI cap does not roll over and has no calendar reset), so each month is
    judged against its own allowance rather than a running annual pool.
    ``overpayment_cap_flag`` is the ok / approaching / breached label from
    ``overpayment_cap_flag`` (a single module threshold constant governs amber),
    computed once here so the summary sheet and the rollup only read it.
    ``overpayment_cumulative_eur`` is a lifetime running total of the recognised
    voluntary overpayment, emitted for context only and never fed into the
    headroom or the flag. Both cap-derived figures are null where the allowance
    is unresolvable, so "unknown" stays distinct from a real zero. Additive:
    three new columns, no conserved figure moves, re-baselined at S3.
    """
    # Plain-English progress line for troubleshooting (stderr only; never stdout).
    print(
        f"[engine.monthly] build_monthly_schedule: assembling {len(months)} monthly rows",
        file=sys.stderr,
    )

    # Phase 12 / S2: a lifetime running total of the recognised voluntary
    # overpayment, emitted per month for context only. Months are assembled in
    # calendar order (month_tables builds them over an ascending month_span), so
    # a simple carried accumulator gives the correct cumulative on each row. It
    # never feeds the per-payment headroom or the flag.
    running_overpayment_cumulative = 0.0

    # Per-month frame build ----------------------------------------------------
    rows = []
    for _, r in months.iterrows():
        ymkey = int(r.ym)
        pay = month_paid[ymkey]; extra = month_extras[ymkey]; lump = month_lumps[ymkey]
        interest_used = month_interest_used[ymkey]
        principal = max(0.0, (pay + extra + lump) - interest_used)

        # Local rounded amounts, each to the cent exactly as in v1.7.0. As of
        # Phase 7 / S4, payment_amount and extra_amount are no longer emitted as
        # their own columns (retired in favour of the principled split); they are
        # kept here only as the inputs that build total_paid. lump_amount is
        # emitted under the final column name ``lump``.
        payment_amount = round(pay, 2)
        extra_amount = round(extra, 2)
        lump_amount = round(lump, 2)

        # ---------------- ATTRIBUTION SPLIT (Phase 7 / S3) ----------------
        # total_paid is the full debit for the month: the same money that already
        # flowed through the daily loop, expressed as the sum of the three legacy
        # amounts. It is therefore invariant to the merge flag and byte-identical
        # to v1.7.0's payment + extra + lump.
        total_paid = round(payment_amount + extra_amount + lump_amount, 2)

        # contractual is the agreed (or projected) instalment captured on the
        # payment day in the daily loop (Phase 7 / S2). It is zero in months with
        # no modelled instalment (before the first payment, or after payoff).
        contractual = round(month_contractual[ymkey], 2)

        # overpayment is the AGREED standing extra for the month from
        # overpay_rules (months.recurring_extra already sums the rules and honours
        # each rule's end_month). It is recognised only in months that carry a
        # modelled instalment: with no instalment there is nothing to overpay, so
        # it stays zero and never invents a phantom overpayment in a closed month.
        agreed_overpayment = round(float(r.recurring_extra or 0.0), 2)
        overpayment = agreed_overpayment if contractual > 0.0 else 0.0

        # payment_unattributed (the Difference) is the explicit residual: whatever
        # of the actual debit the agreed split does not account for. Engine
        # rounding, recompute drift, or a genuine over/under-payment lands here
        # and never silently inflates overpayment. By construction the four parts
        # add back to total_paid to the cent:
        #   contractual + overpayment + lump + payment_unattributed == total_paid
        payment_unattributed = round(total_paid - contractual - overpayment - lump_amount, 2)

        # overpayment_mismatch flags an actual-payment month whose observed debit
        # does not reconcile to the agreed split within the dedicated tolerance.
        # Projected months never flag: they carry no bank debit to disagree with.
        overpayment_mismatch = bool(
            r.has_actual_payment and abs(payment_unattributed) > payment_unattributed_ok_abs_eur
        )

        # ---------------- OVERPAYMENT-CAP ALLOWANCE (Phase 12 / S1) ----------------
        # The per-payment BOI voluntary-overpayment allowance in euro for this
        # month, resolved in the daily loop from the contract in effect
        # (max(percent * instalment, floor_eur) under the rule in force on the
        # contract start_date). None (no profile, no stated instalment, no cap
        # rule, or a non-payment month) is emitted as a null so "unknown" stays
        # distinct from a real zero. Additive: one new column, no existing figure
        # changes.
        _cap_allowance = month_cap_allowance[ymkey]
        overpayment_cap_allowance_eur = (
            None if _cap_allowance is None else round(float(_cap_allowance), 2)
        )

        # ---------------- OVERPAYMENT-CAP HEADROOM & FLAG (Phase 12 / S2) ----------------
        # Per-payment basis: measure this month's recognised voluntary
        # overpayment (the Phase 7 overpayment figure above) against this month's
        # allowance. The BOI cap does not roll over and has no calendar reset, so
        # each month is judged on its own allowance rather than a running annual
        # pool. Headroom is the allowance minus the used amount (positive is room
        # left, negative is the amount over the cap); the flag is
        # ok / approaching / breached from overpayment_cap_flag. Both are null
        # when the allowance is unresolvable, so "unknown" never reads as free
        # headroom.
        cap_used = overpayment  # the Phase 7 recognised voluntary overpayment for the month
        if overpayment_cap_allowance_eur is None:
            overpayment_cap_headroom_eur = None
        else:
            overpayment_cap_headroom_eur = round(overpayment_cap_allowance_eur - cap_used, 2)
        overpayment_cap_flag_value = overpayment_cap_flag(cap_used, overpayment_cap_allowance_eur)

        # Lifetime running total of the recognised voluntary overpayment (context
        # only; it does not affect the per-payment headroom or the flag above).
        running_overpayment_cumulative = round(running_overpayment_cumulative + overpayment, 2)
        overpayment_cumulative_eur = running_overpayment_cumulative

        rows.append(dict(
            ym=ymkey,
            month_start=r.month_start,
            payment_date=r.pay_date,
            # Phase 7 / S4: the final attribution vocabulary. The agreed split
            # (contractual + overpayment + lump + difference) reconstructs
            # total_paid to the cent and is the canonical monthly view. The legacy
            # payment_amount and extra_amount columns are retired here;
            # contractual_payment is renamed to contractual, lump_amount to lump,
            # and payment_unattributed to difference. total_paid and overpayment
            # keep their S3 names. Every conserved figure is untouched: only column
            # names change and the two duplicates drop.
            contractual=contractual,
            overpayment=overpayment,
            lump=lump_amount,
            total_paid=total_paid,
            difference=payment_unattributed,
            overpayment_mismatch=overpayment_mismatch,
            # Phase 12 / S1: additive per-payment cap allowance in euro (null
            # where unresolvable). Does not feed the attribution split above.
            overpayment_cap_allowance_eur=overpayment_cap_allowance_eur,
            # Phase 12 / S2: additive per-payment headroom, ok/approaching/breached
            # flag, and a context-only lifetime cumulative. Headroom and flag are
            # null where the allowance is unresolvable. None of these feed the
            # attribution split.
            overpayment_cap_headroom_eur=overpayment_cap_headroom_eur,
            overpayment_cap_flag=overpayment_cap_flag_value,
            overpayment_cumulative_eur=overpayment_cumulative_eur,
            interest_used=round(interest_used, 2),
            principal_paid=round(principal, 2),
            annual_rate=month_rate[ymkey],
            bank_posted_interest_present=(float(r.actual_interest_amount or 0.0) > 0.0)
        ))
    monthly = pd.DataFrame(rows)

    # Posting date/year --------------------------------------------------------
    monthly["posting_date"] = [
        r.actual_interest_post_date if pd.notna(r.actual_interest_post_date) else r.eom
        for _, r in months.iterrows()
    ]
    monthly["posting_year"] = pd.to_datetime(monthly["posting_date"]).dt.year

    # Add model month-end balance from events (last event in that month).
    if not events_df.empty:
        events_df["ym"] = events_df["date"].apply(ym_int)
        eom_bal = events_df.groupby("ym", as_index=True)["balance"].last().rename("model_eom_balance")
        monthly = monthly.merge(eom_bal, left_on="ym", right_index=True, how="left")

    # Add bank month-end running balance (last bank line in that month, if provided).
    if "run_balance" in actuals.columns:
        bank_month_end = (
            actuals
            .assign(ym=lambda d: d["date"].apply(ym_int))
            .sort_values("date")
            .groupby("ym", as_index=True)["run_balance"]
            .last()
            .rename("bank_eom_running_balance")
        )
        monthly = monthly.merge(bank_month_end, left_on="ym", right_index=True, how="left")
        if "model_eom_balance" in monthly.columns:
            monthly["eom_diff_model_minus_bank"] = monthly["model_eom_balance"] - monthly["bank_eom_running_balance"]

    return monthly
