"""Préparation du corpus : nettoyage, dédoublonnage, tirage stratifié en lots.

Lancement (depuis src/training) :
    python -m annotation.prepare --db <corpus>.db --corpus-dir <dossier>
Le corpus n'est jamais copié dans le dépôt : tout est écrit dans <dossier>/annotation/.
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from .common import (alias_map, annotation_dir, compile_aliases, detect_entities,
                     load_entites, normalize)

SEED = 2027
MIN_MOTS = 4          # voir docs : en dessous, trop peu de contenu pour une stance
SEUIL_QUASI_DOUBLON = 0.85
MIN_TOKENS_QUASI = 5  # on ne compare pas les textes plus courts (faux positifs)
PART_JOUR_MAX = 0.30  # un jour au-dessus de ce poids est découpé en tranches de 4 h


# --------------------------------------------------------------- lecture / nettoyage
def load_posts(db: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT id, created_at, text, dedup_key FROM posts ORDER BY created_at, id")
        return [{"post_id": str(r[0]), "created_at": r[1], "text": r[2] or "", "dedup_key": r[3]}
                for r in rows]
    finally:
        con.close()


def filter_short(posts: list[dict], min_mots: int = MIN_MOTS) -> tuple[list[dict], int]:
    """Écarte les posts dont le texte normalisé (sans URL ni @mention) a moins de min_mots mots."""
    kept = [p for p in posts if len(normalize(p["text"]).split()) >= min_mots]
    return kept, len(posts) - len(kept)


def _jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def dedupe(posts: list[dict], seuil: float = SEUIL_QUASI_DOUBLON) -> tuple[list[dict], dict]:
    """Garde le plus ancien de chaque groupe.

    1. doublon exact : même texte normalisé ;
    2. quasi-doublon : Jaccard des ensembles de mots >= seuil (O(n^2), ok pour quelques milliers).
    """
    stats = {"exacts": 0, "quasi": 0}
    vus: set[str] = set()
    uniques: list[tuple[dict, frozenset]] = []
    for p in sorted(posts, key=lambda p: (p["created_at"], p["post_id"])):
        n = normalize(p["text"])
        if n in vus:
            stats["exacts"] += 1
            continue
        vus.add(n)
        toks = frozenset(n.split())
        if len(toks) >= MIN_TOKENS_QUASI and any(
                len(t) >= MIN_TOKENS_QUASI and abs(len(t) - len(toks)) <= len(toks) * (1 - seuil) + 1
                and _jaccard(toks, t) >= seuil for _, t in uniques):
            stats["quasi"] += 1
            continue
        uniques.append((p, toks))
    return [p for p, _ in uniques], stats


# --------------------------------------------------------------- strates
def assign_slots(posts: list[dict], part_max: float = PART_JOUR_MAX) -> None:
    """Ajoute p['slot'] : le jour, ou jour+tranche de 4 h si ce jour pèse > part_max."""
    par_jour = Counter(p["created_at"][:10] for p in posts)
    total = max(len(posts), 1)
    for p in posts:
        jour = p["created_at"][:10]
        if par_jour[jour] / total > part_max:
            heure = int(p["created_at"][11:13] or 0)
            p["slot"] = f"{jour}T{heure // 4 * 4:02d}h"
        else:
            p["slot"] = jour


def annotate_entities(posts: list[dict], amap: dict[str, str]) -> None:
    pat = compile_aliases(amap)
    for p in posts:
        p["entites_proposees"], p["entites_incertaines"] = detect_entities(p["text"], amap, pat)


def assign_strata(posts: list[dict]) -> None:
    """Strate = entité citée la plus rare du pool (donne leur chance aux petites), sinon 'aucune'."""
    freq = Counter(e for p in posts for e in p["entites_proposees"])
    for p in posts:
        ents = p["entites_proposees"]
        p["strate"] = min(ents, key=lambda e: (freq[e], e)) if ents else "aucune"


def _waterfill(tailles: dict[str, int], total: int) -> dict[str, int]:
    """Répartit total entre strates à parts égales, plafonnées par leur taille."""
    alloc = {k: 0 for k in tailles}
    reste = min(total, sum(tailles.values()))
    actives = [k for k in tailles if tailles[k] > 0]
    while reste > 0 and actives:
        part, extra = divmod(reste, len(actives))
        part = max(part, 1) if extra else part
        for k in list(actives):
            don = min(part, tailles[k] - alloc[k], reste)
            alloc[k] += don
            reste -= don
            if alloc[k] >= tailles[k]:
                actives.remove(k)
            if reste == 0:
                break
    return alloc


def _pick_round_robin(posts: list[dict], k: int, rng: random.Random) -> list[dict]:
    """k posts, en tournant sur les tranches temporelles (ordre et posts mélangés)."""
    par_slot: dict[str, list[dict]] = defaultdict(list)
    for p in posts:
        par_slot[p["slot"]].append(p)
    slots = sorted(par_slot)
    rng.shuffle(slots)
    for s in slots:
        rng.shuffle(par_slot[s])
    out: list[dict] = []
    while len(out) < k and any(par_slot.values()):
        for s in slots:
            if par_slot[s] and len(out) < k:
                out.append(par_slot[s].pop())
    return out


def stratified_sample(pool: list[dict], n: int, seed: int = SEED,
                      part_aucune: float = 0.25) -> list[dict]:
    """Tirage reproductible de n posts : strates = entité (parts égales) + 'aucune' (part fixe),
    à l'intérieur d'une strate, tranches temporelles à tour de rôle.

    Parts égales entre entités : on veut assez d'exemples des petites pour les évaluer.
    Conséquence : l'échantillon n'est pas représentatif ; pondérer pour estimer des taux globaux.
    """
    rng = random.Random(seed)
    pool = sorted(pool, key=lambda p: p["post_id"])
    strates: dict[str, list[dict]] = defaultdict(list)
    for p in pool:
        strates[p["strate"]].append(p)
    aucune = strates.pop("aucune", [])
    n = min(n, len(pool))
    n_aucune = min(round(n * part_aucune), len(aucune))
    n_ent = min(n - n_aucune, sum(len(v) for v in strates.values()))
    n_aucune = min(n - n_ent, len(aucune))  # comble si les entités manquent de posts
    alloc = _waterfill({k: len(v) for k, v in sorted(strates.items())}, n_ent)
    out: list[dict] = []
    for k in sorted(strates):
        out += _pick_round_robin(strates[k], alloc[k], rng)
    out += _pick_round_robin(aucune, n_aucune, rng)
    rng.shuffle(out)
    return out


def build_lots(posts: list[dict], pilote: int = 50, n_eval: int = 200, taille_lot: int = 150,
               seed: int = SEED) -> dict[str, list[dict]]:
    """Découpe sans recouvrement : pilote, eval, puis lot_01, lot_02... jusqu'à épuisement."""
    reste = list(posts)
    lots: dict[str, list[dict]] = {}

    def tirer(nom: str, n: int, graine: int) -> None:
        assign_strata(reste)
        tire = stratified_sample(reste, n, graine)
        ids = {p["post_id"] for p in tire}
        reste[:] = [p for p in reste if p["post_id"] not in ids]
        lots[nom] = [{**p, "lot": nom} for p in tire]

    tirer("lot_00_pilote", pilote, seed)
    tirer("lot_eval", n_eval, seed + 1)
    i = 1
    while reste:
        tirer(f"lot_{i:02d}", taille_lot, seed + 1 + i)
        i += 1
    return lots


# --------------------------------------------------------------- CLI
def write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, type=Path, help="base SQLite du corpus (lecture seule)")
    ap.add_argument("--corpus-dir", help="dossier du corpus (sinon $SAE_CORPUS_DIR)")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--pilote", type=int, default=50)
    ap.add_argument("--eval", type=int, default=200, dest="n_eval")
    ap.add_argument("--taille-lot", type=int, default=150)
    ap.add_argument("--min-mots", type=int, default=MIN_MOTS)
    ap.add_argument("--force", action="store_true", help="écraser des lots existants")
    a = ap.parse_args(argv)

    out = annotation_dir(a.corpus_dir) / "lots"
    if out.exists() and any(out.glob("lot_*.jsonl")) and not a.force:
        raise SystemExit(f"{out} contient déjà des lots (annotations en cours ?). --force pour écraser.")
    out.mkdir(parents=True, exist_ok=True)

    posts = load_posts(a.db)
    n0 = len(posts)
    posts, n_courts = filter_short(posts, a.min_mots)
    posts, dd = dedupe(posts)
    amap = alias_map(load_entites())
    annotate_entities(posts, amap)
    assign_slots(posts)
    lots = build_lots(posts, a.pilote, a.n_eval, a.taille_lot, a.seed)

    for nom, rows in lots.items():
        write_jsonl(out / f"{nom}.jsonl", rows)
    write_jsonl(out / "corpus_propre.jsonl", posts)

    ent = Counter(e for p in posts for e in p["entites_proposees"])
    plan = {"graine": a.seed, "bruts": n0, "trop_courts": n_courts, "doublons_exacts": dd["exacts"],
            "quasi_doublons": dd["quasi"], "retenus": len(posts),
            "sans_entite": sum(1 for p in posts if not p["entites_proposees"]),
            "posts_par_entite": dict(ent.most_common()),
            "lots": {k: len(v) for k, v in lots.items()}}
    (out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in plan.items() if k != "posts_par_entite"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
