# Contract data model (Phase 10 build brief)

> Section A (this file), authored in P9/S4: the Contract object and the loan / contract data model. Section B (lender profile, universal rules, cascade map, migration) is authored in S5; Section C (anonymisation mapping, data, Phase 10 plan) in S6.
>
> All figures below are illustrative placeholders, not real contract values. Real amounts, dates, and account numbers stay off-repo. This file carries structure and reasoning only, never verbatim legal wording.

## A0. Purpose and scope

This document is the Phase 10 build brief for the contract data model. It replaces the month-number rate model with a date-based `contracts:` array, separates loan-level facts from contract-level facts, and defines the Contract object a fresh agent implements in Phase 10 (`v2.0.0`). Section A locks the object shape and the loan / contract split. The universal rules layer, the cascade map, and the migration plan are Section B (S5); the anonymisation mapping, the data files, and the Phase 10 session breakdown are Section C (S6).

## A1. Two levels: Loan and Contract

Design principle: money advanced is a loan fact; the rate agreement over time is a sequence of contracts. A property has exactly one loan (one drawdown of new money) and one or more contracts over that loan's life. A refix advances no new money, so it is a new Contract on the same loan, not a new drawdown. The only genuine second loan-level money event would be a further advance or top-up, which no property has today.

### Loan (one per property)

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `property_id` | str | required | Stable id for the property. |
| `lender` | str | required | Profile key (for example `boi`). Resolves the universal rules; see Section B. |
| `drawdown_amount` | decimal | required | New money advanced, once per loan. |
| `drawdown_date` | date | required | Date the money was advanced. |
| `total_term_months` | int | required | Full amortisation term. |
| `maturity_date` | date or null | null | Derived from drawdown plus term if null. |
| `property_value` | decimal | required | For LTV and valuation. |
| `valuation_blocks` | list | empty list | Unchanged from today. |
| `repayment_day` | int or month_end | required | Per-account (illustrative: day-5 or month-end). Governs projected dates only. |
| `property_growth_pa` | decimal | required | Unchanged from today. |
| `tax` / `tenancy` | object | as today | Unchanged from today. |
| `contracts` | list of Contract | required | Ordered by `start_date`. |

### Contract (one or more per loan)

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `id` | str | required | Stable id, for example A1, B2, B3. |
| `start_date` | date | required | Contract start (drawdown date for the first; day after the prior contract's end for a refix). |
| `end_date` | date or null | null | Fixed-period end; null = open-ended (rolled to variable with no agreed end). |
| `rate` | decimal | required | Annual fixed rate for this contract's period (for example 0.0350). |
| `rate_type` | fixed / variable / tracker | fixed | Rate character during this contract. |
| `instalment` | decimal or null | null | Contractual monthly repayment. Null = engine derives via PMT. A bank-stated figure that differs from a naive PMT because of a payment break or capitalisation overrides the derivation. |
| `follow_on` | object or null | null | Directional roll-to rate; see A2. |
| `standing_overpayment` | object or null | null | Recurring voluntary overpayment window; see A3. |
| `payment_events` | list | empty list | Contract-scoped events; see A4. |
| `overpayment_cap_override` | object or null | null | Null = inherit the profile rule effective at this contract's dates (Section B). |
| `breakage_override` | object or null | null | Null = inherit the profile. |

## A2. Rate model: fixed period plus a directional follow-on

A contract is a fixed period plus a directional rate for what happens after it, which is rarely exercised because a new contract is usually negotiated before the fixed period ends.

    follow_on:
      rate: 0.0450          # decimal or null
      rate_type: variable   # fixed | variable | tracker
      basis: "lender variable, LTV-banded"
      indicative: true      # non-binding, provisional
      note: "roll-to rate if not refixed; expected to be renegotiated first"

Rules: `follow_on` is non-binding. Projections past `end_date` use it only as a clearly flagged provisional assumption. Adding a refix Contract supersedes it. This preserves S3 decision (a): there is no confirmed mid-period rate split, and a refix stays provisional until a statement spans it.

## A3. Standing overpayment (date-based)

Replaces the month-number `overpay_rules`. For a recurring voluntary overpayment attached to a contract:

    standing_overpayment:
      amount: 120.00
      start_date: 2025-08-01
      end_date: 2026-06-30   # null = open-ended
      note: "voluntary overpay window; within allowance; ends at refix"

The cap check uses the profile allowance for this contract (Section B), applied to the contract `instalment`.

## A4. Payment events (date-based, contract-scoped)

Replaces `payment_holidays` plus `contractual_ladder`. Each event:

    payment_events:
      - type: payment_holiday        # payment_holiday | part_capital_increase | ...
        start_date: 2024-04-01
        end_date: 2024-08-01         # null = open-ended
        treatment: capitalise        # interest_only | capitalise | instalment_increase
        amount: null                 # decimal or null
        note: "3-month break; interest accrues daily and capitalises"

Covers a payment break (interest-only plus capitalise) and a formalised part-capital instalment increase (contractual, not an overpayment).

## A5. How `contracts:` subsumes the legacy constructs

| Legacy (today) | Replaced by |
| --- | --- |
| `rate_blocks` (month-number) | `Contract.start_date` / `end_date` / `rate`; month numbers become dates, engine derives month offsets from `drawdown_date` |
| `known_first_payment` | first `Contract.instalment` |
| `contractual_ladder` (Phase 7 steps) | per-Contract `instalment` across contracts plus `payment_events` for mid-contract formalised changes |
| `overpayment_cap_pct` (scalar) | retired; derived from the profile rule times `instalment` (Section B) |
| `overpay_rules` (start_month windows) | `Contract.standing_overpayment` (date windows) |
| `strategy_at_refix` | `follow_on` plus the presence or absence of a subsequent Contract |
| `payment_holidays` | `payment_events` with type payment_holiday |

## A6. Loan-level vs contract-level (quick reference)

- Loan-level (one per property): `property_id`, `lender`, `drawdown_amount`, `drawdown_date`, `total_term_months`, `maturity_date`, `property_value`, `repayment_day`, `property_growth_pa`, tax / tenancy.
- Contract-level (one per contract): `id`, `start_date`, `end_date`, `rate`, `rate_type`, `instalment`, `follow_on`, `standing_overpayment`, `payment_events`, overrides.

## A7. Illustrative examples (placeholder figures)

Single-contract loan with a payment break:

    loan:
      property_id: sample_a
      lender: boi
      drawdown_amount: 400000.00
      drawdown_date: 2024-04-01
      total_term_months: 420
      repayment_day: 5
      contracts:
        - id: A1
          start_date: 2024-04-01
          end_date: 2028-04-01
          rate: 0.0350
          rate_type: fixed
          instalment: 1900.00        # post-break recalculated figure; overrides naive PMT
          follow_on:
            rate: 0.0450
            rate_type: variable
            basis: "lender variable, LTV-banded"
            indicative: true
            note: "roll-to rate if not refixed; expected to be renegotiated first"
          payment_events:
            - type: payment_holiday
              start_date: 2024-04-01
              end_date: 2024-08-01
              treatment: capitalise
              note: "3-month break; interest accrues daily and capitalises"
            - type: part_capital_increase
              start_date: 2025-08-01
              end_date: null
              treatment: instalment_increase
              amount: 200.00
              note: "formalised part-capital increase; contractual, not an overpayment"

Two-contract loan across a refix with a standing overpayment:

    loan:
      property_id: sample_b
      lender: boi
      drawdown_amount: 350000.00
      drawdown_date: 2022-07-01
      total_term_months: 420
      repayment_day: month_end
      contracts:
        - id: B2
          start_date: 2022-07-01
          end_date: 2026-07-01
          rate: 0.0190
          rate_type: fixed
          instalment: 1200.00
          standing_overpayment:
            amount: 120.00
            start_date: 2025-08-01
            end_date: 2026-06-30
            note: "voluntary overpay window; within allowance; ends at refix"
          follow_on:
            rate: 0.0310
            rate_type: variable
            indicative: true
        - id: B3
          start_date: 2026-07-01
          end_date: 2030-07-01
          rate: 0.0310
          rate_type: fixed
          instalment: 1500.00
          # no standing overpayment on B3

## A8. Defaults summary

| Field | Default |
| --- | --- |
| `end_date` | null (open-ended) |
| `rate_type` | fixed |
| `instalment` | null (derive via PMT unless stated) |
| `follow_on` | null |
| `standing_overpayment` | null |
| `payment_events` | empty list |
| `overpayment_cap_override` | null (inherit profile) |
| `breakage_override` | null (inherit profile) |

## A9. Carried forward (locked from S1 to S3)

- Overpayment cap is a per-payment allowance of max(10% of the monthly repayment, EUR 65), not a calendar-year balance reset. Derived from the profile times the contract `instalment`.
- Breakage type `principal_x_rate_differential_x_remaining_years`, C = A x (R% - R1%) x D / 365, with R% / R1% external nullable BOI money-market rates; emit "not computable" when absent; a computed C of zero or less means no charge.
- Payment date is Modified Following (forward to the next working day; back to the last working day of the month if forward crosses into the next month). Payment day is per-account. Governs projected dates only, never an actual posted date.
- Mid-month rate change stays PROVISIONAL / UNCONFIRMED.
- Drawdown is a loan-level fact (one per property). A refix is a new Contract sharing the loan (no new money).

## A10. Deferred to S5 / S6

- S5: lender profile schema (effective-dated `rule_versions` plus rationale plus money-market rates), the rule-resolution anchor, cap-basis variants, the breakage formula catalog, the full cascade / ripple map, and the migration plus golden re-baseline (refactor before re-data).
- S6: anonymisation mapping (real to sample), the committed sample files, the private real-data blocks, and the confirmed Phase 10 session breakdown.
- Open decision for S5: which date anchors each rule lookup. Proposed default: the overpayment cap and the payment-date convention resolve on the event or contract-period date; breakage rates resolve on the breakage-quote date.

---

# Section B (P9/S5): Lender profile integration, cascade map, migration

> Authored in P9/S5. Fulfils the S5 items deferred in A10. The rules-layer
> authority is docs/lender_profile.md; this section does not restate the profile
> schema, it references it and specifies how the profile plugs into the model,
> which repo files change, and how the migration stays byte-identical before the
> one deliberate re-baseline.

## B0. Section B scope

Section A locked the loan / contract split and the Contract object. Section B
specifies how the per-lender profile (defined in docs/lender_profile.md) plugs
into that model, maps every repo file the change touches, and locks the
migration and golden re-baseline strategy for Phase 10.

## B1. Profile integration

- Each loan carries a lender key. On load, the engine resolves the profile
  (boi.local.yaml when present, else sample_lender.yaml) into the typed inputs.
- A Contract inherits the profile rule in force at its dates (LP7 anchors)
  unless it carries an explicit overpayment_cap_override or breakage_override
  (Section A). An override wins for that contract only.
- Resolution is by date, not by position: the rule version is the latest
  effective_from <= anchor date, and the anchor differs per rule (LP7).

## B2. Cascade / ripple map

Every repo file the contracts array and the profile touch, with the change
described. Verified against the live code (Phase 9 changed no engine code, so
main and this branch are identical for these files).

| File | Change |
| --- | --- |
| src/engine/schema.py | Largest change. Replace RateBlock/rate_blocks, ContractualStep/contractual_ladder, overpay_rules, known_first_payment, scalar overpayment_cap_pct, strategy_at_refix, and payment_holidays parsing with the Loan + contracts array (Section A). Add the lender key and a profile loader (read the profile file, parse rule_versions + money_market_rates, expose a resolver). Restructure Inputs to carry contracts and the resolved profile; keep property_price, drawdown_date, property_growth_pa, total_term_months, tax/output blocks as loan-level. |
| src/engine/monthly.py | build_rate_lookup moves from rate_blocks (month numbers) to a contracts-derived month-to-rate lookup (convert each contract start_date/end_date to month offsets from drawdown_date). month_tables: recurring_by_month moves from overpay_rules (start_month) to standing_overpayment date windows. default_payment_date (currently clamp_day on repayment_day_default) is the payment-date-convention hook: day_clamp today; routed through the profile convention at the re-baseline step. derive_modelling_end unchanged. |
| src/engine/simulate.py | payment_for_month (uses rate_blocks.start_month, known_first_payment, strategy_at_refix, pmt) becomes contract-driven: the contract instalment where stated, the PMT fallback where null, a refix handled as a new Contract boundary. _ladder_amount_for_month (reads contractual_ladder) is replaced by per-Contract instalment. lumps_by_date (from lump_sums) unchanged. |
| src/engine/reconcile.py | No change. Reads only reconcile_ok_abs_eur; touches no rate, cap, or payment-date construct. |
| src/engine/report.py | compute_portal_style_metrics calls build_rate_lookup(inputs.rate_blocks) and reads inputs.day_count; repoint to the contracts-derived rate lookup and take day_count from the profile. Formatting code unchanged. |
| src/engine/__main__.py | Low touch. Reads inputs.property_price, property_growth_pa, drawdown_date (stay loan-level), output, tax, and reconcile.snapshots; consumes monthly/events columns whose names do not change. Update only the field access if Inputs field names move. |
| src/metrics.py | Low touch. compute_baseline_kpis reads monthly columns (contractual, overpayment, difference, lump, total_paid, interest_used, principal_paid, model_eom_balance, payment_date, ym) and inputs.modelling.as_of_date; no rate/cap construct. Safe as long as the monthly column vocabulary is preserved. |
| tools/portfolio.py | Low touch. load_inputs, compute_baseline_kpis, reads inputs.output.csv_subdir and reconcile.snapshots, consumes the locked monthly/summary columns. Safe if column names and output.csv_subdir are preserved. |
| tools/baseline.py | Real change. _sanitize_for_strict_baseline currently strips overpay_rules, lump_sums, and bank.merge_standing_extra_into_payment. Update it to strip the new contract-level standing_overpayment (per Contract) and lump_sums so the strict baseline stays contract-only under the new schema. This drives baseline_monthly.csv, so it must be exactly equivalent. |
| data_sample/property_*/inputs.sample.yaml | Migrate to the Loan + contracts + lender schema. Add data/lenders/sample_lender.yaml. The Somerton (B) rewrite from the real S2 terms is Phase 10 (S6 authors the data). |
| data_sample/portfolio.yaml | Minimal. Lender lives in each property inputs.yaml loan block, not here. Add a top-level lenders-folder path only if the loader needs it. |
| .gitignore | Add data/lenders/*.local.yaml so the private profile is never committed. |
| tests/fixtures/golden/* | schedule_monthly.csv, baseline_monthly.csv, portfolio_summary.csv stay byte-identical through the refactor step; re-baselined only at the Modified Following step (B4). |
| tests/* | Update every test that builds Inputs or references the retired constructs: test_run_engine_characterization.py, test_attribution_characterization.py, test_attribution_split.py, test_golden_master.py, test_merge_extra_guard.py, test_metrics_baseline.py, test_valuation_blocks.py, test_meta_passthrough.py, test_output_layout_characterization.py, test_output_structure.py, test_portfolio_rollup.py, test_reconcile_ok.py, test_smoke.py, and conftest.py fixtures. Add profile-loader and rule-resolution tests. |

## B3. Migration: refactor-before-re-data

Ordering, so each step is independently provable:

1. Introduce the profile loader and the contracts schema alongside the existing
   fields (additive parse). No consumer switched yet. Green.
2. Repoint the rate lookup (monthly.py, report.py) and the instalment logic
   (simulate.py) from rate_blocks / known_first_payment / contractual_ladder to
   the contracts-derived equivalents. Convert the sample inputs.yaml to the new
   schema, encoding the same rates, instalments, and windows. Keep
   payment_date_convention resolving to day_clamp (today's behaviour). The
   golden must stay byte-identical here.
3. Retire the dead scalar overpayment_cap_pct and move the cap + breakage into
   the profile as data. Neither is consumed for an output figure, so still
   byte-identical.
4. Update tools/baseline.py sanitiser to the new schema and confirm
   baseline_monthly.csv is unchanged.

Invariant for steps 1 to 4: the Gandon golden output does not move by a cent.
This is the refactor half.

## B4. Golden re-baseline and the byte-identical invariant

- What stays identical through B3: rate resolution per month, projected payment
  dates (still day_clamp), every conserved quantity, and the full
  monthly/reconcile/summary column set.
- The one deliberate behaviour change is the payment-date convention: switching
  the projection path from day_clamp to modified_following (LP7, S3 decision d)
  moves projected future payment dates, which appear in the Gandon golden (the
  schedule projects to 2059). This is the re-data half: flip the engine to
  honour the profile convention, add the Irish business-day calendar, then
  re-baseline schedule_monthly.csv (and any dependent fixture) in a single
  reviewed step. Actual posted dates from the bank feed are never overridden.
- Ship: Phase 10 v2.0.0 (rollback v1.9.0). The re-baseline lands inside Phase
  10, not in this analysis phase.

## B5. Carried forward and deferred to S6

- Carried forward from S1 to S4: all Section A locks, plus the S3 decisions
  (cap, breakage type, Modified Following, ACT/365, per-account payment day).
- Deferred to S6: the anonymisation mapping (real to sample), the committed
  sample profile values, the private boi.local.yaml real values, the Somerton
  inputs.yaml rewrite, and the confirmed Phase 10 session breakdown.


---

# Section C (P9/S6): Anonymisation mapping and Phase 10 session plan

> Authored in P9/S6. Fulfils the anonymisation-mapping and Phase-10-plan items
> deferred in A10 and B5. This section is committed to the public repo, so it
> carries anonymisation policy and rules only, never a real figure, never a real
> date or name, and never a reversible transform. The real-to-sample value
> correspondence, where any is recorded, lives only on the private Real Property
> Data page, off-repo.

## C0. Scope

S6 produces two tracks of data plus this mapping: the committed anonymised
sample files (public) and the private real-data blocks (off-repo). The engine
does not consume any of it until Phase 10 wires the new schema; see C7.

## C1. Two-track data model

- Committed sample track (public repo): data_sample/<property>/inputs.yaml,
  data_sample/lenders/sample_lender.yaml, data_sample/portfolio.yaml.
  Fictitious values, safe to publish, internally consistent so the golden
  master can lock them.
- Private real track (off-repo): the real inputs.yaml per property and the real
  boi lender profile (with R%/R1%), mirrored on the private Real Property Data
  page and pasted into git-ignored local files. Never committed.

The sample and real files share one thing only: the schema shape. Everything
else differs.

## C2. What is scrubbed vs what stays

Scrubbed (never in a committed file):

- Money amounts: drawdown, principal, instalment, property value, overpayment
  amounts, breakage figures.
- Absolute dates: drawdown date, first payment, refix / fixed-period-end dates,
  maturity.
- Identifiers: account numbers, addresses, property names / codenames, lender
  customer references.
- Real market rates: the R%/R1% money-market series (private boi profile only).
- Tenancy / tenant personal data.

Kept (safe, structural, or published product rules):

- Field names and schema shape.
- Rate types (fixed / variable / tracker) and the count and ordering of
  contracts.
- Conventions: ACT/365 day-count, Modified Following, and the cap basis
  (percent_of_monthly_repayment + EUR 65 floor). These are published product
  rules, not personal data.
- The presence and shape of features: a payment break, a standing overpayment
  window, a refix boundary, a follow_on.
- Relative timing: term length, the gap between drawdown and first payment,
  fixed-period length, and the position of a refix within the loan.

## C3. Anonymisation rules

1. Replace, do not scale. Committed sample amounts are freshly invented round
   numbers of a similar order of magnitude, not the real figures multiplied by a
   factor or shifted by an offset. A linear scale or offset is reversible if any
   single real value ever leaks; clean replacement is not.
2. Preserve structure and relative timing, not absolute values. Keep the same
   number of contracts, the same feature shape (break / overpay / refix), and
   the same durations (term, drawdown-to-first-payment gap, fixed-period
   length). Set sample dates to clean fictitious anchors that reproduce those
   durations.
3. No published transform. This section never states the exact real-to-sample
   correspondence. If a correspondence is recorded at all, it lives only on the
   private page.
4. Internally consistent. Each sample loan must load, run, and reconcile on its
   own, so the golden master can lock it. A sample is a valid fictitious loan,
   not a redacted real one.
5. Product rules are not secrets. The 10% / EUR 65 cap, ACT/365, Modified
   Following, the 0.3% green discount, and similar published thresholds may
   appear in committed samples and docs.

## C4. Sample file set (committed, authored in S6)

- data_sample/lenders/sample_lender.yaml: the generic profile from
  docs/lender_profile.md LP9 (placeholder cap / breakage, empty money-market
  series).
- data_sample/property_a/inputs.yaml: investment, one contract, a payment break,
  a standing overpayment; the Property A shape with invented figures.
- data_sample/property_b/inputs.yaml: primary, two contracts across a refix; the
  Property B shape with invented figures.
- data_sample/property_c/inputs.yaml: owned_outright, valuation only, no loan or
  contracts.
- data_sample/portfolio.yaml: the roster (Property A enabled, B and C disabled),
  unchanged in intent from today so the golden master stays green.

These are Phase 10 inputs: authored now, swapped into the engine path in Phase
10 (C7).

## C5. Private real-data blocks (off-repo)

Authored as copy-paste blocks under the private Real Property Data page and its
three property subpages, in the new shape:

- Property A: real loan + one contract (payment break, a formalised part-capital
  increase), real dates and amounts.
- Property B: real loan + two contracts (origin + refix) with a standing-overpay
  window on the first.
- Property C: valuation-only, no loan.
- Real boi profile: real cap / breakage plus the private R%/R1% money-market
  series and a plain-English sourcing note.

Staging rule: paste these into a private, non-live file (for example
inputs.v2.yaml) or keep them on the private page. Do not overwrite the live
old-shape inputs.yaml until the Phase 10 cutover, or today's runs break (C7).

## C6. Proposed Phase 10 session breakdown (confirm before scoping)

Derived from the B2 cascade map and the B3 migration order. Proposed, to confirm
with Ali at Phase 10 S0:

- P10/S0 setup: scope, rollback tag v1.9.0, branch phase10/contract-schema.
- P10/S1: profile loader + contracts schema in schema.py, additive parse, no
  consumer switched yet. Green.
- P10/S2: repoint the rate lookup (monthly.py, report.py) and the instalment
  logic (simulate.py) to contracts; convert the sample inputs.yaml; keep
  day_clamp. Byte-identical golden.
- P10/S3: retire the scalar overpayment_cap_pct; move cap + breakage into the
  profile as data; update tools/baseline.py sanitiser. Byte-identical.
- P10/S4: switch the payment-date convention to Modified Following + the Irish
  business-day calendar; re-baseline the golden (the one deliberate move).
- P10/S5: consume the real property rewrites, update docs + README, ship v2.0.0.

## C7. Cutover note (why the new data is inert until Phase 10)

Today's engine reads the old schema. The new-shape sample and real files authored
in S6 cannot be run until Phase 10 rewires the loader and the consumers. So:
author now, cut over in Phase 10. Never replace a live old-shape inputs.yaml with
a new-shape file before the Phase 10 engine change lands.