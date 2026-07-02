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