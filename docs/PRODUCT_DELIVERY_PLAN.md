# PRODUCT_DELIVERY_PLAN.md — Authorised and Sequenced Work

> The authorised delivery pipeline. One phase is active at a time. Feature
> execution detail lives in `agent_handoff/work_packages/`, not here. Possible
> future work lives in `PRODUCT_BACKLOG.md` and is **not** authorised by being
> listed there.

**Last updated:** 2026-09-26

---

## Phase table

| Phase | Status | Goal | Target tag | Work package |
| --- | --- | --- | --- | --- |
| 0 | Done | Pre-Notion baseline: daily engine, reconcile, Form 11, portfolio runner, strict baseline, 70+ tests | `v0.7.0` | - |
| 1 | Done | Notion re-platform / handoff scaffolding | n/a | - |
| 2 | Done | Remove OneDrive dependency; config-driven paths | `v1.3.0` | - |
| 3 | Done | Security audit; public `mortflow` repo | `v1.4.0` | - |
| 4 | Done | Verification & behaviour lock (golden master) | `v1.5.0` | - |
| 5 | Done | `engine.py` refactor into `src/engine/` package | `v1.6.0` | - |
| 6 | Done | Multi-property scaffolding & toggles | `v1.7.0` | - |
| 7 | Done | Overpayment attribution | `v1.8.0` | - |
| 8 | Done | Output deliverables | `v1.9.0` | - |
| 9 | Done | Contract ingestion & clause mapping (analysis + design) | *(no tag)* | - |
| 10 | Done | Contract schema redesign & Inputs formalisation | `v2.0.0` | - |
| 11 | Done | Activation of properties A, B, C + manifest refactor | `v2.1.0` | - |
| 12 | Done | Overpayment cap (compute & flag) | `v2.2.0` | - |
| **13** | **Active** | **Scenario / what-if analysis (mortgage layer)** | **`v2.3.0`** | `FEATURE_P13_scenario_engine.md` |
| 14 | Planned | Multi-property dashboard (charts, LTV trends, comparative KPIs) | TBD | - |
| 15 | Planned | RPZ projection (max permissible rent, forward projection) | TBD | - |
| 16+ | Backlog | See `PRODUCT_BACKLOG.md` | TBD | - |

> Historical phases 0-12 are summarised here. Full per-phase and per-session
> detail remains in the Notion `mortgage_model` workspace (the master record).

**Phase 12 ship evidence:** `main` `218f8ce`, merged `phase12/overpayment-cap`
`--no-ff` (`313a968..218f8ce`), annotated tag `v2.2.0`; 171 passed / 4 skipped /
0 failed; rollback `v2.1.0`.

---

## Active phase: 13 — Scenario / What-If Analysis (Mortgage Layer)

**Goal:** ask "what if?" across overpayments, lump sums, rate shocks at refix,
and mortgage offer comparisons with breakage fees. Scenarios declared in
`scenarios.yaml`, run in isolation against the frozen `Inputs`.

**Branch:** `phase13/scenario-engine` (off `main` at `218f8ce`)
**Target tag:** `v2.3.0` · **Rollback:** `v2.2.0`

**Sessions:** S0 setup Done (2026-07-20) · S1 schema/loader/clone-and-perturb
(active) · S2 runner pipeline + inert hooks · S3 perturbation types · S4
always-generated set + modes + metrics · S5 offer comparison + breakage · S6
payoff-target solver · S7 analytical tests · S8 report output · S9 ship `v2.3.0`.

**Scope guardrails:** mortgage layer only (rental/tax layers are separate backlog
items with inert hooks); additive (no breaking `inputs.yaml` change);
perturbations act on a clone of the frozen `Inputs`; overpayment scenarios
respect the Phase 12 cap allowance; analytical (closed-form) tests, not golden
masters; Gandon interest-saved is gross only this phase (net-of-tax needs the tax
layer).

See `agent_handoff/work_packages/FEATURE_P13_scenario_engine.md` for detail.

---

## Protected baselines

- **Golden master** (`tests/fixtures/golden/`) — the behaviour lock.
- **Conserved quantities** — total paid, interest, principal, balance, payoff.
- **`data_sample/`** — the tracked demo data the golden master runs against.
- **`v2.2.0`** — the rollback reference for Phase 13.

---

## Release gates

A phase may be tagged only when:

1. The full test suite passes on `main` after merge.
2. The golden master is green (or deliberately re-baselined with evidence).
3. The README version history and test count are updated.
4. The work package is closed and `AGENT_STATUS.md` is updated.
5. The working tree is clean.

---

## Backlog items that may affect future phases

These are **not** committed delivery. See `PRODUCT_BACKLOG.md` for detail.

- Rental scenario layer, tax scenario layer, investment decision layer — likely
  future phases after 13.
- Layered metrics refactor — may affect the dashboard (Phase 14).
- RPZ — Phase 15.
