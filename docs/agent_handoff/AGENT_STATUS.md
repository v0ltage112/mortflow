# AGENT_STATUS.md — Current Operational Truth

> The single source of current state. Update at every phase close and whenever
> the active assignment changes. If this file and the repository disagree, the
> repository wins — then correct this file.

**Last updated:** 2026-09-26
**Updated by:** phase audit 0-12 + REVIEW fix passes (priority, medium, low)

---

## Current position

| Field | Value |
| --- | --- |
| Current phase | **Phase 13 - Scenario / What-If Analysis (Mortgage Layer)** |
| Phase status | Active (scaffolded 2026-07-20) |
| Active session | **Phase 13 / S1 - `scenarios.yaml` schema, loader, and clone-and-perturb** |
| Active work package | `work_packages/FEATURE_P13_scenario_engine.md` |
| Current branch | `main` (feature branch `phase13/scenario-engine` to be cut at S1 apply) |
| Last verified commit | `71368af` (main, after the phase audit and REVIEW fix passes) |
| Target tag | `v2.3.0` |
| Rollback reference | `v2.2.0` |
| Working tree | Clean |
| Public repo | `github.com/v0ltage112/mortflow` |
| Local code path | `C:\Code\mortflow` (off any cloud sync) |
| Data + out path | Private, outside the repo, linked via git-ignored `paths.local.yaml` (see `START_AGENT.md`) |
| Old private repo | `github.com/v0ltage112/mortgage-model` (archived) |
| Test count at last ship | 171 passed / 4 skipped / 0 failed (Phase 12, `v2.2.0`) |
| Test count now | 211 passed / 4 skipped / 0 failed (after the phase audit + REVIEW-000/001/003/004/005/006/008/010/013) |

---

## Active phase summary

**Phase 13** adds scenario / what-if analysis to the mortgage layer: ask "what
if?" across overpayments, lump sums, rate shocks at refix, and mortgage offer
comparisons with breakage fees. Scenarios are declared in `scenarios.yaml`.

**Sessions (verified against Notion Master Handoff, 2026-07-20):**

| Session | Deliverable | Status |
| --- | --- | --- |
| S0 | Setup / scaffold | Done (2026-07-20) |
| S1 | `scenarios.yaml` schema, loader, clone-and-perturb plumbing; perturbation dataclasses; user-editable custom overpayment block | **Active (next)** |
| S2 | Scenario runner pipeline (isolation) + inert rental/tax transform hooks | Planned |
| S3 | Perturbation types wired to the engine (`monthly_overpayment`, `lump_sum`, `contract_rate_change`, recurring annual lump) | Planned |
| S4 | Always-generated set + comparison/stacked modes + output metrics | Planned |
| S5 | `mortgage_offer_comparison` + breakage fee (gated on BOI wording + R%/R1%) | Planned |
| S6 | Payoff-target solver | Planned |
| S7 | Analytical test suite + inert-hook confirmation | Planned |
| S8 | Scenario report output (`scenarios.xlsx` + comparison summary) + Report Q&A | Planned |
| S9 | Ship `v2.3.0` | Planned |

**Always-generated scenario set (locked 2026-07-20):** `baseline`,
`max_cap_overpayment`, `overpay_to_cap_no_breach`, `rate_plus_1pct_at_refix`,
`rate_minus_1pct_at_refix`, `rate_plus_2pct_at_refix`, `rate_plus_3pct_at_refix`,
`current_lump_sum_today`, `lump_at_next_refix`, `recurring_annual_lump`,
`stacked_worst_realistic`, `stacked_best_realistic`, plus a user-editable custom
overpayment block.

**Expected new files (additive only):** `scenarios.yaml`; `src/scenarios/`
(`schema.py`, `loader.py`, `runner.py`, `metrics.py`, `offer.py`, `solve.py`,
`report.py`); `tools/scenarios.py`; `tests/test_scenarios_*.py`.

---

## Blockers

- **Golden master currently failing** (time-dependent; see below). This must be
  resolved before Phase 13 work begins, because Phase 13 relies on a green
  baseline.
- **Phase 13 / S5 gating:** the exact BOI breakage wording and the R% / R1%
  money-market rate source are still required from the project owner. If not
  ready at S5, ship offer comparison without breakage and add it in a follow-on.

---

## Evidence still required

- The exact BOI breakage wording and the R% / R1% money-market rate source (S5).
- Confirmation at S1 whether actuals-based scenarios ship in `v2.3.0` or defer
  (hypothetical scenarios are built fully either way).
- The default opportunity-cost alternative return rate (S4).
- Output placement confirmation: dedicated `scenarios.xlsx` per property plus a
  comparison summary, or a Scenarios sheet on each property workbook (S1/S8).

---

## Known repository defects (not yet fixed)

These were found during the 2026-09-26 review and are logged in
`PRODUCT_BACKLOG.md`. None are Phase 13 scope.

1. ~~**Time-dependent golden master**~~ **FIXED 2026-09-26** on branch
   `fix/golden-master-determinism` (BACKLOG-001). `_valuation_summary_row` now
   derives its as-of date from config (`valuation.as_of_date`, else
   `modelling.end_date`) instead of `date.today()`. Suite is green: 173 passed /
   4 skipped / 0 failed. The golden fixture was **not** re-baselined.
2. ~~`tests/test_overpayment_cap_headroom.py` is committed but **empty (0 bytes)**.~~
   **FIXED 2026-09-26** (BACKLOG-002): 18 tests authored, locking the flag
   boundaries, headroom maths, the 90% trip point, the null passthrough, and the
   cumulative total.
3. ~~`Path.read_text()` without explicit `encoding="utf-8"` in several modules.~~
   **FIXED 2026-09-26** (BACKLOG-003): explicit UTF-8 on all remaining reads
   and writes in `src/` and `tools/`.
4. ~~Duplicated `_VALUATION_ONLY_KINDS`, `_slugify`, and tax date helpers.~~
   **FIXED 2026-09-26** (BACKLOG-004): the kind set now lives once in
   `schema.VALUATION_ONLY_KINDS`; `slugify` is imported from `helpers`; the tax
   month-end helper is shared. `tax._ensure_date` stays local (deliberately
   lenient where the engine's is strict).
5. ~~`assert` used for input validation in `tools/portfolio.py`.~~ **FIXED
   2026-09-26** (BACKLOG-005): now raises `ValueError` with an actionable
   message; 3 tests added.
6. ~~README version history stops at v2.1.0 (v2.2.0 missing); test count stale.~~
   **FIXED 2026-09-26** (BACKLOG-007): v2.2.0 row added; test count corrected.
7. ~~Eleven modules print a "ready" line at import time.~~ **FIXED 2026-09-26**
   (NEW-1): all import-time prints removed; seven now-unused `import sys` lines
   dropped. Importing `src.engine` is now silent.
8. ~~No `.gitattributes`.~~ **FIXED 2026-09-26** (NEW-3): added, pinning golden
   fixtures to LF and `.bat` files to CRLF.
9. ~~`run_sample.bat` used inline `python -c`.~~ **FIXED 2026-09-26** (NEW-4):
   now uses the `tools/_resolve.py` shim, matching `run.bat`.
10. ~~Five lines over 120 characters in `src/`.~~ **FIXED 2026-09-26** (NEW-5).
11. ~~No `pyproject.toml`; `pytest` in runtime requirements.~~ **FIXED
    2026-09-26** (BACKLOG-006): `pyproject.toml` added; `pytest` moved to
    `requirements-dev.txt`.

**Still open:** twelve broad `except Exception` blocks, two of which swallow the
error silently (`src/engine/__main__.py:249`, `tools/portfolio.py:314`). Logged
as NEW-2; not yet fixed.

---

## Phase audit (2026-09-26)

A detailed, evidence-based review of every completed phase (0-12) was carried
out. Every phase does what it claims, and the outputs are correct against the
golden fixtures. Findings are logged as `REVIEW-000..016` in
`PRODUCT_BACKLOG.md`.

**Fixed and merged (no golden fixture re-baselined):**

| Item | What |
| --- | --- |
| REVIEW-000 | Quoted string booleans; non-deterministic workbook table names; test-file encodings |
| REVIEW-001 | Contract contiguity validation (gap/overlap/early open-ended now raise) |
| REVIEW-003 | `contracts: []` now raises instead of silently falling back to legacy |
| REVIEW-004 | Missing lender profile now warns on stderr |
| REVIEW-005 | Malformed `repayment_day` now raises instead of silently becoming 1 |
| REVIEW-006 | Somerton cap test now uses the real sample figures |
| REVIEW-008 | Cap flag now sees an unagreed bank overpayment |
| REVIEW-010 | Workbook Summary numbers are now golden-locked |
| REVIEW-013 | Unrecognised boolean strings now raise |

**Deferred:** REVIEW-007 (cap allowance blank for most of the loan's life) needs
a design decision (agreed vs projected instalment) and a deliberate golden
re-baseline.

**Open (low severity):** REVIEW-002, 009, 011, 012, 014, 016.

---

## Exact next action

1. **Return to REVIEW-007** (agreed vs projected instalment for the cap), or
   sweep the remaining low-severity REVIEW items.
2. **Cut `phase13/scenario-engine`** off `main` and begin S1
   (`scenarios.yaml` schema, loader, and clone-and-perturb).
3. Confirm the S1 open questions (actuals-based scenarios, output placement).

---

## Backlog items created or changed this session

- `BACKLOG-001` — Fix time-dependent golden master (from review).
- `BACKLOG-002` — Remove or fill empty test file.
- `BACKLOG-003` — Explicit UTF-8 encodings on text reads.
- `BACKLOG-004` — De-duplicate kind sets, slugify and tax date helpers.
- `BACKLOG-005` — Replace `assert` validation with `ValueError`.
- `BACKLOG-006` — Add `pyproject.toml`; move pytest to dev requirements.
- `BACKLOG-007` — Refresh README version history and test count.
- `REVIEW-000..016` — Phase audit findings (see `PRODUCT_BACKLOG.md`).

**Confirmation:** no backlog item is represented as active. Phase 13 is the only
active work.
