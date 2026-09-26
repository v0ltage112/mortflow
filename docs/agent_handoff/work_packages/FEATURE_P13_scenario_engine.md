# FEATURE_P13_scenario_engine.md — Phase 13: Scenario / What-If Analysis (Mortgage Layer)

> Active work package. One phase is active at a time.

---

## Identity

| Field | Value |
| --- | --- |
| Feature ID | `P13` (sessions S0-S9) |
| Title | Scenario / What-If Analysis (Mortgage Layer) |
| Phase | Phase 13 |
| Branch | `phase13/scenario-engine` (to be cut off `main` at `218f8ce` at S1 apply) |
| Starting commit | `218f8ce` (tag `v2.2.0`) |
| Target tag | `v2.3.0` |
| Rollback reference | `v2.2.0` |
| Status | Active - scaffolded 2026-07-20; S1 next |

## Objective

Let the user ask "what if?" across overpayments, lump sums, rate shocks at refix,
and mortgage offer comparisons with breakage fees. Scenarios are declared in
`scenarios.yaml` and run in isolation against the frozen `Inputs`, so the
baseline is never mutated.

## In scope

- `scenarios.yaml` schema, loader, and clone-and-perturb plumbing on the frozen
  `Inputs`; perturbation dataclasses; the user-editable custom overpayment block
  (S1).
- Scenario runner pipeline (isolation mode) with inert rental/tax transform hooks
  (S2).
- Perturbation types wired to the engine: `monthly_overpayment`, `lump_sum`
  (dated), `contract_rate_change` (rate shock at refix), recurring annual lump
  (S3).
- Always-generated scenario set + comparison and stacked execution modes +
  output metrics (S4).
- `mortgage_offer_comparison` perturbation + breakage fee (S5).
- Payoff-target solver (S6).
- Analytical test suite + inert-hook confirmation (S7).
- Scenario report output (`scenarios.xlsx` per property + cross-scenario
  comparison summary) + Report Q&A (S8).
- Ship `v2.3.0` (S9).

### Always-generated scenario set (locked 2026-07-20)

`baseline`, `max_cap_overpayment`, `overpay_to_cap_no_breach`,
`rate_plus_1pct_at_refix`, `rate_minus_1pct_at_refix`, `rate_plus_2pct_at_refix`,
`rate_plus_3pct_at_refix`, `current_lump_sum_today`, `lump_at_next_refix`,
`recurring_annual_lump`, `stacked_worst_realistic`, `stacked_best_realistic`,
plus a clearly-marked user-editable custom overpayment block.

### Perturbation types

- `monthly_overpayment` (amount, from_date).
- `lump_sum` (amount, date).
- `contract_rate_change` (contract_id, new_rate or rate_delta, applied at that
  contract's start_date).
- `mortgage_offer_comparison` (alternative contract spec + breakage structure).
- Recurring annual lump (amount, month, from_date).

### Output metrics per scenario

Interest saved lifetime; interest saved to next refix; payoff date change
(months); cap headroom used vs available; opportunity cost vs an alternative
return rate. Gandon (rental) interest-saved is gross only this phase.

### Expected new files (additive only)

`scenarios.yaml`; `src/scenarios/{schema,loader,runner,metrics,offer,solve,report}.py`;
`tools/scenarios.py`; `tests/test_scenarios_*.py`.

## Out of scope

- Rental scenario layer, tax scenario layer, investment decision layer
  (backlog — see `PRODUCT_BACKLOG.md`).
- Dashboard (Phase 14) and RPZ (Phase 15).
- Any change to the golden master beyond additive scenario outputs.

## Dependencies

- Phase 10 frozen `Inputs` and `.copy()` / `.clone()`.
- Phase 12 overpayment-cap allowance and headroom resolvers
  (`resolve_overpayment_cap_allowance`, `overpayment_cap_for_contract`).
- Phase 9 / S3 breakage lock (`docs/bank_semantics.md`) and the lender profile
  `money_market_rates` series.
- Phase 8 workbook writer helpers (for style parity in S8).

## Protected areas

- `tests/fixtures/golden/` — the behaviour lock.
- Conserved quantities: total paid, interest, principal, balance, payoff.
- The frozen `Inputs` dataclass — clone, never mutate.
- `data_sample/`.

## Evidence inspected

- Notion Phase 13 pages (search highlights only — full bodies not yet read).
- Repository: `src/engine/schema.py`, `src/engine/simulate.py`,
  `src/engine/profile.py`, `tools/portfolio.py`.

## Implementation plan

1. **S1** — author `scenarios.yaml` schema, loader, and clone-and-perturb.
2. **S2** — build the runner pipeline with isolation and inert layer hooks.
3. **S3** — wire perturbation types to the engine.
4. **S4** — always-generated set, execution modes, output metrics.
5. **S5** — mortgage offer comparison + breakage fee.
6. **S6** — payoff-target solver.
7. **S7** — analytical test suite + inert-hook confirmation.
8. **S8** — scenario report output + Report Q&A.
9. **S9** — docs/README, ship v2.3.0.

## Acceptance criteria

- [ ] Scenarios run in isolation; the baseline `Inputs` is never mutated.
- [ ] Inert rental/tax hooks are pass-throughs with no logic.
- [ ] `overpay_to_cap_no_breach` uses the Phase 12 allowance exactly.
- [ ] Payoff-target solver handles: target already met, target impossible at cap.
- [ ] Analytical test suite passes.
- [ ] Golden master unchanged except for additive scenario outputs.
- [ ] README version history and test count updated at S9.

## Files changed

| File | Change |
| --- | --- |
| *(to be completed per session)* | |

## Commands or packages supplied

- *(to be completed per session)*

## Returned execution evidence

- *(to be completed per session)*

## Tests and output validation

- Before: *(record at S1 start)*
- After: *(record per session)*
- Output inspection: *(record per session)*

## Decisions and reusable learning

- Scenarios are declared in `scenarios.yaml` (config-driven, no code edit).
- The baseline `Inputs` is never mutated; every scenario runs on a clone.
- The runner is a pipeline; rental/tax layers are transforms, not embedded logic.
- Analytical (closed-form) tests, not golden masters, for dynamic scenario output.
- Breakage fee default follows the Phase 9 / S3 lock:
  `principal x max(0, existing_rate - replacement_rate) x remaining_fixed_years / 365`,
  with R% / R1% from the lender profile `money_market_rates` series.
- Gandon interest-saved is gross only; flag it, never present gross as net.

## Git evidence

- Commit(s): *(per session)*
- Tag: `v2.3.0` (at S9)
- Rollback reference: `v2.2.0`

## Unresolved items

- Exact BOI breakage wording and the R% / R1% money-market rate source (S5).
- Whether actuals-based scenarios ship in `v2.3.0` or defer (confirm at S1).
- Default opportunity-cost alternative return rate (S4).
- Output placement: dedicated `scenarios.xlsx` + comparison summary, or a
  Scenarios sheet on each property workbook (S1/S8).
- Where scenario metrics live (S4).

## Exact successor action

1. Resolve the golden-master time dependency so the baseline is green.
2. Cut `phase13/scenario-engine` off `main` at `218f8ce`.
3. Begin **S1**: `scenarios.yaml` schema, loader, and clone-and-perturb.

## Closure status

Open — S0 complete, S1 not started.
## Pre-phase maintenance (2026-09-26)

Before Phase 13 began, a review of the repository (which was built without the
Companion Coach skill) produced a set of defects. All were fixed on short-lived
branches, each merged to `main` with `--no-ff` and pushed. **No golden fixture
was re-baselined at any point.** Test count moved from 170 passed / 1 failed to
194 passed / 4 skipped / 0 failed.

| Branch | Commit | Scope |
| --- | --- | --- |
| `refactor/repo-structure-privacy` | `4a5aeb6` | Companion Project handoff infrastructure (this docs set) |
| `fix/golden-master-determinism` | `2a26f1d` | BACKLOG-001: deterministic valuation-only rollup as-of date |
| `chore/review-defects` | `11b39ff` | BACKLOG-002/005/007: cap-headroom tests, `ValueError`, README |
| `chore/minor-defects` | *(this branch)* | BACKLOG-003/004/006 + NEW-1/3/4/5 |

**Still open:** NEW-2 (twelve broad `except Exception` blocks, two silent).
## Backlog items created, updated, promoted or superseded

- None from this work package yet.

## Out-of-scope findings transferred to the product backlog

- None yet.

## Confirmation

- [x] Deferred work was **not** implemented.
- [x] No backlog item is represented as active unless promoted.
