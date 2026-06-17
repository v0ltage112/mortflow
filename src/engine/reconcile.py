# src/engine/reconcile.py
"""Model-versus-bank reconciliation for the mortgage engine.

Finance-readable summary
------------------------
This module builds the Reconcile sheet: the side-by-side check that proves the
model's numbers line up with what the bank actually did. It takes the model's
own event log and the bank statement, lines them up on the same date and the
same kind of line (a Payment or an Interest posting), and works out the gap
between the model balance and the bank's running balance on each of those
lines. It then labels each line OK or CHECK against an agreed tolerance, so a
reviewer can scan the column and immediately see which lines, if any, need a
closer look. It does no mortgage maths of its own; it only compares two sets of
numbers that were produced elsewhere.

Technical summary
-----------------
Holds ``build_reconcile``, lifted verbatim from ``run_engine`` in
``simulate.py`` in Phase 5 / S4. It consumes the finished ``events_df`` (the
model event log) and the bank ``actuals`` frame, joins the Payment/Interest
rows on ``[bank_date, type]``, coerces the two balance columns to numeric, and
derives ``diff_model_minus_bank`` plus the four tolerance labels
(``ok_within_1c``, ``ok_within_abs_eur``, ``ok_label``, ``ok_reason``). The
absolute-euro threshold is read from ``inputs.reconcile_ok_abs_eur``. The
function depends only on ``pandas`` and never imports ``simulate``.

Phase 5 / S4 note: pure relocation. The join keys, the diff direction (model
minus bank), and the tolerance defaults are unchanged. The roughly EUR 300
accepted model-vs-bank gap is data, not logic, and is untouched here. The
golden master still reads 46 passed, 2 skipped, plus the S1 characterization
test.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    # Imported for type hints only; no runtime dependency on the schema module,
    # which keeps reconcile.py at the bottom of the dependency graph.
    from .schema import Inputs


def build_reconcile(events_df: pd.DataFrame, actuals: pd.DataFrame, inputs: "Inputs") -> pd.DataFrame:
    """Join the model event log against the bank actuals and label the gaps.

    Finance note: this is the reconciliation step a reviewer reads first. It
    matches each modelled Payment and Interest line to the bank's own line on
    the same date, sets the model balance beside the bank's running balance,
    and flags whether the two agree within tolerance. The OK/CHECK labels are
    the headline of the Reconcile sheet, so getting the join keys and the
    tolerance right here is what makes that sheet trustworthy.

    Parameters
    ----------
    events_df:
        The canonical model event log returned by the daily simulation, one row
        per modelled transaction (Payment, Extra, Lump, Interest).
    actuals:
        The bank statement frame loaded from the lender CSV, carrying the real
        Payment/Interest lines and the bank running balance.
    inputs:
        The validated modelling inputs. Only ``reconcile_ok_abs_eur`` (the
        accepted absolute-euro mismatch) is read here.

    Returns
    -------
    pandas.DataFrame
        One row per reconciled bank Payment/Interest line, carrying the joined
        model amount and balance, the model-minus-bank difference, and the
        tolerance labels.
    """
    # Plain-English progress line for troubleshooting (stderr only; never stdout).
    print("[engine.reconcile] build_reconcile: joining model and bank events", file=sys.stderr)

    # Reconcile: join by date + type (avoids mismatches on same date).
    model_ev = events_df[events_df["kind"].isin(["Payment", "Interest"])].copy()
    model_ev.rename(columns={
        "date": "bank_date",
        "kind": "type",
        "amount": "model_amount",
        "balance": "model_balance",
    }, inplace=True)

    bank_ev = actuals[actuals["type"].isin(["Payment", "Interest"])].copy()
    bank_ev.rename(columns={"date": "bank_date", "run_balance": "bank_running_balance"}, inplace=True)

    rec = pd.merge(
        bank_ev,
        model_ev[["bank_date", "type", "model_amount", "model_balance"]],
        on=["bank_date", "type"], how="left"
    )

    # Coerce numerics and compute diffs/tolerance if both sides exist.
    for c in ("bank_running_balance", "model_balance"):
        if c in rec.columns:
            rec[c] = pd.to_numeric(rec[c], errors="coerce")

    if {"bank_running_balance", "model_balance"}.issubset(set(rec.columns)):
        rec["diff_model_minus_bank"] = rec["model_balance"] - rec["bank_running_balance"]

        # Legacy 1c label (kept for backwards compatibility)
        rec["ok_within_1c"] = rec["diff_model_minus_bank"].abs().le(0.01).map({True: "OK", False: "CHECK"})

        # NEW: configurable absolute-EUR threshold
        thr = float(getattr(inputs, "reconcile_ok_abs_eur", 0.01) or 0.01)
        rec["ok_within_abs_eur"] = rec["diff_model_minus_bank"].abs().le(thr)
        rec["ok_label"] = rec["ok_within_abs_eur"].map({True: "OK", False: "CHECK"})
        rec["ok_reason"] = rec.apply(
            lambda r: (f"|diff|≤€{thr:,.2f}" if pd.notna(r.get("diff_model_minus_bank"))
                       and abs(float(r["diff_model_minus_bank"])) <= thr else ">threshold"),
            axis=1
        )

    return rec


print("[engine.reconcile] reconcile module ready", file=sys.stderr)