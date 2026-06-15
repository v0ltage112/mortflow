"""Scenario smoke tests that mirror key customer promises.

These checks use the fixtures defined in :mod:`tests.conftest` and act as a
high-signal canary whenever the engine, reconciliation logic, or portal metrics
change.  Each test documents what a pass/fail means for stakeholders so the
intent stays clear.
"""

from pathlib import Path

import pytest
import yaml

from src.engine import compute_portal_style_metrics


# ---------------------------------------------------------------------------
# Reconcile sheet guard-rails
# ---------------------------------------------------------------------------

def test_reconcile_worst_diff_within_200(engine_outputs):
    """Keep the worst model-vs-bank difference within €200.

    Why we care
    -----------
    The reconcile sheet is the primary safety check for operations.  Values
    outside €200 signal either genuine divergence or a model bug.  By locking in
    the historical tolerance we get an immediate alert when the underlying
    amortisation logic changes.
    """

    _, rec, _ = engine_outputs
    diffs = rec["diff_model_minus_bank"].abs().dropna()
    assert not diffs.empty, "No diffs to check; is reconcile empty?"
    assert diffs.max() <= 200.00 + 1e-6


# ---------------------------------------------------------------------------
# Portal snapshot alignment
# ---------------------------------------------------------------------------

def test_portal_snapshot_principal_within_50(engine_outputs, inputs, inputs_path, portal_snapshot_date):
    """Portal-style principal should closely match the latest portal balance.

    Why we care
    -----------
    Customer success teams compare our output with the lender's portal.  A
    €50 window reflects the typical fluctuation caused by interest posting cut-
    offs.  If we exceed that window the support scripts raise an incident.
    """

    if portal_snapshot_date is None:
        pytest.skip("No portal snapshot configured in YAML.")

    monthly, _, events = engine_outputs
    portal = compute_portal_style_metrics(portal_snapshot_date, inputs, events, monthly)
    model_principal = portal["principal_excl_unposted"]
    assert model_principal is not None, "Portal-style principal not computed."

    raw = yaml.safe_load(Path(inputs_path).read_text())
    snaps = (raw.get("reconcile") or {}).get("snapshots") or []
    latest = max(snaps, key=lambda s: str(s["date"]))
    bank_balance = float(latest["balance"])

    assert abs(model_principal - bank_balance) <= 50.00 + 1e-6


# ---------------------------------------------------------------------------
# Month-end balance comparisons
# ---------------------------------------------------------------------------

def test_month_end_diffs_within_300(engine_outputs):
    """Model vs bank balances should align in months with posted interest.

    Why we care
    -----------
    Month-end numbers are what auditors scrutinise.  We only enforce the check
    when the bank has actually posted interest in that month; otherwise, timing
    differences are expected.  If the worst case exceeds €300 we raise a helpful
    table so engineers know which months to investigate.
    """

    import pandas as pd

    monthly, _, _ = engine_outputs
    if "eom_diff_model_minus_bank" not in monthly.columns:
        pytest.skip("Monthly EOM diff column not present.")

    # Only check months with a bank interest posting in that month.
    mask = (monthly.get("bank_posted_interest_present", False)) & (
        monthly["bank_eom_running_balance"].notna()
    )
    diffs = monthly.loc[mask, "eom_diff_model_minus_bank"].abs().dropna()

    if diffs.empty:
        pytest.skip("No months with bank interest posting to check.")

    max_allowed = 300.00
    worst = float(diffs.max())

    if worst > max_allowed + 1e-6:
        # Build a friendly table of top offenders to display in the failure message.
        top = (
            monthly.loc[mask, ["ym", "model_eom_balance", "bank_eom_running_balance", "eom_diff_model_minus_bank"]]
            .assign(abs_diff=lambda d: d["eom_diff_model_minus_bank"].abs())
            .sort_values("abs_diff", ascending=False)
            .head(5)
        )
        raise AssertionError(
            f"Month-end diffs exceed €{max_allowed:.0f}. Top offenders:\n"
            f"{top.to_string(index=False)}\n"
            f"Hint: If a month has no bank 'Interest' line, a large diff is normal. "
            f"Add the interest to actuals for that month (if you have it) or leave as-is."
        )


# ---------------------------------------------------------------------------
# Interest-only holiday behaviour
# ---------------------------------------------------------------------------

def test_interest_only_holiday_no_principal(engine_outputs):
    """Interest-only holiday (Mar–Jul 2024) should not pay down principal.

    Why we care
    -----------
    The fixture includes a configured holiday where the borrower only pays
    interest.  Any principal reduction during that window indicates a regression
    in how holidays or payment schedules are modelled.
    """

    monthly, _, _ = engine_outputs
    mask = monthly["ym"].between(202403, 202407)  # Mar..Jul 2024 inclusive
    principal = monthly.loc[mask, "principal_paid"].fillna(0).sum()
    assert abs(principal) <= 0.01
