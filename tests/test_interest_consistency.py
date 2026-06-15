"""Consistency checks between the monthly ledger and event stream.

Interest is one of the most material numbers in the model.  This test verifies
that the aggregated interest recognised in the monthly table matches what was
posted via individual "Interest" events, year by year.
"""

import pandas as pd


def test_interest_sum_matches_events(engine_outputs):
    """Cross-check yearly interest totals between two reporting layers.

    Why we care
    -----------
    The monthly sheet feeds management reporting while the events log mirrors
    bank postings.  A discrepancy between the two usually means interest was
    double-counted or dropped entirely for a period.  By comparing year-level
    totals (with a cent tolerance) we catch those mismatches without being too
    sensitive to minor rounding differences.
    """

    monthly, _, events = engine_outputs

    md = monthly.copy()
    md["posting_year"] = pd.to_datetime(md["posting_date"]).dt.year
    by_year_monthly = md.groupby("posting_year", as_index=True)["interest_used"].sum().round(2)

    ev = events[events["kind"] == "Interest"].copy()
    ev["year"] = pd.to_datetime(ev["date"]).dt.year
    by_year_events = ev.groupby("year", as_index=True)["amount"].sum().round(2)

    # Align indexes (years) and compare within 1c.
    idx = sorted(set(by_year_monthly.index) | set(by_year_events.index))
    for y in idx:
        m = float(by_year_monthly.get(y, 0.0))
        e = float(by_year_events.get(y, 0.0))
        assert abs(m - e) <= 0.01, f"Year {y}: Monthly={m} vs Events={e}"
