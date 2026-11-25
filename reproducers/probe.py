#!/usr/bin/env python3
"""Wissenshistorie — reproduzierbare Probe gegen eingefrorene Engine-Staende.

Kein produktiver Store, keine Live-Aenderung: jede Probe oeffnet eine eigene
Datei-DB unter ./db/ und schliesst sie wieder.

Aufruf:
    PYTHONPATH=<pylib> python3 probe.py <build-label>

Ausgabe: eine JSON-Zeile je Pruefung (flush), damit ein Timeout keine Belege frisst.
"""
import hashlib
import json
import os
import pathlib
import re
import shutil
import sqlite3
import sys
import time

DIM = 32
HERE = pathlib.Path(__file__).resolve().parent
BUILD = sys.argv[1] if len(sys.argv) > 1 else "unbekannt"
DBDIR = HERE / "db"
DBDIR.mkdir(exist_ok=True)


def say(kind, name, **kw):
    rec = {"build": BUILD, "check": name, "kind": kind, **kw}
    print(json.dumps(rec, ensure_ascii=False, default=str), flush=True)


class HashEmbedder:
    """Deterministischer Bag-of-Words-Embedder. Gleiche Eingabe -> gleicher Vektor,
    in beiden Builds identisch. Kein Modell-Download, keine Netzabhaengigkeit."""

    def encode(self, text):
        v = [0.0] * DIM
        for tok in re.findall(r"\w+", text.lower()):
            h = hashlib.sha256(tok.encode()).digest()
            for i in range(DIM // 2):
                v[h[i] % DIM] += 1.0 if h[16 + i] % 2 else -1.0
        norm = sum(x * x for x in v) ** 0.5
        return [x / norm for x in v] if norm else v


def fresh(name):
    p = DBDIR / f"{BUILD}-{name}.db"
    for suf in ("", "-wal", "-shm"):
        f = pathlib.Path(str(p) + suf)
        if f.exists():
            f.unlink()
    return str(p)


def open_db(path):
    from yantrikdb import YantrikDB

    return YantrikDB(path, DIM, embedder=HashEmbedder(), allow_unverified_embedder=True)


def texts(hits):
    return [h.get("text") for h in hits]


def ids(hits):
    return [h.get("rid") for h in hits]


# ─────────────────────────────────────────────────────────────────────
# 1. Revisionshistorie + As-of (record-level, bitemporal)
# ─────────────────────────────────────────────────────────────────────
def t_revision_asof():
    now = time.time()
    t0, t1 = now - 3 * 3600, now - 2 * 3600
    path = fresh("revision")
    db = open_db(path)
    old = "Der Regelkreis speichert den Grundwert und schreibt ihn nicht zurueck."
    r1 = db.record(old, importance=0.9, half_life=1e9, domain="architektur",
                   metadata={"stand": "v1"}, created_at=t0)
    r2 = db.record("Zweiter, unbeteiligter Eintrag ueber den Zeitgeber.",
                   importance=0.5, half_life=1e9, created_at=t0 + 1)
    say("info", "rev/rids", old_rid=r1, other_rid=r2)

    corr = db.correct(r1, reason="Praezisierung nach Messung: Grundwert wird gespeichert, Rueckschreiben ist der Fehler",
                      new_text="Korrektur: Der Grundwert MUSS gespeichert werden; das Rueckschreiben in den Ausgangswert ist der Fehler.",
                      metadata_merge={"stand": "v2"})
    say("info", "rev/correct", result=corr)

    hist = db.history(r1)
    say("check", "rev/history_after_correct",
        revision_count=len(hist),
        prior_text=hist[0]["prior_text"] if hist else None,
        reason=hist[0].get("reason") if hist else None,
        keys=sorted(hist[0].keys()) if hist else [],
        pass_=bool(hist) and hist[0]["prior_text"] == old)

    # As-of VOR der Korrektur: alter Text muss zurueckkommen
    before = db.recall_as_of(t1, query=old, top_k=5)
    say("check", "rev/as_of_before_correction",
        hits=texts(before), why=[h.get("why_retrieved") for h in before],
        pass_=any("Grundwert" in (h.get("text") or "") and "MUSS" not in (h.get("text") or "")
                  for h in before))

    after = db.recall_as_of(now + 60, query=old, top_k=5)
    say("check", "rev/as_of_after_correction",
        hits=texts(after),
        pass_=any("MUSS gespeichert" in (h.get("text") or "") for h in after))

    db.close()

    # Neustart: Historie muss aus der Datei rekonstruierbar sein
    db2 = open_db(path)
    hist2 = db2.history(r1)
    rec = db2.get(r1)
    say("check", "rev/history_survives_reopen",
        revision_count=len(hist2),
        prior_text=hist2[0]["prior_text"] if hist2 else None,
        current_text=(rec or {}).get("text"),
        pass_=len(hist2) == len(hist) and hist2 and hist2[0]["prior_text"] == old)
    before2 = db2.recall_as_of(t1, query=old, top_k=5)
    say("check", "rev/as_of_survives_reopen",
        hits=texts(before2),
        pass_=any("Grundwert" in (h.get("text") or "") and "MUSS" not in (h.get("text") or "")
                  for h in before2))
    db2.close()
    return path


# ─────────────────────────────────────────────────────────────────────
# 2. Record Links: supersedes / derived_from
# ─────────────────────────────────────────────────────────────────────
def t_links():
    now = time.time()
    t0, t1 = now - 3 * 3600, now - 2 * 3600
    path = fresh("links")
    db = open_db(path)
    old = db.record("Aussage A: Der Abruf liefert die alte Fassung des Regelsatzes.",
                    importance=0.9, half_life=1e9, created_at=t0)
    new = db.record("Aussage B: Der Abruf liefert die neue Fassung des Regelsatzes.",
                    importance=0.9, half_life=1e9, created_at=t0 + 60)
    lid = db.link(new, old, "supersedes")
    say("info", "links/created", link_id=lid, old=old, new=new)

    out = db.linked_records(new, direction="outbound")
    agree = "not linked (expected)"
    say("check", "links/traverse",
        outbound_from_new=out,
        pass_=any(x["rid"] == old and x["link_type"] == "supersedes" for x in out))

    # Standardverhalten: wird das abgeloeste Record noch serviert?
    served = db.recall(query="Regelsatz Fassung", top_k=5, include_superseded=True)
    say("info", "links/recall_include_superseded", hits=ids(served))
    policy = db.status_read_policy()
    say("info", "links/default_status_read_policy", exclude_superseded=policy)

    db.set_status_read_policy(True)
    served2 = db.recall(query="Regelsatz Fassung", top_k=5)
    say("check", "links/superseded_hidden_after_policy",
        hits=ids(served2), policy_now=db.status_read_policy(),
        pass_=old not in ids(served2) and new in ids(served2))

    # As-of: vor dem Link muss A gelten, nach dem Link nicht mehr
    a_before = db.recall_as_of(t1, query="Regelsatz Fassung", top_k=5)
    say("check", "links/as_of_before_link_serves_old",
        hits=texts(a_before),
        pass_=any("Aussage A" in (h.get("text") or "") for h in a_before))

    a_after = db.recall_as_of(now + 60, query="Regelsatz Fassung", top_k=5)
    say("check", "links/as_of_after_link_hides_old",
        hits=texts(a_after),
        pass_=not any("Aussage A" in (h.get("text") or "") for h in a_after))

    # derived_from: Kind -> Eltern
    child = db.record("Aussage B1: Teilaussage, abgeleitet aus Aussage B.",
                      importance=0.6, half_life=1e9, created_at=t0 + 120)
    db.link(child, new, "derived_from")
    kin = db.linked_records(child, direction="outbound", link_type="derived_from")
    say("check", "links/derived_from",
        links=kin, pass_=any(x["rid"] == new for x in kin))

    db.close()
    db2 = open_db(path)
    out2 = db2.linked_records(new, direction="outbound")
    say("check", "links/survives_reopen",
        outbound=out2, pass_=any(x["rid"] == old for x in out2))
    db2.close()
    return path


# ─────────────────────────────────────────────────────────────────────
# 3. Claims mit zeitlicher Gueltigkeit
# ─────────────────────────────────────────────────────────────────────
def t_claims():
    now = time.time()
    path = fresh("claims")
    db = open_db(path)
    rid = db.record("Taylor leitet das Plattformteam ab 2025.", importance=0.8,
                    half_life=1e9, domain="org")
    rep = db.attach_claims(rid, [
        {"src": "Taylor", "rel_type": "leads", "dst": "Plattformteam",
         "valid_from": now - 86400 * 400, "valid_to": now - 86400 * 10},
        {"src": "Taylor", "rel_type": "leads", "dst": "Infrastrukturteam",
         "valid_from": now - 86400 * 10, "valid_to": None},
    ])
    say("info", "claims/attach", report=rep)

    got = db.claims_for_memory(rid)
    say("check", "claims/validity_fields_present",
        claims=got,
        pass_=bool(got) and any("valid_to" in c for c in (got if isinstance(got, list) else [])))

    ent = db.get_claims("Taylor")
    say("info", "claims/get_claims", claims=ent)

    # Gibt es einen Lesepfad, der die Gueltigkeit ZUM STICHTAG beachtet?
    before = db.recall_as_of(now - 86400 * 200, query="Taylor Team", top_k=5)
    say("info", "claims/as_of_recall", hits=texts(before),
        note="recall_as_of filtert Records, nicht Claims")
    db.close()
    return path


# ─────────────────────────────────────────────────────────────────────
# 4. Beliefs: Evidenzhistorie und Revision (nur api2)
# ─────────────────────────────────────────────────────────────────────
def t_beliefs():
    now = time.time()
    path = fresh("beliefs")
    db = open_db(path)
    if not hasattr(db, "belief_create"):
        say("check", "belief/api_missing", pass_=False,
            note="dieser Build hat keine belief_*-Methoden")
        db.close()
        return path

    prop = "Die Python-Bindings von YantrikDB 0.23.6 stellen keine Belief-API bereit."
    bid = db.belief_create(prop, prior_log_odds=0.0, domain="architektur")
    say("info", "belief/created", node_id=bid)

    e1 = db.belief_assert_evidence(
        bid, weight=2.0,
        source="dir() auf pylib-series-a8032a2: 180 Methoden, kein einziger belief_*-Name",
        provenance="observation", observation_id="obs-dir-methoden")
    say("info", "belief/evidence_1", result=e1)

    s1 = db.belief_get(bid)
    say("info", "belief/state_after_1", state=s1)

    # Dieselbe Beobachtung, neu bewertet: gleiche observation_id -> keine zweite Stimme
    e2 = db.belief_assert_evidence(
        bid, weight=-2.0,
        source="dir() auf pylib-api2: 194 Methoden, davon 14 belief_* (d32f219/api2)",
        provenance="observation", observation_id="obs-dir-methoden")
    say("info", "belief/evidence_2_same_observation", result=e2)

    s2 = db.belief_get(bid)
    trail = s2.get("evidence_trail") or s2.get("payload", {}).get("evidence_trail")
    say("check", "belief/one_voice_per_observation",
        evidence_entries=len(trail) if trail else None,
        trail=trail,
        pass_=bool(trail) and len(trail) == 1)

    ex = db.belief_explain(bid)
    say("info", "belief/explain", explain=ex)

    rev = db.belief_revise(at=now + 86400 * 90)
    say("info", "belief/revise_at_future", summary=rev)
    s3 = db.belief_get(bid)
    say("info", "belief/state_after_staleness", state=s3)

    db.close()
    db2 = open_db(path)
    s4 = db2.belief_get(bid)
    trail4 = s4.get("evidence_trail") or s4.get("payload", {}).get("evidence_trail")
    say("check", "belief/survives_reopen",
        entries=len(trail4) if trail4 else None,
        trail=trail4,
        pass_=bool(trail4) and len(trail4) == 1)
    q = db2.belief_query(domain="architektur")
    say("info", "belief/query_after_reopen", result=q)
    db2.close()
    return path


# ─────────────────────────────────────────────────────────────────────
# 5. Consolidation: Historie und Rueckweg
# ─────────────────────────────────────────────────────────────────────
def t_consolidation():
    path = fresh("cons")
    db = open_db(path)
    base = "Der Nachtlauf verdichtet aehnliche Episoden zu einer Zusammenfassung."
    rids = [db.record(base + f" Variante {i}", importance=0.7, half_life=1e9,
                      domain="wartung") for i in range(3)]
    other = db.record("Etwas ganz anderes ueber Zertifikatserneuerung.",
                      importance=0.6, half_life=1e9, domain="wartung")
    say("info", "cons/rids", rids=rids, other=other)
    try:
        import yantrikdb
        rep = yantrikdb.consolidate(db, sim_threshold=0.5, min_cluster_size=2, dry_run=True)
        say("info", "cons/dry_run", report=rep)
    except Exception as e:
        say("check", "cons/dry_run_error", error=repr(e), pass_=False)
    db.close()

    con = sqlite3.connect(path)
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    say("info", "cons/schema", tables_of_interest=sorted(
        t for t in tables if t in {"consolidation_members", "record_revisions",
                                   "record_links", "state_assertions", "claims",
                                   "cognitive_nodes", "cognitive_edges"}))
    for t in ("state_assertions", "consolidation_members"):
        if t in tables:
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            say("info", f"cons/rowcount_{t}", rows=n)
    con.close()
    return path


# ─────────────────────────────────────────────────────────────────────
def main():
    say("info", "build_info", file=__import__("yantrikdb").__file__)
    for fn in (t_revision_asof, t_links, t_claims, t_beliefs, t_consolidation):
        try:
            fn()
        except Exception as e:
            import traceback
            say("check", fn.__name__ + "/EXCEPTION", error=repr(e),
                traceback=traceback.format_exc()[-1200:], pass_=False)


if __name__ == "__main__":
    main()
