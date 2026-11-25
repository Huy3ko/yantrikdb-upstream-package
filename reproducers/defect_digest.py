#!/usr/bin/env python3
"""Reproducer: what_changed_since() widerspricht sich selbst.

Erwartet: ein Record, der von einem spaeteren Record abgeloest wurde, wird im
Change-Feed nicht als 'active' gemeldet.
Beobachtet: new_records[i].current_status == 'active' und superseded_by == None,
waehrend derselbe Aufruf in status_transitions den Uebergang active->superseded
meldet. Ursache im Code: engine/digest.rs setzt beide Felder hart auf
Default::default() / None, obwohl die Kanten im selben Lauf gelesen werden.

Exit 0 = Defekt reproduziert.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from probe import fresh, open_db  # noqa: E402

db = open_db(fresh("defect-digest"))
old = db.record("Aussage A zur Abloesung.", importance=0.9, half_life=1e9)
new = db.record("Aussage B loest Aussage A ab.", importance=0.9, half_life=1e9)
db.link(new, old, "supersedes")

chg = db.what_changed_since(0)
if isinstance(chg, str):
    chg = json.loads(chg)

entry = next(r for r in chg["new_records"] if r["rid"] == old)
trans = [t for t in chg["status_transitions"] if t["rid"] == old]

print(json.dumps({
    "record": old[-6:],
    "feed_current_status": entry["current_status"],
    "feed_superseded_by": entry["superseded_by"],
    "feed_transition": [(t["from"], t["to"], t["by_rid"][-6:]) for t in trans],
    "lebender_recall_enthaelt_den_abgeloesten": any(
        h["rid"] == old for h in db.recall(query="Aussage Abloesung", top_k=10)),
}, ensure_ascii=False, indent=2), flush=True)

defekt = (entry["current_status"] == "active"
          and entry["superseded_by"] is None
          and bool(trans))
db.close()
print("DEFECT REPRODUCED" if defekt else "not reproduced", flush=True)
sys.exit(0 if defekt else 1)
