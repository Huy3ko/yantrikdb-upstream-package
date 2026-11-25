# `what_changed_since()` reports a default instead of the record's chain status

## Symptom

A record that was created **and** superseded after `since` appears twice in the
same answer, with contradictory labels:

```
new_records[0].rid            = <A>
new_records[0].current_status = "active"
new_records[0].superseded_by  = null
status_transitions[0].rid     = <A>
status_transitions[0].from/to = active -> superseded
status_transitions[0].by_rid  = <B>
```

A host that reads `new_records` — the shorter view, and the obvious one — learns
the opposite of what happened: a replaced statement looks current.

## Reproduction (minimal, deterministic)

```python
db  = YantrikDB(":memory:", 8)          # any embedder
old = db.record("A"); new = db.record("B")
db.link(new, old, "supersedes")
chg = db.what_changed_since(0)
chg["new_records"][0]["current_status"]   # -> "active"
chg["status_transitions"][0]["to"]        # -> "superseded"
```

Rust equivalent in `engine/tests/digest_changes.rs`:
`new_record_superseded_after_since_reports_its_chain_status`.

## Root cause

`engine/digest.rs`, in `what_changed_since`:

```rust
current_status: Default::default(),
superseded_by: None,
disputed: false,
```

The function reads the supersedes edges into `status_transitions` in the same
pass, so the information is already there. The fields are documented as
chain-derived ("Active unless the record has a selected inbound supersedes
edge"), and `session_digest` — same file, ~230 lines above — already fills them
that way with a per-row `SELECT source_rid FROM record_links … LIMIT 1`.

## Change

The successor map is built from the transition rows **already fetched**; no
second query is added. An edge that supersedes a record created after `since`
is itself committed after `since` (a link cannot precede its target), so the map
is complete for `new_records`.

```rust
let mut successor_of: HashMap<String, String> = HashMap::with_capacity(tr_rows.len());
for (target, source, _at) in &tr_rows {
    successor_of.insert(target.clone(), source.clone());
}
// ...
let superseded_by = successor_of.get(&rid).cloned();
let current_status = if superseded_by.is_some() {
    RecordStatus::Superseded
} else {
    RecordStatus::Active
};
```

No signature change, no new column, no migration — the fields existed.

## Tests (`engine/tests/digest_changes.rs`, 6 cases)

1. the defect: entry and transition of one answer must agree (red without the fix)
2. an undisturbed record stays `Active` and names no successor
3. the successor is not superseded by its own outbound edge (red without the fix)
4. a second successor is never a second *active* edge (`gate_supersedes` keeps one)
5. legacy data with two selected successors resolves deterministically — two
   calls return the same successor, and the newest committed edge wins
6. imported records: a backdated `created_at` keeps a record out of
   `new_records`, while a supersession committed now is still reported as a
   transition — the two lists answer different questions

Counter-run: `digest.rs` stashed, same tree -> 2 of the first 3 fail; fix
restored -> 3 of 3 pass. Full library suite: **2,283 passed, 0 failed**.

## Not included

- **`disputed` stays `false`.** `session_digest` fills it from an OPEN-conflict
  query, but `ChangesSince` gains no conflicts section here, and whether the flag
  means "as-of `since`" or "now" is a product decision. Named so this patch is
  not read as covering it.
- **Retractions** still produce no transition: `record_links` keeps no retraction
  timestamp (the function's doc comment says so).
- No change to `session_digest`, the status read policy, or edge selection.

## Applicability

Applies cleanly to `main` at `bee011a` (`patch -p1 --dry-run`: 3 files, all
hunks OK). Against `v0.23.6` only the `engine/tests/mod.rs` hunk conflicts,
because `main` added `mod drafted_facts;` in that list.
