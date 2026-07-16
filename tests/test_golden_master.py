"""Golden-master regression test for the mortflow cashflow engine.

This test pins the engine's current numeric behaviour. It regenerates every
locked output from the bundled `data_sample/` data into a throwaway temp
directory, then asserts each file matches a committed fixture to two decimal
places (CSV) or byte-for-byte (the effective-inputs YAML).

The point is refactor-safety: a refactor may restructure `src/engine.py` freely,
and this test fails loudly the moment any number moves beyond half a cent.

Fixtures live in `tests/fixtures/golden/` and were captured from runs verified
against the bank on real data, then locked from the de-identified samples that
reproduce the same figures.

Phase 8 / S3 note: the engine writes every CSV into a `csv/` sub-folder
(per-property `<slug>/csv/` and a top-level `csv/` for the rollup), so the
produced files this test reads live one level deeper than the committed
fixtures. A fixture is just the locked expected value; its on-disk path is
independent of the runtime output layout, and the values are byte-identical, so
the suite stays green without moving the fixtures.

Phase 11 / S1 note: the golden master now locks more than one property. Property
A (investment, tax on) emits the Form 11 tax sheets; Property B (primary
residence, tax off) does not. Each scope therefore carries its own locked file
list, and the per-property CSV and effective-inputs tests are parametrised over
every locked scope. Enabling Property B also changes the portfolio rollup, so
`portfolio_summary.csv` is re-baselined alongside the new `property-b` fixtures.

Phase 11 / S2 note: Property C (Paragon, owned outright) is added as a
valuation-only scope. It has no mortgage, so it emits neither the baseline nor
the loan/reconcile/tax CSVs; its single locked output is the value-over-time
`valuation_schedule.csv`. The effective-inputs YAML lock therefore applies only
to the mortgage scopes that run through the baseline tool (see
`BASELINE_INPUTS_SCOPES`). Enabling C adds a third row to the portfolio rollup,
so `portfolio_summary.csv` is re-baselined again; under the S2 interim currency
guard C reports in PKR and its value is held out of the euro `property_value`
column, so the euro aggregate itself is unchanged.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest


def _find_repo_root(start: Path) -> Path:
    """Return the repo root by walking up from this file.

    The repo root is the first ancestor that contains both the `tools`
    package and the `data_sample` directory, so the test resolves correctly
    no matter how deep under the repo the file is placed (a stray
    `tests/tests/` nesting, for example, still works).
    """
    # Check this file's own directory first, then each parent in turn.
    for candidate in (start, *start.parents):
        # Only the repo root holds both of these side by side.
        if (candidate / "tools").is_dir() and (candidate / "data_sample").is_dir():
            return candidate
    # Fail loudly rather than silently resolving to the wrong directory.
    raise RuntimeError(
        "Could not locate the mortflow repo root: no ancestor of "
        f"{start} contains both tools/ and data_sample/."
    )


# Resolve the repo root from this file's location, robust to where it sits.
REPO_ROOT = _find_repo_root(Path(__file__).resolve().parent)
# Committed "expected" outputs.
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "golden"
# Bundled sample portfolio that the pipeline runs against.
SAMPLE_PORTFOLIO = REPO_ROOT / "data_sample" / "portfolio.yaml"

# Phase 8 / S3: the engine writes every CSV into this sub-folder, both under each
# property folder and at the output root for the rollup. Produced files sit at
# <scope>/csv/<name>; the committed fixtures stay at <scope>/<name>.
CSV_SUBDIR = "csv"

# Phase 11 / S1: per-scope locked file lists. Property A is an investment with
# tax on, so it emits the Form 11 tax sheets; Property B is a primary residence
# with tax off, so it does not. The common set is everything both emit.
COMMON_PROPERTY_CSV_FILES = [
    "baseline_monthly.csv",
    "baseline_reconcile.csv",
    "baseline_events_daily.csv",
    "schedule_monthly.csv",
    "reconcile.csv",
    "events_daily.csv",
]
# Extra CSVs only a tax-on property emits (the Form 11 reporting sheets).
TAX_CSV_FILES = [
    "tax_year.csv",
    "tax_audit.csv",
]
# Phase 11 / S2: a valuation-only property (owned outright, no mortgage) emits
# only the value-over-time series. It has no baseline, loan, reconcile, or tax
# files, so its locked list is just this one CSV.
VALUATION_ONLY_CSV_FILES = [
    "valuation_schedule.csv",
]
# Locked CSVs per property scope. Add a scope here to pin another property.
PROPERTY_CSV_FILES = {
    "property-a": COMMON_PROPERTY_CSV_FILES + TAX_CSV_FILES,
    "property-b": COMMON_PROPERTY_CSV_FILES,
    "property-c": VALUATION_ONLY_CSV_FILES,
}
# Flattened (scope, filename) pairs so each file is an independent test case.
PROPERTY_CSV_CASES = [
    (scope, name)
    for scope, names in PROPERTY_CSV_FILES.items()
    for name in names
]
# Portfolio-level CSV written at the output root (aggregates every enabled property).
ROOT_CSV_FILES = ["portfolio_summary.csv"]
# Effective-inputs snapshot is locked byte-for-byte (not at 2dp), one per scope.
YAML_FILE = "baseline.effective.inputs.yaml"
# Phase 11 / S2: the effective-inputs snapshot is a baseline-tool artefact, so it
# exists only for mortgage-bearing scopes. A valuation-only property (property-c)
# never runs the baseline tool, so it is excluded from the byte-equal lock.
BASELINE_INPUTS_SCOPES = ["property-a", "property-b"]

# Half a cent: two monetary values that agree to 2dp never differ by more.
MONEY_ATOL = 0.005


def _run_pipeline(out_dir: Path) -> None:
    """Regenerate every sample output into `out_dir` via the real CLIs.

    Mirrors `run_sample.bat` exactly: baseline first, then portfolio, both
    pointed at the bundled `data_sample` portfolio and the temp out dir.

    Phase 11 / S2: the sample portfolio now also enables Property C (owned
    outright). The baseline tool has no contractual baseline to build for a
    no-mortgage property and skips it; the portfolio tool runs C through the
    valuation-only path and emits its `valuation_schedule.csv`.
    """
    # Force data + out locations through env so the run never depends on a
    # developer's paths.local.yaml. The explicit --out below still wins.
    env = dict(os.environ)
    env["MORTGAGE_DATA_DIR"] = str(REPO_ROOT / "data_sample")
    env["MORTGAGE_OUT_DIR"] = str(out_dir)
    # Force the child interpreter to UTF-8 for stdio. Under pytest the
    # subprocess writes to a pipe, which on Windows defaults to the legacy
    # code page (cp1252) and cannot encode characters the CLIs print (such as
    # the right-arrow in "Building baseline -> ..."), which would crash the run
    # with a UnicodeEncodeError. UTF-8 mode keeps the output portable.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # Both tools take the same portfolio + out root, run from the repo root so
    # "-m tools.x" can import src/ and tools/.
    for module in ("tools.baseline", "tools.portfolio"):
        subprocess.run(
            [
                sys.executable,
                "-m",
                module,
                "--portfolio",
                str(SAMPLE_PORTFOLIO),
                "--out",
                str(out_dir),
            ],
            cwd=str(REPO_ROOT),  # repo root must be importable under -m
            env=env,
            check=True,  # raise immediately if either CLI exits non-zero
        )


@pytest.fixture(scope="session")
def generated_out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run the sample pipeline once per session and reuse the output dir."""
    out_dir = tmp_path_factory.mktemp("golden_out")
    _run_pipeline(out_dir)
    return out_dir


def _format_money(value: object) -> str:
    """Format a value with thousands separators and 2dp for readable diffs.

    Numbers become e.g. "1,234.50"; anything non-numeric is returned as text so
    the message still makes sense for label and date columns.
    """
    try:
        # float() handles ints, numpy floats and numeric strings alike.
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _assert_csv_matches(actual_path: Path, expected_path: Path) -> None:
    """Compare a produced CSV against its locked fixture with a plain report.

    Numbers must agree to two decimal places (half a cent); text and dates must
    match exactly. On any difference this raises an AssertionError whose message
    is written for a non-developer: it names the file, says how many cells moved,
    and points to the single worst change with its row, column, both values and
    the gap in euros.
    """
    # A missing file on either side is a setup problem, not a silent pass.
    assert expected_path.exists(), (
        f"{expected_path.name}: no locked fixture found at {expected_path}. "
        "Re-capture the fixtures before running the test."
    )
    assert actual_path.exists(), (
        f"{actual_path.name}: the pipeline did not produce this file at "
        f"{actual_path}. The engine run itself may have failed."
    )
    # Read both sides the same way so columns and rows line up positionally.
    actual = pd.read_csv(actual_path)
    expected = pd.read_csv(expected_path)
    name = actual_path.name

    # 1) The set and order of columns is part of the locked contract.
    if list(actual.columns) != list(expected.columns):
        missing = [c for c in expected.columns if c not in actual.columns]
        added = [c for c in actual.columns if c not in expected.columns]
        raise AssertionError(
            f"{name}: the columns changed.\n"
            f"  Locked columns:   {list(expected.columns)}\n"
            f"  Produced columns: {list(actual.columns)}\n"
            f"  Missing now:    {missing or 'none'}\n"
            f"  New/unexpected: {added or 'none'}"
        )

    # 2) Row counts must match before we can compare cell by cell.
    if len(actual) != len(expected):
        raise AssertionError(
            f"{name}: the number of rows changed. The locked file has "
            f"{len(expected)} rows; the run produced {len(actual)}. "
            "A different row count usually means the schedule itself changed."
        )

    # 3) Compare every column. Numbers use the half-a-cent tolerance; text and
    #    dates must match exactly. Collect one readable line per changed column
    #    and remember the single largest money gap across the whole file.
    differences: list[str] = []
    worst_gap = 0.0
    worst_line = ""
    for column in expected.columns:
        exp_col = expected[column]
        act_col = actual[column]
        # Treat a column as numeric only when both sides are numeric AND neither
        # side is boolean. Pandas reports true/false columns as numeric, but
        # subtracting them raises a TypeError, so booleans go to exact-match.
        numeric = (
            pd.api.types.is_numeric_dtype(exp_col)
            and pd.api.types.is_numeric_dtype(act_col)
            and not pd.api.types.is_bool_dtype(exp_col)
            and not pd.api.types.is_bool_dtype(act_col)
        )
        if numeric:
            # Per-row absolute difference; NaN where a value is missing.
            gap = (act_col - exp_col).abs()
            # A value present on exactly one side is always a real difference.
            one_sided = act_col.isna() ^ exp_col.isna()
            moved = ((gap > MONEY_ATOL) & gap.notna()) | one_sided
            if not moved.any():
                continue
            count = int(moved.sum())
            if gap[moved].notna().any():
                # Point at the biggest genuine numeric drift in this column.
                idx = gap[moved].idxmax()
                this_gap = float(gap.loc[idx])
                detail = (
                    f"locked {_format_money(exp_col.loc[idx])}, "
                    f"produced {_format_money(act_col.loc[idx])} "
                    f"(off by {_format_money(this_gap)})"
                )
            else:
                # Only present-on-one-side differences exist in this column.
                idx = moved[moved].index[0]
                this_gap = float("inf")
                detail = (
                    f"locked {_format_money(exp_col.loc[idx])}, "
                    f"produced {_format_money(act_col.loc[idx])} "
                    "(value present on only one side)"
                )
            differences.append(
                f"  Column '{column}': {count} value(s) changed. "
                f"Biggest is row {idx + 1}: {detail}."
            )
            if this_gap > worst_gap:
                worst_gap = this_gap
                worst_line = f"row {idx + 1}, column '{column}'"
                if this_gap != float("inf"):
                    worst_line += f" (off by {_format_money(this_gap)})"
        else:
            # Text/date columns: compare exactly. A sentinel stands in for
            # missing values so "present vs absent" is caught while
            # "absent vs absent" counts as equal.
            exp_str = exp_col.where(exp_col.notna(), "<missing>").astype(str)
            act_str = act_col.where(act_col.notna(), "<missing>").astype(str)
            moved = exp_str != act_str
            if not moved.any():
                continue
            count = int(moved.sum())
            idx = moved[moved].index[0]
            differences.append(
                f"  Column '{column}': {count} text value(s) changed. "
                f"First at row {idx + 1}: locked '{exp_str.loc[idx]}', "
                f"produced '{act_str.loc[idx]}'."
            )

    # 4) If anything moved, raise one consolidated, readable report.
    if differences:
        headline = (
            f"{name}: {len(differences)} column(s) drifted from the locked numbers"
        )
        if worst_line:
            headline += f". Worst change: {worst_line}"
        raise AssertionError(headline + ".\n" + "\n".join(differences))


@pytest.mark.parametrize("scope, rel_name", PROPERTY_CSV_CASES)
def test_property_csv_locked(generated_out: Path, scope: str, rel_name: str) -> None:
    """Each per-property CSV matches its committed fixture to 2dp.

    Phase 8 / S3: the produced CSV lives under the property's csv/ sub-folder
    (CSV_SUBDIR), while the committed fixture stays at its existing
    <scope>/<name> location. The values are byte-identical, so the asymmetry is
    intentional and the assertion still passes.

    Phase 11 / S1: parametrised over every locked (scope, file) pair, so Property
    B is pinned alongside Property A. Property B omits the tax sheets (tax off).

    Phase 11 / S2: Property C is pinned too, but as a valuation-only property its
    only locked file is `valuation_schedule.csv` (no baseline, loan, reconcile,
    or tax files exist for it).
    """
    _assert_csv_matches(
        # Produced side: one level deeper, under the property's csv/ folder.
        generated_out / scope / CSV_SUBDIR / rel_name,
        # Expected side: committed fixture, unchanged location and values.
        GOLDEN_DIR / scope / rel_name,
    )


@pytest.mark.parametrize("rel_name", ROOT_CSV_FILES)
def test_root_csv_locked(generated_out: Path, rel_name: str) -> None:
    """The portfolio-level CSV matches its fixture to 2dp.

    Phase 8 / S3: the produced rollup lives under the top-level csv/ sub-folder;
    the committed fixture stays at the golden root.

    Phase 11 / S1: the rollup now aggregates Property A and Property B, so this
    fixture was re-baselined when B was enabled.

    Phase 11 / S2: the rollup now also carries Property C. C reports in PKR, and
    under the interim currency guard its euro `property_value` cell is blank, so
    the euro figures are unchanged and only the extra C row is new. The fixture
    is re-baselined for the three-row rollup.
    """
    _assert_csv_matches(
        # Produced side: under the top-level csv/ folder.
        generated_out / CSV_SUBDIR / rel_name,
        # Expected side: committed fixture at the golden root.
        GOLDEN_DIR / rel_name,
    )


@pytest.mark.parametrize("scope", sorted(BASELINE_INPUTS_SCOPES))
def test_effective_inputs_yaml_byte_equal(generated_out: Path, scope: str) -> None:
    """The baseline effective-inputs snapshot is locked byte-for-byte, per scope.

    This file is a YAML re-dump of the resolved inputs, not computed numbers,
    so it must reproduce exactly. Newlines are normalised so a CRLF/LF flip
    between machines does not cause a false failure.

    Phase 11 / S1: parametrised per scope so Property B's resolved inputs are
    locked alongside Property A's.

    Phase 11 / S2: only the mortgage scopes are checked. A valuation-only
    property never runs the baseline tool, so it produces no effective-inputs
    snapshot; property-c is excluded via BASELINE_INPUTS_SCOPES.
    """
    actual_path = generated_out / scope / YAML_FILE
    expected_path = GOLDEN_DIR / scope / YAML_FILE
    assert expected_path.exists(), f"Missing golden fixture: {expected_path}"
    assert actual_path.exists(), f"Pipeline did not produce: {actual_path}"
    # Universal-newline normalisation keeps the compare content-exact.
    actual_text = actual_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    expected_text = expected_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if actual_text != expected_text:
        # Point at the first differing line so the message is actionable.
        expected_lines = expected_text.splitlines()
        actual_lines = actual_text.splitlines()
        location = "the end of the file"
        for line_no, (exp_line, act_line) in enumerate(
            zip(expected_lines, actual_lines), start=1
        ):
            if exp_line != act_line:
                location = (
                    f"line {line_no}:\n"
                    f"  locked:   {exp_line}\n"
                    f"  produced: {act_line}"
                )
                break
        else:
            # No mismatch within the shared lines, so the lengths differ.
            location = (
                f"a length change ({len(expected_lines)} locked lines vs "
                f"{len(actual_lines)} produced)"
            )
        raise AssertionError(
            f"{YAML_FILE} ({scope}): the resolved-inputs snapshot changed from "
            f"the locked version. First difference at {location}"
        )