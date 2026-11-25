# Knowledge history: separating experience, validity and confidence

A design note accompanying the patches in `patches/`. It describes what the
engine already does, what three changes would add, and which questions are open.
**Nothing here is proposed as a finished design.**

## The problem

The engine keeps three things that look similar and are not:

- **what happened** — records, with event time and transaction time;
- **what is currently valid** — whether a statement has been replaced;
- **how strongly it is believed** — `log_odds` and its evidence trail.

Today these are separable for records (`recall_as_of`, `record_revisions`,
`record_links`) and only partly separable for beliefs. The consequence shows up
in a practical question an agent asks itself: *what did I believe three weeks
ago, and why did that change?* The evidence trail answers "why" for the current
state; nothing answers it for a past one.

## Three pieces

### 1. Evidence provenance in both directions (`0009`)

An evidence entry names a free-text `source` and an `observation_id`. It does not
name the record the observation rested on, so

> belief → evidence → the record that carried it

ends one link short, and the reverse question — *this record is being retracted,
which beliefs depend on it?* — has no index at all. (`#88` describes the same gap
for claims and patterns.)

The patch adds a normalised table, one row per `(belief, observation, record)`,
carrying the record's revision **at citation time**. Properties it keeps:

- citing three records for one observation changes what can be audited, not what
  is believed (`log_odds` is bit-identical);
- a later correction bumps the record and leaves the citation alone; the read
  path reports `revision_drift` — review needed, not refuted;
- a retracted source stays traceable and does not lower confidence;
- citations and the evidence entry commit in one transaction.

**Open decision.** The patch currently folds a re-assertion into the existing
observation when it cites a record the belief already cites. That is right for a
corrected typo and wrong in general: **one record can carry several independent
observations**. Three ways out, none chosen:

1. a span (`span_start`/`span_end`, as `claims` already has) as part of the
   citation identity — most precise, requires the caller to know the span;
2. an explicit `independent` flag — cheap, moves the decision to the caller;
3. leave it and document — what the patch does today.

### 2. `Supersedes` / `DerivedFrom` for cognitive nodes (`A`, not built yet)

The belief graph has 18 edge kinds and none of them means "replaced by".
`contradicts` is not a substitute: a statement that was correct for a narrower
scope is not refuted by the statement that follows it, and asserting otherwise
puts a false claim into the graph.

Rules the edge would have to carry:

- supersession changes **current validity / selection**, not evidence and not
  confidence;
- `derived_from` records where an insight came from — provenance, not extra
  evidence;
- neither edge participates in automatic confidence propagation (the existing
  `is_epistemic()` already excludes everything except `supports`/`contradicts`);
- a superseded belief keeps its full evidence trail and its confidence;
- self-edges, cycles, multiple successors and transitive chains are rejected or
  resolved deterministically.

The record layer already implements this shape (`record_links` with
`selection_state`), including a single-selected-successor invariant and a cycle
check. A belief-level edge should reuse those rules rather than invent new ones.

### 3. Belief as-of (`C`, not built)

`recall_as_of` reconstructs record content. For beliefs the question is what is
*actually* reconstructible:

| component | reconstructible from | limit |
|---|---|---|
| evidence trail at `t` | entry timestamps | yes |
| undecayed `log_odds` at `t` | replay of the trail | exact (measured: 0.878681 stored = recomputed) |
| decayed `log_odds` at `t` | anchor + `at` | only if the decay function is known and the pass is a pure function (it is, after `0006`) |
| propagation effects at `t` | `paths` per entry | yes, aggregate only |
| ceiling clamps | not recorded | **no** — a clamp leaves no trace |
| what the belief was *about* (proposition text) | payload | yes, if no rename happened |

The honest deliverable is a function that returns "these parts are exact, these
are approximate, this is unavailable" — not a number that looks like a past
probability.

## What not to do

- **Do not answer historical questions with today's ranking.** Similarity cannot
  be un-embedded; an as-of result is content and currency, not the order a query
  would have produced.
- **Do not treat a retraction as a refutation.** It removes evidence; whether a
  belief still holds is a separate judgement.
- **Do not store parallel lists** of rids and revision numbers in the payload —
  they drift; a row per citation cannot.

## Questions for the discussion

1. Is `Supersedes` a belief-level edge, or should a superseded belief be modelled
   as a *new* belief derived from the old one (leaving the old one untouched)?
2. For provenance: span as identity, or an explicit independence flag?
3. For as-of: is a component-wise "exact / approximate / unavailable" report
   useful to you, or would a simpler "replay to timestamp, refuse if a clamp
   intervened" be preferable?
