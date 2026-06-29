# src/metrics.py
"""Mortgage model baseline KPI utilities.

This module provides a *single* public function, ``compute_baseline_kpis``,
which turns an amortisation schedule into a compact dictionary of key
performance indicators (KPIs).  The implementation leans on several private
helpers so that each concern is self-contained and clearly documented.  A light
refactor keeps the behaviour stable while dividing the workflow into three
logical stages: argument normalisation, raw aggregation, and optional
enrichments.

Returned keys (when the relevant data are supplied):

* ``total_interest`` – Cumulative interest across the model schedule.
* ``total_principal`` – Principal paid down across the same period.
* ``total_contractual`` – Agreed or projected contractual instalments.
* ``total_overpayment`` – Agreed standing overpayments (the recognised extra).
* ``total_difference`` – Unattributed residual (the Difference column).
* ``total_lumps`` – Lump-sum contributions (if any).
* ``total_paid_all`` – Full debit across the schedule (the total_paid column).
* ``latest_model_eom_balance`` – Ending balance from the last monthly record.
* ``payoff_ym`` – Year-month identifier for the payoff month (if detected).
* ``months_to_clear`` and ``years_to_clear`` – Duration until payoff.
* ``payoff_date`` – Specific payoff date derived from ``events``.
* ``as_of_date`` – Anchor date derived from ``inputs`` (if provided).
* ``next_payment_date`` and ``next_payment_amount`` – Future scheduled payment
  relative to ``as_of_date`` (or to today when the anchor date is unknown).

The helpers are intentionally tolerant to slightly malformed inputs: they
coerce date-like objects, ignore missing columns, and return ``None`` when a
metric cannot be derived.  This makes the KPI computation resilient when called
from multiple front-ends or in intermediate model states.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import datetime as _dt

import pandas as pd


# ===========================================================================
# Section: Shared constants and type aliases
# ===========================================================================

# ``EPSILON`` defines the tolerance used when deciding whether a balance is
# effectively cleared.  Keeping it near zero avoids floating point artefacts
# prematurely declaring a loan paid off, while still accepting minor rounding
# discrepancies.
EPSILON: float = 0.01

# ``KPIBundle`` documents the shape of the mapping returned by all helpers.  It
# keeps the type hints readable in the rest of the module without introducing
# external dependencies (TypedDict, dataclasses, etc.).
KPIBundle = Dict[str, Optional[float]]


# ===========================================================================
# Section: Shared helpers
# ===========================================================================

# NOTE: Each helper below performs a single responsibility that can be reused
# by the main aggregation routine.  This separation keeps
# ``compute_baseline_kpis`` focused on orchestration rather than data hygiene.


def _to_date(x: Any) -> Optional[_dt.date]:
    """Coerce arbitrary objects into :class:`datetime.date` instances.

    The conversion accepts ``None`` (returns ``None``), native ``date``
    objects, and strings formatted as ``YYYY-MM-DD`` or ``YYYY/MM/DD``.  Any
    other value results in ``None`` rather than raising, making downstream
    consumers robust to unexpected user input.
    """

    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if isinstance(x, _dt.date):
        return x
    try:
        # Accept 'YYYY-MM-DD' or 'YYYY/MM/DD'.
        s = str(x).replace("/", "-")
        return _dt.datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _payoff_date_from_events(events_df: Optional[pd.DataFrame]) -> Optional[_dt.date]:
    """Locate the payoff date from a detailed events ledger.

    The events ledger records individual transactions with running balances.
    When the balance first drops below or equal to ``EPSILON`` the loan is
    considered paid off.  Rounding tolerance ensures we do not miss a payoff
    event because of floating-point artefacts.  If the ledger is missing or
    malformed the function returns ``None`` instead of raising.
    """

    if (
        events_df is None
        or events_df.empty
        or "balance" not in events_df.columns
        or "date" not in events_df.columns
    ):
        return None

    hit = events_df.loc[events_df["balance"].fillna(0.0) <= EPSILON]
    if hit.empty:
        return None
    return _to_date(hit.iloc[0]["date"])


def _safe_last_payoff_month(monthly: pd.DataFrame) -> KPIBundle:
    """Derive payoff timeline metrics from the monthly schedule.

    The function inspects the amortisation schedule (one row per month) and
    finds the first entry whose ``model_eom_balance`` is effectively zero.
    ``payoff_ym`` is returned when the schedule carries an ``ym`` column.
    ``months_to_clear`` and ``years_to_clear`` represent the one-based index of
    that payoff row.  Missing inputs produce ``None`` values, ensuring the KPI
    dictionary is always well formed.
    """

    if "model_eom_balance" not in monthly.columns or monthly.empty:
        return {"payoff_ym": None, "months_to_clear": None, "years_to_clear": None}

    done = monthly.loc[monthly["model_eom_balance"].fillna(0.0) <= EPSILON]
    if done.empty:
        return {"payoff_ym": None, "months_to_clear": None, "years_to_clear": None}

    payoff_row = done.iloc[0]
    ym = None
    if "ym" in payoff_row.index and pd.notna(payoff_row["ym"]):
        try:
            ym = int(payoff_row["ym"])
        except Exception:
            ym = None

    # 1-based index position in the full schedule.
    idx_pos = int(done.index[0]) + 1
    years = round(idx_pos / 12.0, 2)

    return {"payoff_ym": ym, "months_to_clear": idx_pos, "years_to_clear": years}


def _sum_or_zero(df: pd.DataFrame, col: str) -> float:
    """Return the sum of ``col`` in ``df`` or ``0.0`` when the column is absent."""

    if col not in df.columns:
        return 0.0
    series = df[col]
    return float(series.fillna(0.0).sum()) if not series.empty else 0.0


def _kpis_from_monthly_only(monthly: pd.DataFrame) -> KPIBundle:
    """Aggregate KPI metrics using only the monthly amortisation schedule.

    This helper focuses on numerical totals derived from the monthly table.
    It intentionally ignores optional metadata (``inputs`` / ``events``) so it
    can be reused whenever only the schedule is available—e.g. when previewing
    model runs in a notebook.
    """

    k: KPIBundle = {}
    k["total_interest"] = _sum_or_zero(monthly, "interest_used")
    k["total_principal"] = _sum_or_zero(monthly, "principal_paid")
    # Phase 7 / S4: the monthly schedule now carries the final attribution
    # vocabulary; payment_amount and extra_amount are retired. Report the agreed
    # split instead. total_paid_all stays the conserved full debit by reading the
    # total_paid column directly (equal to the old base + extra + lump sum to the
    # cent), and total_lumps reads the renamed lump column.
    k["total_contractual"] = _sum_or_zero(monthly, "contractual")
    k["total_overpayment"] = _sum_or_zero(monthly, "overpayment")
    k["total_difference"] = _sum_or_zero(monthly, "difference")
    k["total_lumps"] = _sum_or_zero(monthly, "lump")
    k["total_paid_all"] = _sum_or_zero(monthly, "total_paid")

    if "model_eom_balance" in monthly.columns and not monthly.empty:
        k["latest_model_eom_balance"] = float(
            monthly["model_eom_balance"].ffill().iloc[-1]
        )
    else:
        k["latest_model_eom_balance"] = None

    # Payoff milestones (month index, year-month id, etc.).
    k.update(_safe_last_payoff_month(monthly))
    return k


def _next_payment_from_monthly(
    monthly: pd.DataFrame, as_of: Optional[_dt.date]
) -> KPIBundle:
    """Determine the next scheduled payment relative to ``as_of``.

    When ``as_of`` is ``None`` the computation anchors on ``date.today()``.
    The helper filters rows whose ``payment_date`` is on or after that anchor
    and whose ``contractual`` instalment is positive.  If no such payment exists the
    returned values default to ``None``.
    """

    if (
        "payment_date" not in monthly.columns
        or "contractual" not in monthly.columns
        or monthly.empty
    ):
        return {"next_payment_date": None, "next_payment_amount": None}

    if as_of is None:
        as_of = _dt.date.today()

    m = monthly.copy()
    # Coerce to date.
    m["_pdate"] = pd.to_datetime(m["payment_date"], errors="coerce").dt.date
    m = m.loc[
        (m["_pdate"].notna())
        & (m["_pdate"] >= as_of)
        & (m["contractual"].fillna(0.0) > 0.0)
    ]
    if m.empty:
        return {"next_payment_date": None, "next_payment_amount": None}

    r = m.iloc[0]
    return {
        "next_payment_date": _to_date(r["_pdate"]),
        # Phase 7 / S4: payment_amount is retired; the contractual instalment is
        # its direct successor as the "next scheduled payment" figure.
        "next_payment_amount": float(r["contractual"]),
    }


# ===========================================================================
# Section: Argument normalisation helpers
# ===========================================================================


def _normalise_arguments(
    args: Tuple[Any, ...], kwargs: Dict[str, Any]
) -> Tuple[Any, pd.DataFrame, Optional[pd.DataFrame]]:
    """Resolve the ``inputs``, ``monthly`` and ``events`` artefacts from mixed arguments.

    The public API historically accepted both positional and keyword styles.
    Rather than keep the branching logic inline, the handling is centralised in
    this helper so that ``compute_baseline_kpis`` can read as a high-level
    recipe.  The helper mirrors the legacy behaviour exactly, raising
    ``TypeError`` when no monthly schedule is supplied.
    """

    inputs: Any = None
    monthly: Optional[pd.DataFrame] = None
    events: Optional[pd.DataFrame] = None

    # Prefer keyword arguments—callers can be explicit without caring about
    # historical ordering.
    if "monthly" in kwargs and isinstance(kwargs["monthly"], pd.DataFrame):
        monthly = kwargs["monthly"]
    if "inputs" in kwargs:
        inputs = kwargs["inputs"]
    if "events" in kwargs and isinstance(kwargs["events"], pd.DataFrame):
        events = kwargs["events"]

    # Fall back to positional arguments when keywords were not provided.  This
    # branch mirrors the original signature ``(inputs, monthly, events=None)``
    # and therefore keeps compatibility with historical call sites.
    if monthly is None:
        if len(args) == 1 and isinstance(args[0], pd.DataFrame):
            monthly = args[0]
        elif len(args) >= 2 and isinstance(args[1], pd.DataFrame):
            inputs = args[0]
            monthly = args[1]
            if len(args) >= 3 and isinstance(args[2], pd.DataFrame):
                events = args[2]

    if monthly is None:
        raise TypeError(
            "compute_baseline_kpis expected (monthly) or (inputs, monthly, events) "
            "but could not locate a monthly DataFrame."
        )

    return inputs, monthly, events


# ===========================================================================
# Section: Public API (backwards-compatible entry point)
# ===========================================================================


def compute_baseline_kpis(*args, **kwargs) -> KPIBundle:
    """Compute KPI aggregates from the provided amortisation artefacts.

    Parameters
    ----------
    * ``monthly`` (:class:`pandas.DataFrame`): The only mandatory argument.
      It may be supplied positionally or via the ``monthly`` keyword.
    * ``inputs``: Optional object containing configuration metadata.  The
      function only inspects ``inputs.modelling.as_of_date`` (attribute or
      dictionary style access).
    * ``events`` (:class:`pandas.DataFrame`, optional): Detailed ledger used to
      infer the precise payoff date.

    Returns
    -------
    ``Dict[str, Optional[float]]``
        A mapping of KPI names to values as documented in the module-level
        description.  Missing metrics are represented as ``None``.
    """

    # ------------------------------------------------------------------
    # Phase 1 – Normalise positional/keyword arguments.
    # ------------------------------------------------------------------
    inputs, monthly, events = _normalise_arguments(args, kwargs)

    # ------------------------------------------------------------------
    # Phase 2 – Aggregate KPI values from the monthly schedule.
    # ------------------------------------------------------------------
    kpis = _kpis_from_monthly_only(monthly)

    # ------------------------------------------------------------------
    # Phase 3 – Optional enrichments sourced from inputs/events.
    # ------------------------------------------------------------------
    as_of = None
    if inputs is not None:
        # Tolerate either dataclass-like attributes or dict-style access.
        metadata = None
        try:
            metadata = getattr(inputs, "modelling", None) or {}
        except Exception:
            metadata = {}
        if isinstance(inputs, dict):
            metadata = inputs.get("modelling", metadata) or metadata
        as_of = _to_date((metadata or {}).get("as_of_date"))
    kpis["as_of_date"] = as_of

    kpis["payoff_date"] = _payoff_date_from_events(events)
    kpis.update(_next_payment_from_monthly(monthly, as_of))

    return kpis
