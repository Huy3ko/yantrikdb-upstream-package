# Expose the native belief lifecycle to Python

> **Depends on PR #313** (`fix/belief-evidence-series`, three commits).
> This patch applies on top of that branch, not on `main`: the binding reads
> `EvidenceEntry::history` and `::paths` and `BeliefPayload::undecayed_log_odds`,
> which #313 introduces. Applying it to `main` textually works and does not
> compile — that is the dependency, not a defect of the patch.

## Symptom

The engine runs the whole belief loop: create, evidence with a stable
observation identity, re-assessment, propagation across epistemic edges,
explain, time-based decay. The Python bindings exposed **none** of it —
measured: no attribute containing `belief` on `YantrikDB`. An agent driving a
memory through Python could assert facts and recall them, but could not form,
inspect or revise a belief.

## Change

A thin mapping (`py_engine/belief_api.rs`), not a second implementation — every
semantic stays in `yantrikdb_core`:

```
belief_create                  create (id from the persisted NodeIdAllocator)
belief_get                     state + trail (history per observation, paths)
belief_query                   native BeliefPattern query
belief_inventory               landscape by domain / confidence / volatility
belief_assert_evidence         one observation, stable identity
belief_assert_evidence_batch   several, one persistence pass
belief_explain                 provenance: supporting/contradicting, trend
belief_relate / belief_edges   epistemic edges
belief_confirm / belief_refute direct statement
belief_revise                  decay, with an explicit clock
belief_contradictions          contradiction scan
```

Two small native additions were necessary:

- **`create_belief`** — node creation belongs where the persisted
  `NodeIdAllocator` lives; a caller cannot mint an id that survives a restart.
- **`revise_all_beliefs_at(now, ..)`** — the existing pass with the clock
  supplied; `revise_all_beliefs` now delegates with `now()`. Without it a
  time-based measurement is not deterministic (two runs a microsecond apart are
  two instants).

## Verification

Built on the branch of #313, not on `main`:

```
cargo build -p yantrikdb-python          # ok
PYTHONPATH=<arm> python3 -c "..."        # 13 belief_* methods present
```

Lifecycle smoke: create → assert evidence (p = 0.858149, trail = 1) → assert
the **same** observation again → probability unchanged, trail still 1 (the
identity from #313 is what makes this hold). Library suite on the series:
**2,307 passed, 0 failed**.

## Not included

- No MCP server and no Hermes provider wiring: the binding is the prerequisite,
  not the integration.
- No new belief semantics — no supersession edge, no as-of query. Those are
  design items, not bindings.
- `belief_get` returns the trail including each observation's earlier
  assessments, but propagated entries still carry a node id in their `source`
  field rather than a readable origin; the `observation_id` prefix
  (`prop|<origin>`) is what makes them traceable. Not fixed here.
