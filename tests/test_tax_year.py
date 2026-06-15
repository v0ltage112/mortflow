"""High-level checks for the derived tax-year report.

The Tax Year worksheet is where finance teams reconcile the model against
statutory reporting (interest deductions, occupancy ratios, etc.).  This test
module validates the broad structure of that report so any regression in the
aggregation logic is caught during CI instead of in a spreadsheet audit.
"""

from pathlib import Path

import yaml

from src.tax import compute_tax_year_table, load_tenancies
from tests.conftest import inputs_path


# ---------------------------------------------------------------------------
# Tax Year table schema and value ranges
# ---------------------------------------------------------------------------

def test_tax_year_sheet_basic(engine_outputs, inputs_path):
    """Check the yearly tax summary for expected columns and sane values.

    Why we care
    -----------
    The tax-year output ties directly into statutory filings.  Missing columns
    or negative ratios would send accountants on a goose chase.  This test is
    intentionally broad: it confirms the schema, enforces non-negativity on
    currency metrics, ensures ratios remain within [0, 1], and validates that
    allowable interest never exceeds the bank-posted interest for a year.
    """

    monthly, _, _ = engine_outputs
    raw_cfg = yaml.safe_load(Path(inputs_path).read_text())

    # Load tenancy information using the same precedence order as production:
    # configuration override first, fall back to the sample pack otherwise.
    _REPO_ROOT = Path(__file__).resolve().parents[1]
    tenancy_str = (raw_cfg.get("tax") or {}).get("tenancy_file", "tenancy.local.yaml")
    pref = Path(inputs_path).parent / Path(tenancy_str).name
    fb   = _REPO_ROOT / "data_sample" / "property_a" / "tenancy.sample.yaml"
    tenancies, policy, _ = load_tenancies(pref, fb)

    tax_year_df, ten_log_df = compute_tax_year_table(monthly, raw_cfg, tenancies, policy)

    # --- Column presence ------------------------------------------------------
    needed = {
        "year",
        "interest_posted",
        "allowable_interest_s97",
        "principal_paid",
        "avg_occupancy_ratio",
        "deductible_pct",
    }
    assert needed.issubset(set(tax_year_df.columns)), f"Missing columns: {needed - set(tax_year_df.columns)}"
    assert not tax_year_df.empty, "TaxYear is empty."

    # --- Value ranges --------------------------------------------------------
    # Monetary fields should never go negative; ratios stay within [0, 1].
    assert (tax_year_df["interest_posted"] >= -1e-6).all()
    assert (tax_year_df["allowable_interest_s97"] >= -1e-6).all()
    assert (tax_year_df["principal_paid"] >= -1e-6).all()
    assert ((tax_year_df["avg_occupancy_ratio"] >= -1e-9) & (tax_year_df["avg_occupancy_ratio"] <= 1 + 1e-9)).all()
    assert ((tax_year_df["deductible_pct"] >= 0 - 1e-9) & (tax_year_df["deductible_pct"] <= 1 + 1e-9)).all()

    # Allowable interest cannot exceed what the bank actually charged.  A small
    # tolerance accounts for rounding when slicing by tax-year boundaries.
    assert (tax_year_df["allowable_interest_s97"] <= tax_year_df["interest_posted"] + 0.01).all()

    # --- Tenancy log presence -------------------------------------------------
    # The tenancy log is used by reviewers to cross-check occupancy-based
    # deductions; it should never be empty if the tax-year table exists.
    assert ten_log_df is not None and not ten_log_df.empty, "TenancyLog should not be empty."
