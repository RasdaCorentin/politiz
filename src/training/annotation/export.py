"""Export train/eval en JSONL, avec un jeu d'évaluation figé.

    python -m annotation.export --freeze-eval     # fige lot_eval (une seule fois)
    python -m annotation.export                   # écrit train.jsonl et eval.jsonl

Règles :
- une annotation "de référence" par post : fichier `consensus` s'il existe, sinon l'unique
  annotation, sinon accord complet de tous les annotateurs ; sinon le post est écarté (désaccord) ;
- eval = posts du lot_eval, listés dans eval_fige.json (empreinte SHA-256) ;
- train = tout le reste ; aucun post d'eval n'y entre, jamais.
- textes lus dans lots/corpus_propre.jsonl ; les lots lot_*.jsonl ne servent qu'à lister le pilote
  et l'évaluation.

Option --silver : écrit en plus train_silver.jsonl à partir des étiquettes silver (produites par
un LLM, dossier annotation/silver/final/, un JSONL par fichier, mêmes champs que les annotations).
Seul final/ est lu : shards/ contient les entrées du LLM (sans étiquette) et out/ ses sorties brutes.
- chaque ligne porte `source: silver` ; train.jsonl et eval.jsonl portent `source: gold` ;
- tout post du pilote (lot_00_pilote) et de l'évaluation (lot_eval, eval_fige.json) est exclu ;
- tout post annoté à la main (gold, tous annotateurs) est exclu, sans option : le gold reste le
  jeu de test. Un garde-fou échoue si un post gold se retrouve malgré tout dans train_silver ;
- silver ne va jamais dans eval.jsonl, et l'outil d'annotation n'en affiche jamais.

Option --textes FICHIER (répétable) : textes supplémentaires (JSONL `post_id`, `text` ou `texte`),
ajoutés à corpus_propre.jsonl ; un identifiant déjà connu garde son premier texte ; par exemple lots/textes_nouveau.jsonl, écrit par `annotation.silver_nouveau`.
Sans elle, un post silver absent de corpus_propre.jsonl compte dans `sans_texte`.

Option --stance-regroupe-neutre : fusionne `mention` dans `neutre` dans les fichiers écrits
(projection, voir projection_stance.py ; le schéma n'est pas modifié). Sans option, rien ne change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .common import annotation_dir, entity_choices, load_entites, load_schema
from .storage import load_annotations, read_jsonl, validate
from projection_stance import regrouper_lignes

EVAL_LOT = "lot_eval"
PILOTE_LOT = "lot_00_pilote"
CHAMPS_SORTIE = ["pertinent", "cibles", "themes", "emotion", "ironie", "regle_suffit", "indice"]


def _cle(rec: dict) -> str:
    return json.dumps({k: rec.get(k) for k in CHAMPS_SORTIE[:-1]}, sort_keys=True, ensure_ascii=False)


def reference(recs: dict[str, dict]) -> dict | None:
    """recs : annotateur -> annotation d'un post. Retourne la référence ou None (désaccord)."""
    if not recs:
        return None
    if "consensus" in recs:
        return recs["consensus"]
    vals = list(recs.values())
    if len({_cle(r) for r in vals}) == 1:
        return vals[0]
    return None


def reference_labels(annots: dict[str, dict[str, dict]]) -> tuple[dict[str, dict], list[str]]:
    par_post: dict[str, dict[str, dict]] = {}
    for nom, recs in annots.items():
        for pid, r in recs.items():
            par_post.setdefault(pid, {})[nom] = r
    refs, conflits = {}, []
    for pid, recs in sorted(par_post.items()):
        ref = reference(recs)
        if ref is None:
            conflits.append(pid)
        else:
            refs[pid] = ref
    return refs, conflits


def split(refs: dict[str, dict], posts: dict[str, dict], eval_ids: set[str]) -> tuple[list[dict], list[dict]]:
    def ligne(pid: str) -> dict:
        r = refs[pid]
        return {"post_id": pid, "text": posts[pid]["text"], "created_at": posts[pid].get("created_at"),
                "source": "gold", **{k: r.get(k) for k in CHAMPS_SORTIE}}
    ok = [pid for pid in refs if pid in posts]
    return ([ligne(p) for p in ok if p not in eval_ids], [ligne(p) for p in ok if p in eval_ids])


def load_silver(silver_dir: Path) -> dict[str, dict]:
    """post_id -> dernière étiquette silver (tous les *.jsonl du dossier, ordre alphabétique)."""
    out: dict[str, dict] = {}
    for f in sorted(Path(silver_dir).rglob("*.jsonl")):
        for r in read_jsonl(f):
            if "post_id" in r:
                out[str(r["post_id"])] = r
    return out


def ids_gold(annots: dict[str, dict[str, dict]]) -> set[str]:
    """Posts annotés à la main, par n'importe quel annotateur (désaccords compris)."""
    return {pid for recs in annots.values() for pid in recs}


def silver_train(silver: dict[str, dict], posts: dict[str, dict], exclus: set[str],
                 schema: dict, entites: list[str], *, gold: set[str]) -> tuple[list[dict], dict]:
    """Jeu d'entraînement silver, séparé du gold. Exclut les posts du pilote, de l'évaluation et
    du gold. `gold` est obligatoire : l'exclusion n'a pas d'option pour la désactiver."""
    rows, stats = [], {"exclus_pilote_eval": 0, "exclus_gold": 0, "invalides": 0, "sans_texte": 0}
    for pid, r in sorted(silver.items()):
        if pid in exclus:
            stats["exclus_pilote_eval"] += 1
        elif pid in gold:
            stats["exclus_gold"] += 1
        elif pid not in posts:
            stats["sans_texte"] += 1
        elif validate(r, schema, entites):
            stats["invalides"] += 1
        else:
            rows.append({"post_id": pid, "text": posts[pid]["text"], "created_at": posts[pid].get("created_at"),
                         "source": "silver", **{k: r.get(k) for k in CHAMPS_SORTIE}})
    return rows, stats


def verifier_hors_gold(rows: list[dict], gold: set[str]) -> None:
    """Garde-fou : arrête l'export si un post gold figure dans les données d'entraînement silver."""
    fuites = {r["post_id"] for r in rows} & gold
    if fuites:
        raise SystemExit(f"{len(fuites)} post(s) gold dans train_silver : arrêt, train_silver.jsonl n'est pas écrit.")


def empreinte(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-dir")
    ap.add_argument("--silver", nargs="?", const="", metavar="DOSSIER",
                    help="écrit aussi train_silver.jsonl (source: silver, hors pilote et évaluation) ; "
                         "dossier par défaut : <annotation>/silver/final")
    ap.add_argument("--freeze-eval", action="store_true", help="fige la liste d'ids du lot_eval")
    ap.add_argument("--textes", action="append", default=[], metavar="FICHIER",
                    help="JSONL de textes supplémentaires (post_id, text ou texte) ; répétable")
    ap.add_argument("--stance-regroupe-neutre", action="store_true",
                    help="fusionne mention dans neutre dans les fichiers écrits (projection, schéma inchangé)")
    a = ap.parse_args(argv)
    adir = annotation_dir(a.corpus_dir)
    lock = adir / "eval_fige.json"

    lots = {p.stem: read_jsonl(p) for p in sorted((adir / "lots").glob("lot_*.jsonl"))}
    if a.freeze_eval:
        if lock.exists():
            raise SystemExit(f"{lock} existe déjà : le jeu d'évaluation est figé, on ne le refait pas.")
        ids = sorted(p["post_id"] for p in lots[EVAL_LOT])
        lock.write_text(json.dumps({"lot": EVAL_LOT, "n": len(ids), "sha256": empreinte(ids), "ids": ids},
                                   indent=1), encoding="utf-8")
        print(f"Jeu d'évaluation figé : {len(ids)} posts.")
        return
    if not lock.exists():
        raise SystemExit("Jeu d'évaluation non figé : lancer d'abord --freeze-eval.")
    fige = json.loads(lock.read_text(encoding="utf-8"))
    if empreinte(fige["ids"]) != fige["sha256"]:
        raise SystemExit("eval_fige.json a été modifié : arrêt.")
    eval_ids = set(fige["ids"])

    posts = {p["post_id"]: p for p in read_jsonl(adir / "lots" / "corpus_propre.jsonl")}
    for f in a.textes:
        if not Path(f).is_file():
            raise SystemExit(f"{f} : fichier de textes introuvable.")
        supp = {p["post_id"]: {**p, "text": p.get("text") or p.get("texte")} for p in read_jsonl(Path(f))}
        deja = supp.keys() & posts.keys()
        if deja:
            print(f"{f} : {len(deja)} identifiant(s) déjà connu(s), premier texte gardé")
        posts.update({k: v for k, v in supp.items() if k not in deja})
    annots = {p.stem: load_annotations(p) for p in sorted((adir / "annotations").glob("*.jsonl"))}
    refs, conflits = reference_labels(annots)
    train, ev = split(refs, posts, eval_ids)
    if a.stance_regroupe_neutre:
        train, ev = regrouper_lignes(train), regrouper_lignes(ev)
    for nom, rows in (("train.jsonl", train), ("eval.jsonl", ev)):
        (adir / nom).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    if a.silver is not None:
        exclus = eval_ids | {p["post_id"] for p in lots.get(PILOTE_LOT, [])} | {p["post_id"] for p in lots.get(EVAL_LOT, [])}
        gold = ids_gold(annots)
        sdir = Path(a.silver) if a.silver else adir / "silver" / "final"
        rows, st = silver_train(load_silver(sdir), posts, exclus, load_schema(),
                                entity_choices(load_schema(), load_entites()), gold=gold)
        verifier_hors_gold(rows, gold)
        if a.stance_regroupe_neutre:
            rows = regrouper_lignes(rows)
        (adir / "train_silver.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                                 encoding="utf-8")
        print(f"train_silver : {len(rows)} (source: silver) | {st}")
    manquants = len(eval_ids - {r["post_id"] for r in ev})
    print(f"train : {len(train)} | eval : {len(ev)}/{len(eval_ids)} (à annoter ou arbitrer : {manquants}) "
          f"| désaccords écartés : {len(conflits)}")


if __name__ == "__main__":
    main()
