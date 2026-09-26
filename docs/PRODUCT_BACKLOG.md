# PRODUCT_BACKLOG.md — Possible Future Work

> The **single authoritative home** for possible future work outside the active
> delivery pipeline: deferred features, ideas, enhancements, technical debt,
> investigations and improvements not currently authorised for delivery.
>
> **Recording an item here does not authorise its implementation.** Do not
> implement a backlog item unless it is explicitly **PROMOTED** into
> `PRODUCT_DELIVERY_PLAN.md`.

**Last updated:** 2026-09-26

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

Status: READY
Captured: 2026-09-26
Source: repo review

#### Context
Several `Path.read_text()` calls omit `encoding="utf-8"` (schema, tax,
portfolio, `__main__`), so Windows uses the locale code page.

#### Reason not now
Not Phase 13 scope.

#### Likely outcome
Portable, locale-independent file reads.

#### Build notes
Add `encoding="utf-8"` (or `utf-8-sig` where a BOM is possible).

#### Promotion trigger
Immediate — small, low risk.

#### Related records
`DECISIONS_AND_LEARNINGS.md` (L5).

---

### BACKLOG-004: De-duplicate kind sets, slugify and tax date helpers

Status: CANDIDATE
Captured: 2026-09-26
Source: repo review

#### Context
`_VALUATION_ONLY_KINDS` is defined in both `tests/conftest.py` and
`tools/portfolio.py`; `_slugify` duplicates `helpers.slugify`; `src/tax.py`
re-implements `_ensure_date` / `_eom` / `_days_in_month`.

#### Reason not now
Not Phase 13 scope.

#### Likely outcome
One canonical definition of each, imported everywhere.

#### Build notes
Move the kind set into `schema.py`; import `helpers.slugify`; reuse the shared
date helpers.

#### Promotion trigger
When touching those modules for another reason.

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

Status: CANDIDATE
Captured: 2026-09-26
Source: repo review

#### Context
No `pyproject.toml`; `pytest` is listed in runtime `requirements.txt` though it
is a dev tool.

#### Reason not now
Not Phase 13 scope.

#### Likely outcome
Standard project metadata and a clean runtime/dev split.

#### Build notes
Add `pyproject.toml`; move `pytest` to `requirements-dev.txt`.

#### Promotion trigger
When packaging or tooling is next touched.

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
