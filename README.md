# YantrikDB — upstream package (2026-11-26)

Patches, evidence and a design note from an investigation of the cognitive
memory engine. Everything here is prepared against `yantrikos/yantrikdb`
`main` = `bee011a` (24 Nov 2026) and is offered for review, not for blind
merging.

Three of these went in as separate pull requests before this package existed;
they are listed here with their status so nothing is duplicated.

## Status

| # | Subject | Status |
|---|---|---|
| 0001 | conflict detection: shared subject **and** shared frame | PR #312 |
| 0002 | redundancy scan gated behind `run_conflict_scan` | PR #311 |
| 0004–0006 | belief evidence: identity, one voice, time-based decay (3 commits) | PR #313 |
| 0008 | `what_changed_since` reports chain status, not a default | PR #310 |
| 0003 | Hermes plugin: personality telemetry not derived as persona | **closed — already fixed upstream** (`run_personality=False` is the default and the only call site) |
| 0007 | native belief lifecycle over Python | **prepared, not submitted** — depends on **#313**; branch `fix/belief-python-api`, commit `bd0edc0` |
| 0009 | evidence provenance in both directions | **experimental**, depends on 0007; open design decision (record vs. observation identity) |
| A, C | supersedes/derived-from for beliefs, belief as-of | **design only**, no code |

`patches/` holds one patch per candidate. `pr-texts/` holds the text submitted
(or to be submitted) for each. `reproducers/` holds the two standalone scripts
for the digest defect: `defect_digest.py` (red before the patch, green after)
and `probe.py` (the capability matrix used to find it).

## The four submissions

- **#310** `what_changed_since` contradicted itself: a record created and
  superseded after `since` appeared as `active` in `new_records` and as
  `active → superseded` in `status_transitions` of the same answer. Fixed by
  filling the two fields from the transition rows already fetched. Six
  regression tests, 2,283 passed / 0 failed.
- **#311** `think()` ran the O(n²) pairwise redundancy scan even with
  `run_conflict_scan: false` — ~289 M pairs on a 24k-record store, and it
  persists conflicts while doing it. 2,279 / 0.
- **#312** the substitution check treated a category hit as a contradiction
  (45 of 45 open `preference` conflicts were false positives). Two gates now:
  shared context and a **frame** overlap of the sentences with the values
  removed. The frame check replaces a positional "the next two tokens must
  match", which silently dropped reordered clauses and clause-final values.
  40 tests, 2,286 / 0.
- **#313** three commits in one PR, because two of them do not build alone:
  stable `observation_id` (repeated evidence revised instead of voted twice,
  0.9 → 1.8 measured before), propagation keeping one voice across paths
  (0.5 → 1.0 before), and decay computed from an anchor instead of the running
  value. 2,307 / 0.

## The design note

`ARCHITECTURE.md` describes the three open pieces — provenance in both
directions, supersession as a belief-level edge, and belief as-of — together
with the limits that must survive: a retracted source is not a refutation, a
superseded belief keeps its evidence, and an as-of answer is content and
currency, never today's ranking pretending to be yesterday's.

It ends with three questions we could not answer alone; they are the reason this
is a package and not four more patches.

## Reproducing

```
git clone https://github.com/yantrikos/yantrikdb && cd yantrikdb
git checkout bee011a
git apply patches/0008-changed-since-chain-status.patch
cargo test -p yantrikdb --lib          # expect 2,283 passed
```

Series candidates apply in order and are marked as such in their PR text:

```
git apply patches/0004-evidence-identity.patch
git apply patches/0005-propagation-origin.patch
git apply patches/0006-staleness-decay.patch
```

For the digest defect, `reproducers/defect_digest.py` runs against a wheel built
from the tree: it prints `DEFEKT REPRODUZIERT` before the patch and
`nicht reproduziert` after.

## What is not here

No memory contents, no database dumps, no deployment details. Measured numbers
are from synthetic stores built by the tests, except where a patch text says
"production store" — those are counts only, with no records.

## 0010 — substitution categories indexed (perf)

`patches/0010-substitution-index.patch` · `pr-texts/PR-0010.md` · `reproducers/substitution_index_bench.rs`

`check_redundancy_in_namespace` issued one JOIN per token pair of every
near-duplicate memory pair. The table (8 categories, 80 members) is now loaded
once per namespace and the same predicate is answered in memory.

Same corpus, same binary, built from `3d52394` and from the branch:
parent `> 300 s` (timeout), change `1.242 s`, same 40 triggers. On a
24,268-record store: 116 s (unfinished) → 0.531 s, `think()` >25 min → 2.01 s.

Nothing is gated or disabled. PR: https://github.com/yantrikos/yantrikdb/pull/315
Note: #312 must rebase onto this and move its subject/frame predicate into
`check_substitution_pair_in_index`, or it edits a function the redundancy path
no longer calls.
