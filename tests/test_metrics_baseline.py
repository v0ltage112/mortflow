"""Minimal smoke tests for the KPI computation layer.

The `compute_baseline_kpis` function is deliberately lightweight yet critical:
it powers the headline dashboard numbers that stakeholders review every time we
ship a scenario.  This module keeps a single, well-documented smoke test that
catches accidental API drift (missing parameters, renamed keys, etc.) without
over-constraining the implementation.
"""

from src.engine import load_inputs
from src.metrics import compute_baseline_kpis


# ---------------------------------------------------------------------------
# Smoke-test the KPI surface
# ---------------------------------------------------------------------------

def test_compute_baseline_kpis_smoke(inputs_path, engine_outputs):
    """Load the KPI snapshot for a real case and check for key markers.

    Why we care
    -----------
    The KPI layer is often touched when new business metrics are introduced.
    This test confirms that the function still accepts the same signature and
    returns the expected structure (a mapping with at least the `as_of_date`
    field).  If the call suddenly raises, or if the shape changes, dashboards
    and CLI tools that read the KPIs will break.  The assertion set is kept
    intentionally small so the test remains a guard rather than a maintenance
    burden.
    """

    inputs = load_inputs(inputs_path)
    monthly, _, events = engine_outputs

    # The call itself is the main thing we exercise; any exception means the
    # engine/metrics contract drifted.
    kpis = compute_baseline_kpis(inputs, monthly, events)

    # Light-touch checks on the return type and one key field that downstream
    # consumers rely on for display.
    assert isinstance(kpis, dict)
    assert "as_of_date" in kpis
