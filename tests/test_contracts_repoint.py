# tests/test_contracts_repoint.py
"""Phase 10 / S2: lock the contracts-driven rate + instalment repoint.

Finance-readable summary
------------------------
S2 flips the engine from the legacy month-number rate_blocks and overpay_rules
onto the date-based contracts model, and converts Property A's sample inputs to
that schema. This test proves the conversion is faithful at the seams a reader
cares about: Property A now loads as three contracts with the legacy scalar
constructs empty, the loan-level facts are sourced from the new keys, and the
contract-derived rate lookup returns the same rate in each contract window that
the retired rate_blocks used to. The byte-identical schedule itself is pinned by
the golden-master and characterization suites; this test guards the wiring.

Technical summary
-----------------
Loads the converted Property A sample through load_inputs and asserts the
resolved Inputs (contracts populated, rate_blocks / overpay_rules empty, the
scalar loan facts derived from the new keys, known_first_payment taken from the
first contract's instalment). It then exercises rate_lookup_for on the boundary
months of the three contracts.
"""
from __future__ import annotations

import math
from pathlib import Path

from src.engine import load_inputs
from src.engine.monthly import rate_lookup_for


REPO_ROOT = Path(__file__).resolve().parent.parent
PROPERTY_A = REPO_ROOT / "data_sample" / "property_a" / "inputs.sample.yaml"


def test_property_a_loads_as_contracts():
    """Property A resolves to the contracts model with the legacy fields empty."""
    inputs = load_inputs(PROPERTY_A)

    # Three contracts, time-sorted, replacing the three legacy rate blocks.
    assert [c.id for c in inputs.contracts] == ["A1", "A2", "A3"]
    # The legacy month-number constructs are retired for the converted sample.
    assert inputs.rate_blocks == []
    assert inputs.overpay_rules == []
    # loan_v2 is resolved for a contracts file.
    assert inputs.loan_v2 is not None

    # Loan-level scalar facts are sourced from the new keys.
    assert math.isclose(inputs.principal_at_drawdown, 495000.0, abs_tol=1e-6)
    assert math.isclose(inputs.property_price, 550000.0, abs_tol=1e-6)
    # The known first payment is the first contract's agreed instalment.
    assert math.isclose(inputs.known_first_payment, 2123.44, abs_tol=1e-6)
    # repayment_day 5 carries through to the projected-payment day.
    assert inputs.repayment_day_default == 5


def test_property_a_standing_overpayment_carried():
    """The month-17 / EUR200 standing extra now rides on contract A1."""
    inputs = load_inputs(PROPERTY_A)
    a1 = inputs.contracts[0]
    assert a1.standing_overpayment is not None
    assert math.isclose(a1.standing_overpayment.amount, 200.0, abs_tol=1e-6)


def test_contract_rate_lookup_matches_windows():
    """The contract-derived rate lookup reproduces the retired rate windows."""
    inputs = load_inputs(PROPERTY_A)
    rate_of = rate_lookup_for(inputs)

    # A1 months 1..48 at 3.65%.
    assert math.isclose(rate_of(1), 0.0365, abs_tol=1e-12)
    assert math.isclose(rate_of(48), 0.0365, abs_tol=1e-12)
    # A2 months 49..97 at 4.75%.
    assert math.isclose(rate_of(49), 0.0475, abs_tol=1e-12)
    assert math.isclose(rate_of(97), 0.0475, abs_tol=1e-12)
    # A3 months 98+ at 4.00% (open-ended tail).
    assert math.isclose(rate_of(98), 0.0400, abs_tol=1e-12)
    assert math.isclose(rate_of(420), 0.0400, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# REVIEW-001: contract contiguity validation.
# ---------------------------------------------------------------------------

def _write_inputs(tmp_path, contracts):
    """Write a minimal contracts inputs file and return its path."""
    import yaml

    raw = {
        "meta": {"property_id": "t", "name": "T", "kind": "investment"},
        "loan": {
            "property_id": "t",
            "lender": "boi",
            "drawdown_amount": 100000,
            "drawdown_date": "2024-01-01",
            "total_term_months": 120,
            "property_value": 150000,
            "repayment_day": 5,
            "first_payment_date": "2024-02-05",
            "contracts": contracts,
        },
    }
    p = tmp_path / "inputs.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return p


def test_contiguous_contracts_load(tmp_path):
    """A contiguous contracts array (each starts the day after the prior ends) loads."""
    p = _write_inputs(tmp_path, [
        {"id": "C1", "start_date": "2024-01-01", "end_date": "2026-01-01", "rate": 0.03},
        {"id": "C2", "start_date": "2026-01-02", "end_date": "2028-01-01", "rate": 0.04},
        {"id": "C3", "start_date": "2028-01-02", "rate": 0.045},
    ])
    inputs = load_inputs(p)
    assert [c.id for c in inputs.contracts] == ["C1", "C2", "C3"]


def test_contract_gap_raises(tmp_path):
    """REVIEW-001: a gap between contracts is a config error, not a silent borrow."""
    p = _write_inputs(tmp_path, [
        {"id": "C1", "start_date": "2024-01-01", "end_date": "2026-01-01", "rate": 0.03},
        # C2 starts two days after C1 ends: a one-day gap.
        {"id": "C2", "start_date": "2026-01-03", "rate": 0.04},
    ])
    import pytest

    with pytest.raises(ValueError, match="not contiguous"):
        load_inputs(p)


def test_contract_overlap_raises(tmp_path):
    """REVIEW-001: an overlap between contracts is a config error."""
    p = _write_inputs(tmp_path, [
        {"id": "C1", "start_date": "2024-01-01", "end_date": "2026-01-01", "rate": 0.03},
        # C2 starts before C1 ends: an overlap.
        {"id": "C2", "start_date": "2025-12-31", "rate": 0.04},
    ])
    import pytest

    with pytest.raises(ValueError, match="not contiguous"):
        load_inputs(p)


def test_open_ended_contract_before_last_raises(tmp_path):
    """REVIEW-001: only the final contract may be open-ended."""
    p = _write_inputs(tmp_path, [
        {"id": "C1", "start_date": "2024-01-01", "rate": 0.03},  # open-ended, not last
        {"id": "C2", "start_date": "2026-01-02", "rate": 0.04},
    ])
    import pytest

    with pytest.raises(ValueError, match="only the final contract may be open-ended"):
        load_inputs(p)


# ---------------------------------------------------------------------------
# REVIEW-004: a missing lender profile warns rather than degrading silently.
# ---------------------------------------------------------------------------

def test_missing_lender_profile_warns(tmp_path, capsys):
    """REVIEW-004: a lender key with no profile warns on stderr and still loads."""
    p = _write_inputs(tmp_path, [
        {"id": "C1", "start_date": "2024-01-01", "rate": 0.03},
    ])
    # Point the lender at a key with no discoverable profile beside the inputs.
    import yaml

    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw["loan"]["lender"] = "no_such_lender"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")

    inputs = load_inputs(p)
    captured = capsys.readouterr()
    # The run still loads (not fatal), but the warning names the missing profile.
    assert inputs.profile is None
    assert "no_such_lender" in captured.err
    assert "not found" in captured.err


# ---------------------------------------------------------------------------
# REVIEW-003: an empty contracts array is a config error, not a legacy file.
# ---------------------------------------------------------------------------

def test_empty_contracts_array_raises(tmp_path):
    """REVIEW-003: 'contracts: []' is an error, not a silent legacy fallback."""
    import pytest

    p = _write_inputs(tmp_path, [])
    with pytest.raises(ValueError, match="present but empty"):
        load_inputs(p)


def test_absent_contracts_key_is_legacy(tmp_path):
    """A file with no 'contracts' key at all still loads as a legacy file."""
    import yaml

    raw = {
        "meta": {"property_id": "t", "name": "T", "kind": "investment"},
        "loan": {
            "property_id": "t",
            "drawdown_amount": 100000,
            "drawdown_date": "2024-01-01",
            "total_term_months": 120,
            "property_price": 150000,
            "repayment_day_default": 5,
            "first_payment_date": "2024-02-05",
            "known_first_payment": 900.0,
        },
        "rate_blocks": [{"start_month": 1, "end_month": 120, "annual_rate": 0.03, "kind": "fixed"}],
    }
    p = tmp_path / "legacy.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    inputs = load_inputs(p)
    # No contracts, so the legacy rate_blocks path is used.
    assert inputs.contracts == []
    assert inputs.loan_v2 is None


# ---------------------------------------------------------------------------
# REVIEW-005: a malformed repayment_day raises rather than silently becoming 1.
# ---------------------------------------------------------------------------

def test_bad_repayment_day_raises(tmp_path):
    """REVIEW-005: a non-numeric repayment_day is a config error."""
    import pytest
    import yaml

    p = _write_inputs(tmp_path, [
        {"id": "C1", "start_date": "2024-01-01", "rate": 0.03},
    ])
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw["loan"]["repayment_day"] = "whenever"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="repayment_day"):
        load_inputs(p)


def test_out_of_range_repayment_day_raises(tmp_path):
    """REVIEW-005: a repayment_day outside 1-31 is a config error."""
    import pytest
    import yaml

    p = _write_inputs(tmp_path, [
        {"id": "C1", "start_date": "2024-01-01", "rate": 0.03},
    ])
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw["loan"]["repayment_day"] = 45
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="out of range"):
        load_inputs(p)


def test_month_end_repayment_day_loads(tmp_path):
    """REVIEW-005: 'month_end' still resolves to 31 (clamped to the real month end)."""
    p = _write_inputs(tmp_path, [
        {"id": "C1", "start_date": "2024-01-01", "rate": 0.03},
    ])
    import yaml

    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw["loan"]["repayment_day"] = "month_end"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert load_inputs(p).repayment_day_default == 31


# ---------------------------------------------------------------------------
# REVIEW-013: an unrecognised boolean string raises rather than reading as False.
# ---------------------------------------------------------------------------

def test_bad_output_boolean_raises(tmp_path):
    """REVIEW-013: 'write_excel: maybe' is a config error, not a silent False."""
    import pytest
    import yaml

    p = _write_inputs(tmp_path, [
        {"id": "C1", "start_date": "2024-01-01", "rate": 0.03},
    ])
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw["output"] = {"write_excel": "maybe"}
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="expected a boolean"):
        load_inputs(p)


def test_quoted_output_boolean_reads_correctly(tmp_path):
    """REVIEW-013: a quoted 'false' reads as False, not as a truthy string."""
    import yaml

    p = _write_inputs(tmp_path, [
        {"id": "C1", "start_date": "2024-01-01", "rate": 0.03},
    ])
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw["output"] = {"write_excel": "false", "write_csv": "true"}
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    out = load_inputs(p).output
    assert out.write_excel is False
    assert out.write_csv is True