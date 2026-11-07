"""Accord inter-annotateurs : kappa de Cohen (paires) et de Fleiss (tous), par champ.

    python -m annotation.agreement --lot lot_00_pilote [--annotateurs a b c]
Seuls les posts annotés par TOUS les annotateurs retenus comptent.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from collections import Counter
from pathlib import Path

from .common import annotation_dir, load_schema
from .storage import annotations_path, load_annotations, read_jsonl

ABSENT = "absent"
CHAMPS = ["pertinent", "cibles", "themes", "emotion", "ironie", "regle_suffit"]


def cohen_kappa(a: list, b: list) -> float:
    """kappa de Cohen pour deux séries d'étiquettes. nan si indéfini (étiquette unique)."""
    n = len(a)
    if n == 0 or n != len(b):
        return math.nan
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in ca) / n**2
    if pe == 1:
        return math.nan
    return (po - pe) / (1 - pe)


def fleiss_kappa(matrix: list[list]) -> float:
    """kappa de Fleiss. matrix[i] = étiquettes données par chaque annotateur à l'item i."""
    n_items = len(matrix)
    if n_items == 0:
        return math.nan
    r = len(matrix[0])
    if r < 2 or any(len(row) != r for row in matrix):
        return math.nan
    cats = sorted({x for row in matrix for x in row}, key=str)
    counts = [Counter(row) for row in matrix]
    p_i = [(sum(c[k] ** 2 for k in cats) - r) / (r * (r - 1)) for c in counts]
    p_bar = sum(p_i) / n_items
    p_j = [sum(c[k] for c in counts) / (n_items * r) for k in cats]
    pe = sum(p**2 for p in p_j)
    if pe == 1:
        return math.nan
    return (p_bar - pe) / (1 - pe)


def _items(champ: str, recs: list[dict], themes: list[str]) -> dict[str, list]:
    """Transforme les annotations d'un post (une par annotateur) en items catégoriels.

    clé d'item -> une étiquette par annotateur. Pour les champs structurés :
      - cibles : un item par (post, entité citée par au moins un annotateur), étiquette = stance ou 'absent' ;
      - themes : un item binaire par (post, thème).
    Si pertinent=non, les champs dépendants valent 'vide'.
    """
    pid = recs[0]["post_id"]
    if champ in ("pertinent",):
        return {pid: [r["pertinent"] for r in recs]}
    if champ == "cibles":
        ents = sorted({c["entite"] for r in recs for c in r.get("cibles") or []})
        return {f"{pid}|{e}": [next((c["stance"] or "vide" for c in r.get("cibles") or [] if c["entite"] == e), ABSENT)
                               for r in recs] for e in ents}
    if champ == "themes":
        return {f"{pid}|{t}": [("oui" if t in (r.get("themes") or []) else "non") for r in recs]
                for t in themes}
    return {pid: [r.get(champ) or "vide" for r in recs]}


def agreement(annots: dict[str, dict[str, dict]], themes: list[str], champs=CHAMPS) -> dict:
    """annots[annotateur][post_id] -> annotation. Retourne kappas par champ et pairs."""
    noms = sorted(annots)
    communs = sorted(set.intersection(*(set(a) for a in annots.values()))) if noms else []
    res = {"annotateurs": noms, "n_posts": len(communs), "champs": {}}
    for champ in champs:
        items: dict[str, list] = {}
        for pid in communs:
            items.update(_items(champ, [annots[n][pid] for n in noms], themes))
        mat = list(items.values())
        info = {"n_items": len(mat),
                "accord_brut": (sum(len(set(r)) == 1 for r in mat) / len(mat)) if mat else math.nan,
                "fleiss": fleiss_kappa(mat) if len(noms) >= 2 else math.nan, "cohen": {}}
        for (i, a), (j, b) in itertools.combinations(enumerate(noms), 2):
            info["cohen"][f"{a}~{b}"] = cohen_kappa([r[i] for r in mat], [r[j] for r in mat])
        res["champs"][champ] = info
    return res


def disagreements(annots: dict[str, dict[str, dict]], posts: dict[str, dict], themes: list[str]) -> list[dict]:
    """Posts où au moins un champ diverge (pour réviser le guide). Contient le texte : hors git."""
    noms = sorted(annots)
    communs = sorted(set.intersection(*(set(a) for a in annots.values())))
    out = []
    for pid in communs:
        recs = [annots[n][pid] for n in noms]
        champs_div = [c for c in CHAMPS
                      if any(len(set(v)) > 1 for v in _items(c, recs, themes).values())]
        if champs_div:
            out.append({"post_id": pid, "text": posts.get(pid, {}).get("text", ""), "champs": champs_div,
                        "annotations": {n: {k: annots[n][pid].get(k) for k in
                                            CHAMPS + ["indice", "commentaire"]} for n in noms}})
    return out


def _fmt(x: float) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.2f}"


def interpretation(k: float) -> str:
    if k is None or math.isnan(k):
        return "indéfini"
    for seuil, txt in [(0.8, "très bon"), (0.6, "bon"), (0.4, "moyen"), (0.2, "faible")]:
        if k >= seuil:
            return txt
    return "quasi nul"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lot", required=True, help="nom du lot, ex. lot_00_pilote")
    ap.add_argument("--annotateurs", nargs="*", help="par défaut : tous les fichiers trouvés")
    ap.add_argument("--corpus-dir")
    ap.add_argument("--desaccords", action="store_true", help="écrit la liste des désaccords (avec texte)")
    a = ap.parse_args(argv)

    adir = annotation_dir(a.corpus_dir)
    schema = load_schema()
    fichiers = {p.stem: p for p in (adir / "annotations").glob("*.jsonl")}
    noms = a.annotateurs or sorted(fichiers)
    annots = {}
    for n in noms:
        recs = load_annotations(annotations_path(adir, n))
        annots[n] = {k: v for k, v in recs.items() if v.get("lot") == a.lot}
    if len(annots) < 2:
        raise SystemExit("Il faut au moins deux annotateurs.")
    res = agreement(annots, schema["themes"]["valeurs"])
    print(f"Lot {a.lot} : {res['n_posts']} posts annotés par {', '.join(res['annotateurs'])}\n")
    print(f"{'champ':14}{'items':>7}{'accord':>8}{'Fleiss':>8}  lecture")
    for c, i in res["champs"].items():
        print(f"{c:14}{i['n_items']:>7}{_fmt(i['accord_brut']):>8}{_fmt(i['fleiss']):>8}  {interpretation(i['fleiss'])}")
        for paire, k in i["cohen"].items():
            print(f"{'':14}{paire:>23} Cohen {_fmt(k)}")
    if a.desaccords:
        posts = {p["post_id"]: p for p in read_jsonl(adir / "lots" / f"{a.lot}.jsonl")}
        dis = disagreements(annots, posts, schema["themes"]["valeurs"])
        dest = adir / f"desaccords_{a.lot}.jsonl"
        dest.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in dis), encoding="utf-8")
        print(f"\n{len(dis)} posts en désaccord -> {dest}")


if __name__ == "__main__":
    main()
