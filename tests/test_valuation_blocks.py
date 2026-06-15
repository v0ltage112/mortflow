"""Regression tests for valuation blocks (explicit revaluations).

Valuation blocks let users override the default growth curve with dated
revaluations.  They are central to keeping the model aligned with surveyor
reports.  The tests below confirm that a block updates both the base value and
the subsequent growth slope.
"""

from dataclasses import replace
from datetime import date

from src.engine import ValuationBlock, property_value_on


def test_revaluation_changes_base_and_growth(inputs):
    """Inject a revaluation and assert the new base and slope are respected.

    Why we care
    -----------
    Analysts frequently add valuation blocks when a property is reappraised.
    If the engine fails to anchor to the new base value or to apply the
    configured growth rate thereafter, the loan-to-value projections become
    unreliable.  The numbers we assert against come directly from the fixture
    configuration (600k base with 1% annual growth).
    """

    vb = ValuationBlock(start=date(2028, 4, 1), base_value=600000.0, growth_pa=0.01)
    inputs_with_block = replace(inputs, valuation_blocks=[vb])

    # On the block start date, property_value_on should yield the new base.
    pv_start = property_value_on(inputs_with_block, date(2028, 4, 1))
    assert abs(pv_start - 600000.0) <= 1.0

    # One year later the value should have compounded by ~1% (≈ €606k).
    pv_1y = property_value_on(inputs_with_block, date(2029, 4, 1))
    assert abs(pv_1y - 606000.0) <= 10.0
