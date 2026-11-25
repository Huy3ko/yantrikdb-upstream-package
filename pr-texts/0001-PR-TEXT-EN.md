# Conflict detection treats a substitution-category hit as a contradiction

## Symptom

The substitution branch of the trigger scan reports two documents as one claim
with two values whenever both name a value from the same exclusive category —
a model name in one, a provider in another, a version in a third. On a store
with ~97k records, **45 of 45** open `preference` conflicts were false
positives of this rule.

## Reproduction

```
cargo test -p yantrikdb --lib triggers::tests
```

`same_category_different_subject_is_not_a_conflict` — both texts name a member
of the same category, the subjects differ; the old rule returns a conflict
(**red without the fix**).

## Root cause

`cognition/triggers.rs`, `check_substitution_category_pair`: the diff tokens of
the two texts are looked up in `substitution_members`, and a hit in a shared
category was returned as a contradiction. Nothing asked whether the two
documents talk about the same thing.

## Change

Two gates, both computed on prose only (code fences and inline spans are
stripped first — `--data` is not a claim about a data layer):

1. **shared context** — the neighbourhoods of the two substituted tokens must
   share at least `MIN_SHARED_CONTEXT` content words;
2. **shared frame** — the content words that remain after removing the two
   substituted values must overlap with at least 0.7 Jaccard.

## Why the frame check, and not "the next token must match"

The first version of this patch compared the exact tokens *after* the value.
That is positional and drops real contradictions in two common shapes:

- **reordered clause**: "the index runs on postgresql" / "on mysql runs the index"
- **value at the end**: "… we use postgresql." / "… we use mysql."

Both are found and fixed here; both are regression tests. Frame overlap scores
1.0 for them, while the intended hard negative — "postgresql as the index" /
"mysql for the tests", same subject and verb, different object — scores 0.44.
The threshold sits between the two.

## Tests

`cognition::triggers::tests`: 40 cases, including a table-driven matrix that
asserts **zero false positives and zero false negatives** over the pairs that
motivated the rule. Full suite against `main` = `bee011a`: **2,286 passed,
0 failed**.

## Not included

- Conflicts that were already stored by earlier runs are not re-evaluated or
  closed; this patch prevents new ones.
- A temporal qualifier ("both were true at different times") is still not part
  of the rule — that needs a schema decision.
- The frame check is lexical, not a parse. Sentences that assert the same thing
  with a different noun phrase for the object will still be treated as
  different claims; erring that way keeps the rule from suppressing real
  conflicts.
