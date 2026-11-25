# `think()` runs the pairwise redundancy scan even with `run_conflict_scan: false`

## Symptom

`ThinkConfig::run_conflict_scan` is meant to switch the conflict scan off. With
it set to `false`, `think()` still runs `check_redundancy`, which compares every
active memory against every other one (pairwise cosine) **and persists learned
substitution conflicts**.

On a store with 24,074 active records that is roughly 289 million pairs. In a
phase-by-phase measurement (`examples/think_phases.rs`), that single check
dominated the cycle: `think()` with all phases off went from **> 14 min to 0.8 s**
once the check was gated.

## Reproduction

```
cargo run --example think_phases -- <store>     # before: one phase at >14 min
```

Unit-level (`engine/tests/redundancy_gate.rs`):

- `conflict_scan_off_persists_no_redundancy_conflict` — with the flag off, no
  conflict rows are written (**fails without the fix**)
- `conflict_scan_on_persists_the_same_conflict` — with the flag on, the row is
  written (unchanged behaviour)

## Root cause

`engine/cognition.rs`, Phase 1 of `think()`:

```rust
all_triggers.extend(crate::triggers::check_redundancy(
    self,
    config.redundancy_sim_threshold,
)?);
```

No flag check. Every other scan in that block is either cheap or independent of
the conflict flag; this one is the expensive, conflict-persisting one.

## Change

```rust
if config.run_conflict_scan {
    all_triggers.extend(crate::triggers::check_redundancy(
        self,
        config.redundancy_sim_threshold,
    )?);
}
```

One call site, no behaviour change when the flag is on.

## Related issues — same function, different mechanisms

These are **not** duplicates; each fixes a different defect in the same area.
This patch does not touch any of them:

- **#259 / #263** — `check_redundancy` ignored its `sim_threshold` argument
  (hardcoded 0.85). Fixed separately; that is about the *threshold*, this is
  about *when the scan runs at all*.
- **#256** — redundancy pairs crossed namespace boundaries. Fixed separately;
  that is about *which pairs*, this is about *whether to scan*.
- **#242** — `find_clusters()` had no namespace check (cross-tenant merging).
  A different entry point.
- **#142** — the `conflicts_found` counter undercounted because Phase 1 writes
  conflicts too. Already addressed in the count; not a scheduling question.

## Tests

`engine/tests/redundancy_gate.rs` (2 cases) plus the phase example. Counter-run
at the decision point (`if config.run_conflict_scan` -> `if true`): the
`_off_` test fails, its `_on_` twin stays green. Full library suite against
`main` = `bee011a`: **2,279 passed, 0 failed**.

## Not included

- **`check_redundancy` itself stays O(n²).** Turning it on still costs the
  pairwise scan. A blocking/ANN approach is a separate proposal with its own
  measurement.
- **Existing conflicts** from earlier runs are left alone; this patch creates
  and deletes none.
- No change to the default value of `run_conflict_scan`.
