"""Golden-master regression test for the mortflow cashflow engine.

This test pins the engine's current numeric behaviour. It regenerates every
locked output from the bundled ``data_sample/`` data into a throwaway temp
directory, then asserts each file matches a committed fixture to two decimal
places (CSV) or byte-for-byte (the effective-inputs YAML).

The point is refactor-safety: Phase 5 may restructure ``src/engine.py`` freely,
and this test fails loudly the moment any number moves beyond half a cent.

Fixtures live in ``tests/fixtures/golden/`` and were captured from a run Ali
verified against the bank on real Property A data, then locked from the
de-identified sample that reproduces the same figures.

Phase 8 / S3 note: the engine now writes every CSV into a ``csv/`` sub-folder
(per-property ``<slug>/csv/`` and a top-level ``csv/`` for the rollup), so the
produced files this test reads live one level deeper than before. The committed
fixtures are intentionally left at their existing locations: a fixture is just
the locked expected value, and its on-disk path is independent of the runtime
output layout. Because the CSV contents are byte-identical (S3 moved paths only,
not numbers), the suite stays green without re-capturing anything. Any fixture
re-baseline is deferred to S5. The effective-inputs YAML stays at the property
root and its test is unchanged.
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

    The repo root is the first ancestor that contains both the ``tools``
    package and the ``data_sample`` directory, so the test resolves correctly
    no matter how deep under the repo the file is placed (a stray
    ``tests/tests/`` nesting, for example, still works).
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

# Per-property CSVs to lock, relative to the property output sub-folder.
# Only Property A is enabled in the sample portfolio, so it is the only scope.
PROPERTY_SCOPE = "property-a"
# Phase 8 / S3: the engine now writes every CSV into this sub-folder, both under
# each property folder and at the output root for the rollup. The produced files
# therefore sit at <scope>/csv/<name>; the committed fixtures stay at their
# existing <scope>/<name> locations (their layout is independent of the runtime
# output layout, and the values are byte-identical, so the suite stays green
# without re-capturing them). S5 owns any fixture re-baseline.
CSV_SUBDIR = "csv"
PROPERTY_CSV_FILES = [
    "baseline_monthly.csv",
    "baseline_reconcile.csv",
    "baseline_events_daily.csv",
    "schedule_monthly.csv",
    "reconcile.csv",
    "events_daily.csv",
    "tax_year.csv",
    "tax_audit.csv",
]
# Portfolio-level CSV written at the output root.
ROOT_CSV_FILES = ["portfolio_summary.csv"]
# Effective-inputs snapshot is locked byte-for-byte, not at 2dp.
YAML_FILE = "baseline.effective.inputs.yaml"

# Half a cent: two monetary values that agree to 2dp never differ by more.
MONEY_ATOL = 0.005


def _run_pipeline(out_dir: Path) -> None:
    """Regenerate every sample output into ``out_dir`` via the real CLIs.

    Mirrors ``run_sample.bat`` exactly: baseline first, then portfolio, both
    pointed at the bundled ``data_sample`` portfolio and the temp out dir.
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
    the gap in euros. The first line is a one-sentence summary, so it also reads
    well in pytest's short summary panel.
    """
    # A missing file on either side is a setup problem, not a silent pass.
    assert expected_path.exists(), (
        f"{expected_path.name}: no locked fixture found at {expected_path}. "
        "Re-capture the fixtures (Step 5) before running the test."
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
        # Treat a column as numeric only when both sides are a numeric dtype
        # AND neither side is boolean. Pandas reports true/false columns as
        # numeric, but subtracting them raises a TypeError, so booleans are
        # routed to the exact-match branch below instead.
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


@pytest.mark.parametrize("rel_name", PROPERTY_CSV_FILES)
def test_property_csv_locked(generated_out: Path, rel_name: str) -> None:
    """Each per-property CSV matches its committed fixture to 2dp.

    Phase 8 / S3: the produced CSV now lives under the property's csv/ sub-folder
    (CSV_SUBDIR), while the committed fixture stays at its existing
    <scope>/<name> location. The values are byte-identical, so this asymmetry is
    intentional and the assertion still passes.
    """
    _assert_csv_matches(
        # Produced side: now one level deeper, under the property's csv/ folder.
        generated_out / PROPERTY_SCOPE / CSV_SUBDIR / rel_name,
        # Expected side: committed fixture, unchanged location and values.
        GOLDEN_DIR / PROPERTY_SCOPE / rel_name,
    )


@pytest.mark.parametrize("rel_name", ROOT_CSV_FILES)
def test_root_csv_locked(generated_out: Path, rel_name: str) -> None:
    """The portfolio-level CSV matches its fixture to 2dp.

    out_dir is locked as the relative slug "property-a" (see the relative
    out_dir change in tools/portfolio.py), so this assertion is machine
    independent.

    Phase 8 / S3: the produced rollup now lives under the top-level csv/
    sub-folder; the committed fixture stays at the golden root.
    """
    _assert_csv_matches(
        # Produced side: now under the top-level csv/ folder.
        generated_out / CSV_SUBDIR / rel_name,
        # Expected side: committed fixture at the golden root, unchanged.
        GOLDEN_DIR / rel_name,
    )


def test_effective_inputs_yaml_byte_equal(generated_out: Path) -> None:
    """The baseline effective-inputs snapshot is locked byte-for-byte.

    This file is a YAML re-dump of the resolved inputs, not computed numbers,
    so it must reproduce exactly. Newlines are normalised so a CRLF/LF flip
    between machines does not cause a false failure.

    Phase 8 / S3: the YAML snapshot stays at the property root (it is not a CSV),
    so both the produced path and the fixture path are unchanged here.
    """
    actual_path = generated_out / PROPERTY_SCOPE / YAML_FILE
    expected_path = GOLDEN_DIR / PROPERTY_SCOPE / YAML_FILE
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
            f"{YAML_FILE}: the resolved-inputs snapshot changed from the locked "
            f"version. First difference at {location}"
        )