# PRODUCT_BACKLOG.md — Possible Future Work

> The **single authoritative home** for possible future work outside the active
> delivery pipeline: deferred features, ideas, enhancements, technical debt,
> investigations and improvements not currently authorised for delivery.
>
> **Recording an item here does not authorise its implementation.** Do not
> implement a backlog item unless it is explicitly **PROMOTED** into
> `PRODUCT_DELIVERY_PLAN.md`.

**Last updated:** 2026-09-26 (phase audit findings REVIEW-000..016 added and groomed)

---

## Status vocabulary

`CANDIDATE` · `DEFERRED` · `BLOCKED` · `READY` · `PROMOTED` · `REJECTED`

---

## Feature candidates (from Notion Master Handoff)

### BACKLOG-101: Rental scenario layer

Status: CANDIDATE
Captured: 2026-09-26 (migrated from Notion)
Source: Notion Master Handoff backlog

#### Context
Gandon is an investment property with rental income. This layer adds rental
income, vacancy, and cashflow to the scenario engine.

#### Reason not now
Phase 13 covers the mortgage layer only; rental is a separate layer.

#### Likely outcome
Scenario analysis that includes rental income and vacancy.

#### Build notes
To be discovered.

#### Promotion trigger
After Phase 13 ships and the mortgage-layer scenario engine is stable.

#### Related records
`PRODUCT_VISION.md` (layered extensions); Phase 13 work package.

---

### BACKLOG-102: Tax scenario layer

Status: CANDIDATE
Captured: 2026-09-26 (migrated from Notion)
Source: Notion Master Handoff backlog

#### Context
Adds the true after-tax impact to mortgage and rental scenarios.

#### Reason not now
Depends on the rental layer and the mortgage-layer scenario engine.

#### Likely outcome
After-tax scenario comparison.

#### Build notes
To be discovered.

#### Promotion trigger
After the rental scenario layer.

#### Related records
`src/tax.py`; Phase 13 work package.

---

### BACKLOG-103: Investment decision layer

Status: CANDIDATE
Captured: 2026-09-26 (migrated from Notion)
Source: Notion Master Handoff backlog

#### Context
Top-level decision layer composing mortgage, rental, and tax results into a
capital allocation comparison (e.g. overpay the mortgage, contribute to a
pension, or invest elsewhere), including the pension relief gross-up effect.

#### Reason not now
Composes the rental and tax layers, which do not exist yet.

#### Likely outcome
A capital allocation comparison across options.

#### Build notes
To be discovered.

#### Promotion trigger
After the rental and tax scenario layers.

#### Related records
`PRODUCT_VISION.md`; BACKLOG-101; BACKLOG-102.

---

### BACKLOG-104: Expenses + cashflow

Status: CANDIDATE
Captured: 2026-09-26 (migrated from Notion)
Source: Notion Master Handoff backlog

#### Context
Track all costs from each property, not just the mortgage cost. Recurring and
one-off expenses (new schema fields: category, amount, frequency, date range).
A precursor to richer scenario analysis.

#### Reason not now
Outside the Phase 13 mortgage-layer scope.

#### Likely outcome
Full property cashflow including non-mortgage costs.

#### Build notes
New schema fields: `category`, `amount`, `frequency`, `date range`.

#### Promotion trigger
When scenario analysis needs whole-property cashflow.

#### Related records
`docs/contract_data_model.md`.

---

### BACKLOG-105: Form 11 detailed workings

Status: CANDIDATE
Captured: 2026-09-26 (migrated from Notion)
Source: Notion Master Handoff backlog

#### Context
More detailed Form 11 workings beyond the current `TaxYear` / `TaxAudit` sheets.

#### Reason not now
Outside the Phase 13 scope.

#### Likely outcome
Deeper tax audit trail.

#### Build notes
To be discovered.

#### Promotion trigger
When the tax scenario layer is scoped.

#### Related records
`src/tax.py`; BACKLOG-102.

---

### BACKLOG-106: Valuation models

Status: CANDIDATE
Captured: 2026-09-26 (migrated from Notion)
Source: Notion Master Handoff backlog

#### Context
Richer property valuation models beyond the current growth / revaluation blocks.

#### Reason not now
Outside the Phase 13 scope.

#### Likely outcome
More realistic property value projections.

#### Build notes
To be discovered.

#### Promotion trigger
When valuation accuracy becomes a decision input.

#### Related records
`src/engine/valuation.py`; `src/engine/valuation_only.py`.

---

### BACKLOG-107: Scheduled runs

Status: CANDIDATE
Captured: 2026-09-26 (migrated from Notion)
Source: Notion Master Handoff backlog

#### Context
Automated / scheduled model runs.

#### Reason not now
Outside the Phase 13 scope.

#### Likely outcome
Regular automatic refreshes of outputs.

#### Build notes
To be discovered.

#### Promotion trigger
When manual runs become a burden.

#### Related records
`run.bat`; `run_sample.bat`.

---

### BACKLOG-108: UI exploration

Status: CANDIDATE
Captured: 2026-09-26 (migrated from Notion)
Source: Notion Master Handoff backlog

#### Context
Explore a user interface for the model.

#### Reason not now
Outside the Phase 13 scope; the product is currently CLI + Excel.

#### Likely outcome
A friendlier interface for non-technical use.

#### Build notes
To be discovered.

#### Promotion trigger
When release packages need a GUI.

#### Related records
`PRODUCT_VISION.md` (intended users).

---

### BACKLOG-109: Layered metrics refactor

Status: CANDIDATE
Captured: 2026-09-26 (migrated from Notion)
Source: Notion Master Handoff backlog

#### Context
Just as `engine.py` was broken into smaller files in Phase 5, `metrics.py` will
become unmanageable as rental and tax layers are added. Proposed split:
`base_metrics.py` (core mortgage KPIs), `rental_metrics.py` (cashflow, yield,
vacancy), `tax_metrics.py` (deductibility, net-of-tax saving, Form 11 impact),
`scenario_metrics.py` (interest saved, term reduction, opportunity cost).

#### Reason not now
Timing: do this at the start of the first phase that adds a new layer (rental or
tax), not as a standalone phase.

#### Likely outcome
Each metrics module independently importable and testable. No behaviour change;
re-baseline required.

#### Build notes
All tests that import from `metrics.py` need updating; impacts `src/`, `tests/`,
and `tools/` that read metrics outputs.

#### Promotion trigger
When the rental or tax scenario layer is scoped.

#### Related records
`src/metrics.py`; BACKLOG-101; BACKLOG-102.

---

### BACKLOG-111: CI pipeline

Status: DEFERRED
Captured: 2026-09-26 (migrated from Notion)
Source: Notion Master Handoff backlog

#### Context
Automatic `pytest -q` runs on GitHub on every push and PR. Dropped from the
active roadmap 2026-07-16: as a disciplined solo dev who runs the suite before
every push, the marginal value is low.

#### Reason not now
Low marginal value for a solo developer; revisit if contributors join or a PR
gate is wanted.

#### Likely outcome
A clean-room cross-platform check (fresh Linux runner building from
`requirements.txt`).

#### Build notes
GitHub Actions workflow (`.github/workflows/ci.yml`) running `pytest -q` on
Ubuntu + Python 3.14; optional OS/Python matrix, pip cache, README status badge,
required-check branch protection. Watch for CRLF vs LF on the golden CSV fixtures
(pin to `lf` via `.gitattributes`) and Python 3.14 wheel availability on Linux.

#### Promotion trigger
Contributors join, or a PR gate is wanted.

#### Related records
`requirements.txt`; `tests/fixtures/golden/`.

---

### BACKLOG-112: PRTB integration

Status: CANDIDATE
Captured: 2026-09-26 (migrated from Notion)
Source: Notion Master Handoff backlog

#### Context
Integrate PRTB (Residential Tenancies Board) registration data or compliance
checks into the tenancy output.

#### Reason not now
Scope and feasibility TBD; no clear public API or data source identified yet.

#### Likely outcome
Tenancy data cross-checked against the register.

#### Build notes
To be discovered.

#### Promotion trigger
A viable public data source is identified.

#### Related records
`src/tax.py`; Phase 15 (RPZ).

---

### BACKLOG-113: Phase 13 scoping spec (requirements source)

Status: PROMOTED
Captured: 2026-09-26 (migrated from Notion)
Source: Notion Master Handoff backlog

#### Context
Full requirements and design context for Phase 13 (scenario engine):
contract-aware perturbations, execution modes, always-generated scenarios,
mortgage offer comparison, and the modular architecture for rental and tax
layers to plug into.

#### Reason not now
-
#### Likely outcome
Captured in `FEATURE_P13_scenario_engine.md`.

#### Build notes
Promoted into Phase 13.

#### Promotion trigger
-
#### Related records
`FEATURE_P13_scenario_engine.md`.

---

### BACKLOG-114: Phase 10 scoping spec (requirements source)

Status: PROMOTED
Captured: 2026-09-26 (migrated from Notion)
Source: Notion Master Handoff backlog

#### Context
Full requirements and design context for Phase 10 (contract schema redesign):
the contracts array structure, Inputs formalisation, and the bank-semantics
decisions locked before S1.

#### Reason not now
-
#### Likely outcome
Delivered in Phase 10 (`v2.0.0`).

#### Build notes
Promoted into Phase 10; shipped.

#### Promotion trigger
-
#### Related records
`docs/contract_data_model.md`; `docs/lender_profile.md`.

---

### BACKLOG-115: Phase 11 scoping spec (requirements source)

Status: PROMOTED
Captured: 2026-09-26 (migrated from Notion)
Source: Notion Master Handoff backlog

#### Context
Full requirements and context for Phase 11 (activation of all properties):
real-data requirements for B and C, the portfolio manifest refactor, and the
definition of "presentation-ready" per property kind.

#### Reason not now
-
#### Likely outcome
Delivered in Phase 11 (`v2.1.0`).

#### Build notes
Promoted into Phase 11; shipped.

#### Promotion trigger
-
#### Related records
`tools/portfolio.py`; `data_sample/portfolio.yaml`.

---

### BACKLOG-110: Mortgage offer comparison (requirements)

Status: PROMOTED
Captured: 2026-09-26 (migrated from Notion)
Source: Notion Master Handoff backlog

#### Context
When a bank gives a refinancing offer or a new fixed rate, compare it against
the current deal including breakage fees.

#### Reason not now
—
#### Likely outcome
Offer comparison with breakage.

#### Build notes
Promoted into Phase 13 / S5.

#### Promotion trigger
—
#### Related records
`FEATURE_P13_scenario_engine.md` (S5).

---

## Technical debt and defects (from 2026-09-26 repo review)

### BACKLOG-001: Fix time-dependent golden master

Status: PROMOTED
Captured: 2026-09-26
Source: repo review

#### Context
`tools/portfolio.py::_valuation_summary_row` used `date.today()` for
`as_of_date` and grew Property C's value to today, so
`tests/fixtures/golden/portfolio_summary.csv` drifted daily. The suite reported
**1 failed, 170 passed, 4 skipped**.

#### Reason not now
-
#### Likely outcome
A deterministic golden master that passes on any date.

#### Build notes
**Done 2026-09-26** on branch `fix/golden-master-determinism`. Added
`_derive_valuation_as_of` (config-driven: `valuation.as_of_date`, else
`modelling.end_date`); `_valuation_summary_row` takes the date as a parameter.
The sample pins `as_of_date: 2026-07-17`, so the golden value is unchanged and
**no fixture was re-baselined**. Two regression tests added. Suite: 173 passed /
4 skipped / 0 failed.

#### Promotion trigger
-
#### Related records
`AGENT_STATUS.md` (known defects); `DECISIONS_AND_LEARNINGS.md` (L1).

---

### BACKLOG-002: Remove or fill empty test file

Status: PROMOTED
Captured: 2026-09-26
Source: repo review

#### Context
`tests/test_overpayment_cap_headroom.py` was tracked and 0 bytes. The Phase 12
S2 notes claimed it locked the flag boundaries, headroom maths, the 90%
approaching boundary, a synthetic breach, the null passthrough, and the
cumulative total, but none of those tests existed. `overpayment_cap_flag()` was
not called by any test.

#### Reason not now
-
#### Likely outcome
Real coverage of the cap flag and headroom logic.

#### Build notes
**Done 2026-09-26** (BACKLOG-002): 18 tests authored covering the null
allowance, the ok / approaching / breached boundaries (including the subtle
`used == allowance` case, which is approaching not breached), the non-positive
allowance rule, the real Gandon allowance boundaries, and the three emitted
monthly columns (headroom, flag, cumulative).

#### Promotion trigger
-
#### Related records
`src/engine/monthly.py` (`overpayment_cap_flag`); `DECISIONS_AND_LEARNINGS.md` (L2).

---

### BACKLOG-003: Explicit UTF-8 encodings on text reads

Status: PROMOTED
Captured: 2026-09-26
Source: repo review

#### Context
Several `Path.read_text()` calls omitted `encoding="utf-8"` (schema, tax,
profile, portfolio, baseline, `__main__`, `valuation_only`), so Windows used the
locale code page.

#### Reason not now
-
#### Likely outcome
Portable, locale-independent file reads.

#### Build notes
**Done 2026-09-26** (BACKLOG-003): explicit `encoding="utf-8"` added to every
remaining read and write in `src/` and `tools/`.

#### Promotion trigger
-
#### Related records
`DECISIONS_AND_LEARNINGS.md` (L5).

---

### BACKLOG-004: De-duplicate kind sets, slugify and tax date helpers

Status: PROMOTED
Captured: 2026-09-26
Source: repo review

#### Context
`_VALUATION_ONLY_KINDS` was defined in `tests/conftest.py`, `tools/baseline.py`
and `tools/portfolio.py`; `_slugify` duplicated `helpers.slugify`; `src/tax.py`
re-implemented `_eom`.

#### Reason not now
-
#### Likely outcome
One canonical definition of each, imported everywhere.

#### Build notes
**Done 2026-09-26** (BACKLOG-004): the kind set now lives once as
`schema.VALUATION_ONLY_KINDS`; `baseline._slug` and `conftest._slugify` delegate
to `helpers.slugify`; `tax._eom` is imported from `helpers`. `tax._ensure_date`
was deliberately left local: it is lenient (pandas parsing) where the engine's is
strict, so swapping it would change behaviour.

#### Promotion trigger
-
#### Related records
`DECISIONS_AND_LEARNINGS.md` (L3).

---

### BACKLOG-005: Replace `assert` validation with `ValueError`

Status: PROMOTED
Captured: 2026-09-26
Source: repo review

#### Context
`tools/portfolio.py` validated `portfolio.yaml` with `assert`, which is stripped
under `python -O`.

#### Reason not now
-
#### Likely outcome
Validation that survives optimisation.

#### Build notes
**Done 2026-09-26** (BACKLOG-005): `load_portfolio` now raises `ValueError` with
an actionable message; also reads with explicit UTF-8. Three tests added.

#### Promotion trigger
-
#### Related records
`DECISIONS_AND_LEARNINGS.md` (L4).

---

### BACKLOG-006: Add `pyproject.toml`; move pytest to dev requirements

Status: PROMOTED
Captured: 2026-09-26
Source: repo review

#### Context
No `pyproject.toml`; `pytest` was listed in runtime `requirements.txt` though it
is a dev tool.

#### Reason not now
-
#### Likely outcome
Standard project metadata and a clean runtime/dev split.

#### Build notes
**Done 2026-09-26** (BACKLOG-006): `pyproject.toml` added (metadata, Python
floor, pytest config, optional dev extras); `pytest` moved to
`requirements-dev.txt`.

#### Promotion trigger
-
#### Related records
`requirements.txt`; `requirements-dev.txt`.

---

### BACKLOG-007: Refresh README version history and test count

Status: PROMOTED
Captured: 2026-09-26
Source: repo review

#### Context
README version history stopped at v2.1.0 (v2.2.0 missing); the stated test count
(168) was stale.

#### Reason not now
-
#### Likely outcome
Accurate README.

#### Build notes
**Done 2026-09-26** (BACKLOG-007): added the v2.2.0 row (overpayment cap) and
corrected the test count to 194 passed / 4 skipped.

#### Promotion trigger
-
#### Related records
`README.md`; BACKLOG-001.

---

### BACKLOG-008: Sanitise property nicknames from tracked files

Status: REJECTED
Captured: 2026-09-26
Source: privacy scan

#### Context
The real property nicknames (Gandon / Somerton / Paragon) appear in tracked code
comments, tests and docs. They are labels, not addresses, and have been public
since Phase 3.

#### Reason not now
Owner confirmed 2026-09-26 that the nicknames are acceptable in tracked files.
They are readable labels, not personal data, and aid the golden-master and cap
tests.

#### Likely outcome
No change. Nicknames retained.

#### Build notes
Not required.

#### Promotion trigger
None. Revisit only if the repo is shared more widely and the owner changes
position.

#### Related records
`DECISIONS_AND_LEARNINGS.md` (D11); Operating Contract section 10.

---

## Code hygiene (from the 2026-09-26 deep scan)

### NEW-1: Remove import-time "ready" prints

Status: PROMOTED
Captured: 2026-09-26
Source: deep scan

#### Context
Eleven engine modules printed a "ready" line to stderr the moment they were
imported, before any work was requested. Debugging leftovers.

#### Reason not now
-
#### Likely outcome
Silent imports.

#### Build notes
**Done 2026-09-26** (NEW-1): all eleven import-time prints removed; seven
now-unused `import sys` lines dropped. `import src.engine` is now silent.

#### Promotion trigger
-
#### Related records
`AGENT_STATUS.md` (known defects).

---

### NEW-2: Narrow broad `except Exception` blocks

Status: READY
Captured: 2026-09-26
Source: deep scan

#### Context
Twelve places catch any exception. Two swallow the error silently with `pass`:
`src/engine/__main__.py:249` and `tools/portfolio.py:314`. Catching everything
can hide a real bug and let a run continue with a wrong or missing result.

**Groomed 2026-09-26:** the phase audit found two more silent sites in the same
family, `tools/portfolio.py::_derive_as_of` and `_derive_valuation_as_of`, which
swallow any exception while reading the inputs YAML and fall back to `{}` (a
malformed file yields a blank as-of date with no warning). These are folded into
this item; REVIEW-015 is closed as a duplicate.

#### Reason not now
Not Phase 13 scope; the paths are not currently triggering.

#### Likely outcome
Specific exceptions caught, and a warning logged rather than passing silently.

#### Build notes
Narrow the caught types where possible; log a warning instead of `pass`. Review
each site individually: some are deliberate graceful degradation.

#### Promotion trigger
When those error paths are next touched.

#### Related records
`DECISIONS_AND_LEARNINGS.md`; skill error-handling guidance.

---

### NEW-3: Add `.gitattributes`

Status: PROMOTED
Captured: 2026-09-26
Source: deep scan

#### Context
No `.gitattributes`, so line endings could flip between CRLF and LF. The golden
master compares committed CSV fixtures, so a line-ending change would fail the
comparison for a reason unrelated to the numbers.

#### Reason not now
-
#### Likely outcome
Stable line endings across machines.

#### Build notes
**Done 2026-09-26** (NEW-3): `.gitattributes` added, pinning golden fixtures to
LF and `.bat` files to CRLF.

#### Promotion trigger
-
#### Related records
`tests/fixtures/golden/`; BACKLOG-111 (CI pipeline).

---

### NEW-4: Align `run_sample.bat` with `run.bat`

Status: PROMOTED
Captured: 2026-09-26
Source: deep scan

#### Context
`run.bat` used the `tools/_resolve.py` shim; `run_sample.bat` used an inline
`python -c "..."` command, the fragile form that previously caused cmd.exe
quoting problems.

#### Reason not now
-
#### Likely outcome
Both launchers use the same robust technique.

#### Build notes
**Done 2026-09-26** (NEW-4): `run_sample.bat` now calls `tools/_resolve.py`.

#### Promotion trigger
-
#### Related records
`run.bat`; `tools/_resolve.py`.

---

### NEW-5: Wrap lines over 120 characters

Status: PROMOTED
Captured: 2026-09-26
Source: deep scan

#### Context
Five lines in `src/` exceeded 120 characters.

#### Reason not now
-
#### Likely outcome
Consistent line length.

#### Build notes
**Done 2026-09-26** (NEW-5): all five wrapped.

#### Promotion trigger
-
#### Related records
PEP 8.

---

## Phase audit findings (2026-09-26)

> A detailed, evidence-based review of every completed phase (0-12) against its
> claimed deliverable, its outputs, and its robustness. Phase 13 is active and
> was **not** reviewed. Two trivial defects were fixed inline on branch
> `review/phase-audit-2026-09-26` (see REVIEW-000); the rest are logged here and
> are **not** authorised for implementation.

### Grooming summary (2026-09-26)

All 17 items were reviewed for duplication and status consistency. One duplicate
was folded into an existing item; the rest are distinct.

| Item | Severity | Status | Note |
| --- | --- | --- | --- |
| REVIEW-000 | fixed | PROMOTED | 3 trivial defects fixed inline on the audit branch |
| REVIEW-001 | medium | CANDIDATE | contract date gaps |
| REVIEW-002 | low | CANDIDATE | mid-month refix |
| REVIEW-003 | low | CANDIDATE | empty `contracts: []` |
| REVIEW-004 | medium | CANDIDATE | missing lender profile |
| REVIEW-005 | low | CANDIDATE | bad `repayment_day` |
| REVIEW-006 | medium | CANDIDATE | synthetic Somerton test figures |
| REVIEW-007 | medium | CANDIDATE | cap blank for most of term |
| REVIEW-008 | **high** | CANDIDATE | cap flag blind to unagreed overpayment |
| REVIEW-009 | low | CANDIDATE | payoff-month attribution |
| REVIEW-010 | **high** | CANDIDATE | Summary numbers not golden-locked |
| REVIEW-011 | low | CANDIDATE | per-currency totals not locked |
| REVIEW-012 | low | CANDIDATE | `csv_subdir` path escape |
| REVIEW-013 | low | CANDIDATE | silent bad boolean string |
| REVIEW-014 | low | CANDIDATE | missing `actuals` reroutes |
| REVIEW-015 | - | REJECTED | duplicate of NEW-2; folded in |
| REVIEW-016 | low | CANDIDATE | valuation anchor fallback |

**Suggested first fix pass (not authorised):** REVIEW-008 and REVIEW-010, then
REVIEW-001 and REVIEW-004.

### REVIEW-000: Defects fixed inline during the audit

Status: PROMOTED
Captured: 2026-09-26
Source: phase audit

#### Context
Two trivial, low-risk defects were found and fixed on the audit branch, each
verified against the full suite (194 passed / 4 skipped / 0 failed) and with no
golden fixture re-baselined.

#### Build notes
**Done 2026-09-26** on `review/phase-audit-2026-09-26`:
1. **Quoted string booleans read as truthy** (`src/engine/schema.py`). A quoted
   `tax: "false"` in the `meta` block produced `tax_enabled=True`, because
   `bool("false")` is `True`; the same pattern affected the payment-holiday
   `capitalise` flag. Added a shared `_as_bool` helper and used it in
   `_resolve_meta` and `_resolve_payment_holidays`. No sample uses quoted
   booleans, so the golden is unaffected.
2. **Non-deterministic workbook table names** (`src/engine/report.py`).
   `_add_table` built the Excel table name from `abs(hash((ws.title, ref)))`;
   Python's `hash()` is salted per process, so the `.xlsx` bytes differed
   between runs. Replaced with `zlib.crc32`, which is stable across processes.
   This directly contradicted the product's determinism guarantee.
3. **Test-file encodings** (`tests/`). Nine `read_text()` / `write_text()` calls
   in seven test files omitted `encoding="utf-8"`, the same locale-dependent
   defect BACKLOG-003 fixed in `src/` and `tools/` but missed in `tests/`.

#### Promotion trigger
-
#### Related records
`src/engine/schema.py`; `src/engine/report.py`; BACKLOG-003.

---

### REVIEW-001: Contract date-gap months silently use the last contract's rate

Status: PROMOTED
Captured: 2026-09-26
Source: phase audit (Phase 10)

#### Context
`rate_lookup_for` / `_contract_month_ranges` build a rate window per contract
and fall through to `contracts[-1].rate` for any model month not covered by a
window. A gap between two contracts (for example A1 ends Feb 2028, A2 starts
May 2028) therefore applies the **final** contract's rate to the gap months.
Verified at runtime: a gap month returned A3's rate (0.04), not A1's or A2's.
There is no contiguity validation on the contracts array.

#### Reason not now
-
#### Likely outcome
A gap or overlap is a clear config error rather than a silent mis-price.

#### Build notes
**Done 2026-09-26** on branch `fix/review-medium`. Added
`_validate_contract_contiguity` in `schema.py`, called from `_resolve_contracts`:
each contract must start the day after the previous one ends, and only the final
contract may be open-ended. A gap, an overlap, or an early open-ended contract
raises `ValueError` with the offending ids and dates. The bundled samples are
contiguous, so **no golden fixture was re-baselined**. Four tests added.

#### Promotion trigger
-
#### Related records
`src/engine/monthly.py`; `src/engine/schema.py`; `tests/test_contracts_repoint.py`.

---

### REVIEW-002: Mid-month refix double-claims a model month

Status: CANDIDATE
Captured: 2026-09-26
Source: phase audit (Phase 10)

#### Context
`month_index` is month-granular, so a contract starting mid-month and the prior
contract ending mid-month both map to the same model month. `rate_lookup_for`
returns the first matching window, so the new rate is delayed by up to a month.
The samples use month boundaries, so they are unaffected.

#### Reason not now
No live impact on the bundled data.

#### Likely outcome
A documented, tested rule for which contract owns a shared month (for example
the later contract wins), or a warning when a boundary is mid-month.

#### Build notes
Decide the tie-break, encode it in `_contract_month_ranges`, and add a test with
a mid-month refix.

#### Promotion trigger
When a real refix lands mid-month.

#### Related records
`src/engine/monthly.py`; `src/engine/helpers.py` (`month_index`).

---

### REVIEW-003: `contracts: []` is treated as a legacy file

Status: PROMOTED
Captured: 2026-09-26
Source: phase audit (Phase 10)

#### Context
`_resolve_loan_v2` returns `None` when the `contracts` array is empty, so a file
that declares `contracts: []` silently falls back to the legacy `rate_blocks`
keys rather than erroring. A user who empties the array by mistake gets the old
model with no warning.

#### Reason not now
-
#### Likely outcome
An empty `contracts:` array is a config error when the mortgage module is on.

#### Build notes
**Done 2026-09-26** on branch `fix/review-low`. `_resolve_loan_v2` now
distinguishes "no `contracts:` key" (legacy, still loads) from "`contracts:`
present but empty" (raises `ValueError`). Two tests added. Output-neutral.

#### Promotion trigger
-
#### Related records
`src/engine/schema.py`; `tests/test_contracts_repoint.py`.

---

### REVIEW-004: A missing lender profile silently disables cap, breakage, and convention

Status: PROMOTED
Captured: 2026-09-26
Source: phase audit (Phase 10 / Phase 12)

#### Context
`load_inputs` catches `FileNotFoundError` from `resolve_lender_profile` and sets
`profile=None`. That silently disables the overpayment cap, the breakage
reference, and the Modified Following payment-date convention. Since Phase 12
the cap is an emitted output figure, so a missing profile now blanks a reported
number rather than only a reference.

#### Reason not now
-
#### Likely outcome
A missing profile for a declared `lender` key warns rather than silently
degrading the run.

#### Build notes
**Done 2026-09-26** on branch `fix/review-medium`. `load_inputs` now prints an
actionable warning to stderr naming the lender key and the search directory when
no profile resolves, while still loading (not fatal). No output figure changes,
so **no golden fixture was re-baselined**. One test added.

#### Promotion trigger
-
#### Related records
`src/engine/schema.py`; `src/engine/profile.py`; REVIEW-008.

---

### REVIEW-005: `_repayment_day_to_int` returns 1 on a bad value

Status: PROMOTED
Captured: 2026-09-26
Source: phase audit (Phase 10)

#### Context
`_repayment_day_to_int` returns `1` when the `repayment_day` value cannot be
parsed, silently moving projected payment dates to the 1st instead of raising.

#### Reason not now
-
#### Likely outcome
A malformed `repayment_day` is a config error.

#### Build notes
**Done 2026-09-26** on branch `fix/review-low`. `_repayment_day_to_int` now
raises `ValueError` for a non-numeric value or one outside 1-31, while still
accepting `month_end` (31) and a missing value (1). Three tests added.
Output-neutral.

#### Promotion trigger
-
#### Related records
`src/engine/schema.py`; `tests/test_contracts_repoint.py`.

---

### REVIEW-006: Somerton cap test uses synthetic figures, not the real data

Status: PROMOTED
Captured: 2026-09-26
Source: phase audit (Phase 12)

#### Context
`test_cap_breakage_from_profile.py::test_cap_allowance_tracks_somerton_refix`
claims in its docstring to lock "the real Gandon and Somerton figures", but uses
instalments `1433.91` / `1823.78` (allowances `143.39` / `182.38`). The actual
Property B data uses `1218.82` / `1550.21` (allowances `121.88` / `155.02`). The
Gandon figure is real; the Somerton pair is not, so the test does not lock the
real data.

#### Reason not now
-
#### Likely outcome
The test asserts the real Property B figures.

#### Build notes
**Done 2026-09-26** on branch `fix/review-medium`. The test now uses the real
sample instalments `1218.82` / `1550.21` and asserts the real allowances
`121.88` / `155.02`, matching the golden fixtures. Docstring updated.

#### Promotion trigger
-
#### Related records
`tests/test_cap_breakage_from_profile.py`; `data_sample/property_b/inputs.sample.yaml`.

---

### REVIEW-007: Cap allowance is unknown for most of the loan's life

Status: CANDIDATE
Captured: 2026-09-26
Source: phase audit (Phase 12)

#### Context
The allowance is emitted only where a contract states an `instalment`. For
Property A that is the A1 window only (43 of 422 months); A2 and A3 carry
`instalment: null`, so the allowance, headroom, and flag are blank from 2028-03
onward. The Summary sheet and portfolio rollup therefore show a blank cap state
whenever the as-of date falls after the first contract.

#### Reason not now
By design: the cap is a percentage of a stated instalment, and a derived PMT is
a projection, not an agreed figure.

#### Likely outcome
A documented decision on whether to derive the instalment via PMT (flagged as
projected) or carry the last known instalment, so the cap is visible across the
whole term.

#### Build notes
If adopted, resolve the allowance from a PMT-derived instalment and mark it
projected; re-baseline the golden fixtures.

#### Promotion trigger
When the live-position cap view is needed beyond the first contract.

#### Related records
`src/engine/schema.py`; `src/engine/monthly.py`; `tools/portfolio.py`.

---

### REVIEW-008: The cap flag cannot see an unagreed overpayment

Status: PROMOTED
Captured: 2026-09-26
Source: phase audit (Phase 7 / Phase 12)

#### Context
`overpayment_cap_flag` is driven by the `overpayment` column, which is the
**agreed** standing extra. Any extra the borrower actually paid through the bank
lands in `difference`, not `overpayment`. A real-world breach (paying more than
the cap via the bank) therefore leaves the flag at "ok". For a feature whose
purpose is to flag cap breaches, this is a meaningful gap.

#### Reason not now
-
#### Likely outcome
A flag that reflects the money actually overpaid.

#### Build notes
**Done 2026-09-26** on branch `fix/review-priority`. `build_monthly_schedule`
now measures the cap against `overpayment + max(0, difference)` (the agreed
extra plus any positive unattributed excess; a negative Difference is an
underpayment and is floored at zero). In the bundled samples the Difference is
zero in every allowance month, so **no golden fixture was re-baselined**. Two
regression tests added (`test_cap_flag_sees_an_unagreed_bank_overpayment`,
`test_cap_flag_ignores_an_underpayment`).

#### Promotion trigger
-
#### Related records
`src/engine/monthly.py`; `src/engine/simulate.py`; `tests/test_overpayment_cap_headroom.py`.

---

### REVIEW-009: The final payoff month attributes the full agreed overpayment

Status: CANDIDATE
Captured: 2026-09-26
Source: phase audit (Phase 7)

#### Context
In the closing month the debit is trimmed to clear the balance, but the
attribution still recognises the full agreed overpayment. For Property A month
`205504`, `overpayment=200.00` is attributed even though the trimmed debit was
`707.83`; the `-1648.11` difference absorbs it. Conservation holds, but the
attribution is arguably misleading in the closing month.

#### Reason not now
Conservation is intact and the difference column makes the residual explicit.

#### Likely outcome
The closing month's overpayment is capped at what the trimmed debit allows.

#### Build notes
Cap the recognised overpayment at the month's remaining debit in
`build_monthly_schedule`; re-baseline the golden fixtures.

#### Promotion trigger
-
#### Related records
`src/engine/monthly.py`.

---

### REVIEW-010: The golden master does not lock workbook Summary numbers

Status: PROMOTED
Captured: 2026-09-26
Source: phase audit (Phase 4 / Phase 8)

#### Context
The golden master compares CSVs to 2dp and the effective-inputs YAML
byte-for-byte. The workbook Summary sheet (as-of balance, current rate, next
payment, cap state, portal metrics, property value, LTV) is **not** numerically
locked: `test_output_structure.py` checks sheet names and order only. A
regression in a Summary figure would pass the suite.

#### Reason not now
-
#### Likely outcome
The Summary's key figures are locked, so a presentation regression is caught.

#### Build notes
**Done 2026-09-26** on branch `fix/review-priority`. Added a `summary.csv`
fixture per property (`tests/fixtures/golden/<scope>/summary.csv`) and a
`test_workbook_summary_locked` case in `test_golden_master.py` that compares the
produced Summary metric/value pairs exactly. Verified non-vacuous: corrupting a
fixture fails the test. No existing fixture changed.

#### Promotion trigger
-
#### Related records
`tests/test_golden_master.py`; `tests/test_output_structure.py`; `src/engine/__main__.py`.

---

### REVIEW-011: `portfolio_totals_by_currency.csv` is not golden-locked

Status: CANDIDATE
Captured: 2026-09-26
Source: phase audit (Phase 4 / Phase 11)

#### Context
`ROOT_CSV_FILES` in the golden master lists only `portfolio_summary.csv`, so the
per-currency totals file is shape-checked but its numbers are not locked.

#### Reason not now
The totals are a sum of already-locked per-property figures.

#### Likely outcome
The per-currency totals are locked like the summary.

#### Build notes
Add `portfolio_totals_by_currency.csv` to `ROOT_CSV_FILES` and capture the
fixture.

#### Promotion trigger
-
#### Related records
`tests/test_golden_master.py`; `tools/portfolio.py`.

---

### REVIEW-012: `csv_subdir` can escape the output directory

Status: CANDIDATE
Captured: 2026-09-26
Source: phase audit (Phase 8)

#### Context
`_resolve_output` strips surrounding slashes from `csv_subdir` but not `..`, so
`csv_subdir: ".."` writes CSVs into the parent of the output directory.

#### Reason not now
Requires a deliberately malformed config; no live impact.

#### Likely outcome
A `csv_subdir` containing `..` is rejected.

#### Build notes
Reject any `csv_subdir` whose resolved path leaves `out_dir`.

#### Promotion trigger
-
#### Related records
`src/engine/schema.py`.

---

### REVIEW-013: `_resolve_output` silently treats an unrecognised string flag as False

Status: PROMOTED
Captured: 2026-09-26
Source: phase audit (Phase 6)

#### Context
`_resolve_output._flag` returns `False` for any string not in the truthy set, so
`write_excel: "maybe"` silently disables the workbook rather than erroring.

#### Reason not now
-
#### Likely outcome
An unrecognised boolean string is a config error.

#### Build notes
**Done 2026-09-26** on branch `fix/review-low`. `_as_bool` gained a `strict`
mode; `_resolve_output._flag` uses it, so an unrecognised string raises while a
quoted `"false"` still reads as False. Two tests added. Output-neutral.

#### Promotion trigger
-
#### Related records
`src/engine/schema.py`; `tests/test_contracts_repoint.py`.

---

### REVIEW-014: `_is_valuation_only` treats a missing `actuals` as valuation-only

Status: CANDIDATE
Captured: 2026-09-26
Source: phase audit (Phase 11)

#### Context
`_is_valuation_only` (in `tools/portfolio.py` and `tests/conftest.py`) returns
`True` when a manifest entry has no `actuals`. A mortgage property that forgets
to list `actuals` is therefore silently routed to the valuation-only path rather
than erroring.

#### Reason not now
The signal is correct for a genuine owned-outright property.

#### Likely outcome
A mortgage-kind entry with no `actuals` is a config error.

#### Build notes
Cross-check `property_kind` against the presence of `actuals` and raise on a
mismatch.

#### Promotion trigger
-
#### Related records
`tools/portfolio.py`; `tests/conftest.py`.

---

### REVIEW-015: Silent `except Exception` in as-of derivation

Status: REJECTED
Captured: 2026-09-26
Source: phase audit (Phase 11)

#### Context
`_derive_as_of` and `_derive_valuation_as_of` swallow any exception while
reading the inputs YAML and fall back to `{}`, so a malformed inputs file yields
a blank as-of date with no warning. Part of the broader NEW-2 family of broad
exception handlers.

#### Reason not now
**Duplicate of NEW-2.** Groomed 2026-09-26: the two sites are folded into
NEW-2's scope, so this item is closed rather than tracked separately.

#### Likely outcome
A malformed inputs file warns rather than silently blanking the as-of.

#### Build notes
Narrow the exception to `yaml.YAMLError` / `OSError` and log a warning.

#### Promotion trigger
-
#### Related records
`tools/portfolio.py`; NEW-2.

---

### REVIEW-016: `_read_valuation_anchor` silently falls back to loan-derived fields

Status: CANDIDATE
Captured: 2026-09-26
Source: phase audit (Phase 6)

#### Context
When the `valuation:` block is absent, `_read_valuation_anchor` falls back to
loan-derived fields on `Inputs`. The fallback is bounded by a fail-loud check
for a positive base value and a base date, so it cannot silently emit a flat
series, but the fallback itself is undocumented at the call site.

#### Reason not now
The fail-loud guard bounds the risk.

#### Likely outcome
The fallback is either documented as intended or removed.

#### Build notes
Add a comment or a warning when the fallback path is taken.

#### Promotion trigger
-
#### Related records
`src/engine/valuation_only.py`.
