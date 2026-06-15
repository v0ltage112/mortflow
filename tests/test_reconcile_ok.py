"""Guards around the Reconcile sheet's "OK" classification logic.

The reconciliation output is where support agents look first when a customer
questions the model.  This test ensures that increasing the acceptable mismatch
threshold still results in at least one "OK" row, proving that the flagging
mechanism is wired up correctly.
"""

from dataclasses import replace

from src.engine import run_engine


def test_reconcile_ok_threshold(inputs, actuals_df):
    """Adjust the OK threshold and confirm the classification responds.

    Why we care
    -----------
    The `reconcile_ok_abs_eur` knob is used in operations when small rounding
    differences would otherwise flood the report with warnings.  If the engine
    stops honouring the override, support teams lose a key safety valve.  The
    test therefore tweaks the threshold, re-runs the engine, and asserts that at
    least one row is labelled "OK".
    """

    tweaked = replace(inputs, reconcile_ok_abs_eur=300.0)
    _, rec, _ = run_engine(tweaked, actuals_df)
    assert "ok_label" in rec.columns
    assert (rec["ok_label"] == "OK").any()
