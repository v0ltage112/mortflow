# Lender profile and universal rules (Phase 10 build brief)

> Authored in P9/S5. Companion to docs/contract_data_model.md. This file is the
> authority for the rules layer: the per-lender profile, its effective-dated
> rule versions (overpayment cap, breakage formula, payment-date convention,
> day-count), the rationale per version, and the dated money-market-rate series
> the breakage formula consumes. docs/contract_data_model.md Section B covers how
> the profile plugs into the contracts array, the repo-wide cascade, and the
> migration.
>
> All figures below are illustrative placeholders, not real contract or market
> values. The generic product thresholds (10%, EUR 65, 0.5%, EUR 2.54, 0.3%,
> 102%) are published BOI product rules, not personal data. Real money-market
> rates stay off-repo in the private profile.
>
> Status (Phase 10, v2.0.0, shipped 2026-07-06): implemented. This profile is live in src/engine/profile.py (the loader plus effective-dated rule resolution) and src/engine/schema.py (resolve_overpayment_cap_allowance, overpayment_cap_for_contract, and resolve_breakage_reference). data/lenders/sample_lender.yaml ships committed; the real boi.local.yaml stays git-ignored. The overpayment cap, the breakage reference, the day-count, and the Modified Following payment-date convention resolve per the LP7 anchors as of v2.0.0. The cap and breakage resolvers are reference-only (no output figure consumes them yet); the payment-date convention is the one rule that changed engine output, driving the v2.0.0 golden re-baseline. This document remains the design brief; the live repo is the source of truth.

## LP0. Purpose and scope

Today the universal bank rules are scattered and partly implicit. The
overpayment cap sits as a scalar (overpayment_cap_pct) on each property, the
breakage formula is not modelled anywhere in the engine, and the projected
payment date is a plain day-of-month clamp. This file lifts the rules into one
reusable, effective-dated lender profile that every loan points to through its
lender key. A rule change becomes a new dated block in one place, with the
reasoning recorded beside it, instead of an edit scattered across property
files.

Scope is design only (Phase 9 guardrail). No engine code changes here. Phase 10
implements this profile and ships v2.0.0.

## LP1. Profile model and file layout

A profile is a named rules document for one lender. Each loan selects its
profile with the lender key defined in the contract data model (Section A):

    loan:
      lender: boi

Two profiles exist:

- sample_lender: committed to the public repo. Generic, illustrative, safe to
  publish. Carries the rule structure with placeholder or null figures so the
  schema and tests have something to resolve against.
- boi: private, git-ignored. Carries the real BOI thresholds, the real breakage
  money-market-rate series, and the real rationale. Never committed.

Proposed location, mirroring the existing local-vs-sample split (one shared
profiles folder, not a copy per property):

    data/
      lenders/
        sample_lender.yaml        # committed
        boi.local.yaml            # git-ignored (real rules + rates)

The *.local.yaml suffix reuses the gitignore convention already used by
paths.local.yaml and tenancy.local.yaml. Resolution: lender: boi loads
boi.local.yaml when present, else falls back to sample_lender.yaml, so a fresh
clone runs on the committed sample.

## LP2. Effective-dated rule versions (append-only)

Rules change over time. The profile records this as an append-only list of dated
versions. Never edit or delete a past version; add a new one with a later
effective_from. This keeps history and intent separate (Principle 3) and makes
every past model run reproducible.

Resolution rule: for a given anchor date, use the version with the greatest
effective_from that is not after the anchor date (latest effective_from <=
anchor). Which date is the anchor depends on the rule; see LP7.

    # profile: boi (illustrative placeholder values)
    lender_id: boi
    display_name: "Bank of Ireland"
    rule_versions:
      - effective_from: 2020-01-01
        rationale: >
          Baseline BOI fixed-rate rules as understood at project start.
          Overpayment cap is a per-payment allowance, not a calendar-year
          balance reset (S3 decision b). Breakage is the BOI differential
          formula (S3 decision c). Day-count is ACT/365.
        overpayment_cap:
          basis: percent_of_monthly_repayment
          percent: 0.10
          floor_eur: 65.00
          rolls_over: false          # unused monthly headroom does not accumulate
        breakage:
          formula: principal_x_rate_differential_x_remaining_years
        payment_date_convention: modified_following
        day_count: ACT/365

Only one version exists today. If BOI revised, for example, the overpayment
percentage, you would append a second block with the new effective_from and
leave the first untouched.

Migration note: the payment_date_convention above records the correct locked
rule (Modified Following, S3 decision d). The engine does NOT honour it during
the byte-identical refactor step; it keeps its current day-clamp behaviour and
only starts consuming the profile convention at the deliberate re-baseline step.
See docs/contract_data_model.md Section B (B3, B4).

## LP3. The rule set inside a version

Each version carries four rule groups:

- overpayment_cap: the voluntary-overpayment allowance. See LP4.
- breakage: the early-repayment-charge formula reference. See LP5.
- payment_date_convention: how a scheduled date is adjusted off a non-working
  day. Values: day_clamp (current engine behaviour, clamp to the given day of
  month) or modified_following (locked target, LP7 and Section B).
- day_count: interest day-count basis. ACT/365 confirmed on both loans.

## LP4. Overpayment cap-basis catalog

The cap is expressed as a basis plus its parameters, so a future lender with a
different rule is a new catalog entry rather than a code change.

- percent_of_monthly_repayment (BOI, locked): allowance for a payment =
  max(percent * contract_instalment, floor_eur). BOI: percent = 0.10,
  floor_eur = 65.00. Assessed per payment; rolls_over: false.
- percent_of_opening_balance_annual (NOT BOI; catalog only): the legacy,
  incorrect assumption baked into today's overpayment_cap_pct comment. Recorded
  here so the migration can retire it knowingly. Do not use for BOI.
- flat_eur_annual (catalog only): a fixed euro allowance per year, if a future
  lender uses one.

The cap is not consumed by the engine today (it is read into overpayment_cap_pct
and never used for a figure), so encoding it in the profile changes no current
output. It is the foundation for the Phase 13/14 cap-headroom work.

## LP5. Breakage-fee formula catalog

- principal_x_rate_differential_x_remaining_years (BOI, locked type):
  C = A x (R% - R1%) x D / 365.
  - A: the amount repaid early, averaged over the remaining fixed period (not
    the raw outstanding balance).
  - R%: BOI wholesale money-market funding rate for a sum equal to A over the
    original fixed period.
  - R1%: BOI money-market deposit rate for a sum equal to A over period D.
  - D: days from the early repayment or rate change to the end of the fixed
    period.
  - If C <= 0, no charge is payable.
  - R% and R1% are external market inputs (LP6), not the customer's contract
    rates. When a needed rate is absent, emit "not computable" rather than
    substituting a contract rate.
- flat_eur (catalog only): a fixed euro breakage cost, if a contract states one.

Breakage is not computed anywhere in the engine today, so this is reference data
for Phase 14 (mortgage-offer comparison) and any earlier breakage surfacing.

## LP6. Money-market rate series (private)

R% and R1% are sourced externally and are private. They live only in
boi.local.yaml, never in the committed sample. Modelled as a dated lookup so a
breakage quote resolves the rates in force on its quote date:

    # boi.local.yaml (git-ignored). Values here are placeholders.
    money_market_rates:
      - as_of: 2025-05-28          # breakage-quote date the rates apply to
        funding_rate: null         # R% - external BOI wholesale rate, off-repo
        deposit_rate: null         # R1% - external BOI deposit rate, off-repo
        note: "source + term basis recorded privately"

The committed sample_lender.yaml carries an empty or null series and documents
the shape only:

    money_market_rates: []          # sample: no market rates published

Sourcing note (private): record where each R%/R1% came from and the term basis
used, so a historical breakage quote can be reproduced.

## LP7. Rule-resolution model (date anchors)

Each rule resolves against a specific anchor date:

- overpayment_cap: anchored on the contract-period date (the date of the payment
  or event being assessed). The allowance uses the cap rule in force then,
  applied to that contract's instalment.
- payment_date_convention: anchored on the scheduled month or contract-period
  date being placed.
- day_count: anchored on the accrual date (the contract period in force).
- breakage R%/R1%: anchored on the breakage-quote date (the date the early
  repayment or rate switch is quoted), looked up in money_market_rates.

This is the default confirmed for S5: cap and payment convention on the
contract-period/event date; breakage rates on the breakage-quote date.

## LP8. Sample vs private split

| Item | sample_lender.yaml (committed) | boi.local.yaml (git-ignored) |
| --- | --- | --- |
| Rule structure (rule_versions, groups) | Yes, full shape | Yes, full shape |
| Cap percent / floor | Generic placeholder (0.10 / 65) | Real BOI values |
| Breakage formula type | Yes | Yes |
| money_market_rates (R%/R1%) | Empty / null | Real, private |
| Rationale text | Generic | Real, may reference private context |
| Committed to public repo | Yes | Never |

## LP9. Worked examples (placeholder figures)

Committed sample profile:

    # data/lenders/sample_lender.yaml  (committed, illustrative)
    lender_id: sample_lender
    display_name: "Sample Lender"
    rule_versions:
      - effective_from: 2020-01-01
        rationale: "Generic fixed-rate rules for the public sample."
        overpayment_cap:
          basis: percent_of_monthly_repayment
          percent: 0.10
          floor_eur: 65.00
          rolls_over: false
        breakage:
          formula: principal_x_rate_differential_x_remaining_years
        payment_date_convention: modified_following
        day_count: ACT/365
    money_market_rates: []

Private BOI profile (shape only; real values off-repo):

    # data/lenders/boi.local.yaml  (git-ignored, real rules + rates)
    lender_id: boi
    display_name: "Bank of Ireland"
    rule_versions:
      - effective_from: 2020-01-01
        rationale: "Real BOI baseline; see private notes."
        overpayment_cap:
          basis: percent_of_monthly_repayment
          percent: 0.10
          floor_eur: 65.00
          rolls_over: false
        breakage:
          formula: principal_x_rate_differential_x_remaining_years
        payment_date_convention: modified_following
        day_count: ACT/365
    money_market_rates:
      - as_of: 2025-05-28
        funding_rate: null      # R% (real value off-repo)
        deposit_rate: null      # R1% (real value off-repo)