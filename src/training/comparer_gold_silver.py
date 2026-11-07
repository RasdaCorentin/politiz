"""Accord entre étiquettes silver (LLM) et gold (humain) : agrégats seulement.

    python3 -I src/training/comparer_gold_silver.py --corpus <dossier du corpus>

Lit les JSONL du corpus (hors dépôt) et imprime sur stdout : effectifs, accords,
intervalles de Wilson à 95 %, chevauchements entre jeux, couverture du lexique
d'émotion. Avec `--emotion-3-classes`, l'accord d'émotion se lit en joie / colere / neutre
(projection_emotion) ; les posts qui n'ont plus de classe sont exclus et comptés à part.
N'imprime jamais de texte de post, de handle, de DID ni d'identifiant de post.
Bibliothèque standard uniquement.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

# Lancé avec `python3 -I`, le dossier du script n'est pas dans sys.path : on l'ajoute pour projection_emotion.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from projection_emotion import reduire_emotion  # noqa: E402

RACINE = Path(__file__).resolve().parents[2]
Z95 = 1.959963984540054
CONFIANCES_UTILES = ("haute", "moyenne")  # celles que retient le scoreur lexique-v1
HANDLE_RE = re.compile(r"@[a-z0-9][a-z0-9._\-]*")  # même motif que le scoreur
URL_RE = re.compile(r"https?://\S+|www\.\S+")
EMOTION_RE = re.compile(r"^\s*-\s*emotion:\s*(\w+)")
MARQUEUR_RE = re.compile(r'\{motif:\s*"((?:[^"\\]|\\.)*)"\s*,\s*confiance:\s*(\w+)')


def pct(k: int, n: int) -> str:
    return "n/a" if n == 0 else f"{100 * k / n:.1f} %".replace(".", ",")


def intervalle(k: int, n: int) -> str:
    """Intervalle de Wilson à 95 % pour k succès sur n."""
    if n == 0:
        return "n/a"
    p = k / n
    z2 = Z95**2
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    marge = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    bas, haut = 100 * (centre - marge), 100 * (centre + marge)
    return f"[{bas:.1f} ; {haut:.1f}] %".replace(".", ",")


def ligne_accord(titre: str, k: int, n: int) -> None:
    print(f"{titre} : {k}/{n} = {pct(k, n)} ; IC95 Wilson {intervalle(k, n)}")


def compte(valeurs) -> str:
    c = Counter("vide" if v in (None, "") else str(v) for v in valeurs)
    return " ".join(f"{k}={v}" for k, v in sorted(c.items()))


def section(titre: str) -> None:
    print(f"\n== {titre}")


def lire_jsonl(chemin: Path) -> list[dict]:
    if not chemin.is_file():
        sys.exit(f"Fichier absent : {chemin.name}")
    with chemin.open(encoding="utf-8") as f:
        return [json.loads(ligne) for ligne in f if ligne.strip()]


def nettoyer(texte: str) -> str:
    """Approche du texte nettoyé attendu par le scoreur : minuscules, sans accents, sans URL ni handle."""
    t = unicodedata.normalize("NFKD", (texte or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return HANDLE_RE.sub(" ", URL_RE.sub(" ", t))


def charger_lexique(chemin: Path) -> dict[str, list[tuple[re.Pattern, str]]]:
    """Lit emotions.yaml sans PyYAML : une émotion par bloc, un marqueur par ligne inline."""
    if not chemin.is_file():
        sys.exit(f"Lexique absent : {chemin.name}")
    classes: dict[str, list[tuple[re.Pattern, str]]] = {}
    courant = None
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        m = EMOTION_RE.match(ligne)
        if m:
            courant = m.group(1)
            classes.setdefault(courant, [])
            continue
        for mm in MARQUEUR_RE.finditer(ligne):
            motif = json.loads('"' + mm.group(1) + '"')
            classes[courant].append((re.compile(motif), mm.group(2)))
    return classes


def declenche(classes, texte: str) -> set[str]:
    """Émotions dont au moins un marqueur utile (haute ou moyenne) se déclenche."""
    t = nettoyer(texte)
    return {e for e, marqueurs in classes.items()
            if any(conf in CONFIANCES_UTILES and motif.search(t) for motif, conf in marqueurs)}


def analyser_pertinence(gold: dict, silver: dict) -> None:
    section("Pertinence (gold vs silver)")
    ids = [p for p in gold if p in silver]
    print(f"posts gold : {len(gold)} ; présents côté silver : {len(ids)}")
    ligne_accord("accord exact", sum(gold[p]["pertinent"] == silver[p]["pertinent"] for p in ids), len(ids))
    print("effectifs gold : " + compte(gold[p]["pertinent"] for p in ids))
    print("effectifs silver (mêmes posts) : " + compte(silver[p]["pertinent"] for p in ids))
    paires = Counter((gold[p]["pertinent"], silver[p]["pertinent"]) for p in ids)
    print("paires gold -> silver : " + ", ".join(f"{g}->{s}={n}" for (g, s), n in sorted(paires.items())))
    hors = [p for p in ids if gold[p]["pertinent"] == "non"]
    print("hors-sujets gold (non) : silver donne " + compte(silver[p]["pertinent"] for p in hors))


def analyser_cibles(gold: dict, silver: dict) -> None:
    section("Cibles (lignes entité x stance côté gold)")
    lignes = [(p, c["entite"], c["stance"]) for p, g in gold.items() for c in g.get("cibles", [])]
    cib_silver = {p: {c["entite"]: c["stance"] for c in silver[p].get("cibles", [])}
                  for p in gold if p in silver}
    doublons = sum(len(silver[p].get("cibles", [])) - len(cib_silver[p]) for p in cib_silver)
    print(f"lignes gold : {len(lignes)} ; entités dupliquées côté silver : {doublons}")
    presentes = sum(e in cib_silver.get(p, {}) for p, e, _ in lignes)
    ligne_accord("entité citée aussi par silver", presentes, len(lignes))
    accord = sum(cib_silver.get(p, {}).get(e) == st for p, e, st in lignes)
    ligne_accord("entité et stance identiques", accord, len(lignes))
    print("effectifs gold (stance) : " + compte(st for _, _, st in lignes))
    print("effectifs silver sur les mêmes entités : "
          + compte(cib_silver[p][e] for p, e, _ in lignes if e in cib_silver.get(p, {})))
    paires = Counter((st, cib_silver[p][e]) for p, e, st in lignes if e in cib_silver.get(p, {}))
    print("paires stance gold -> silver (entité commune) : "
          + ", ".join(f"{g}->{s}={n}" for (g, s), n in sorted(paires.items())))


def analyser_emotion(gold: dict, silver: dict, trois_classes: bool = False) -> None:
    if trois_classes:
        analyser_emotion_trois_classes(gold, silver)
        return
    section("Émotion (gold renseigné : posts pertinents ou doute)")
    ids = [p for p, g in gold.items() if g.get("emotion") is not None]
    print(f"posts gold avec émotion : {len(ids)} ; exclus (émotion vide côté gold) : {len(gold) - len(ids)}")
    accord = sum(gold[p]["emotion"] == (silver[p].get("emotion") or None) for p in ids if p in silver)
    ligne_accord("accord exact", accord, len(ids))
    print("effectifs gold : " + compte(gold[p]["emotion"] for p in ids))
    print("effectifs silver (mêmes posts) : " + compte(silver[p].get("emotion") for p in ids if p in silver))


def analyser_emotion_trois_classes(gold: dict, silver: dict) -> None:
    """Accord d'émotion après projection à trois classes. Un post est retenu si gold et silver ont
    chacun une classe après projection ; les autres (surprise, émotion absente) sont exclus et comptés."""
    section("Émotion projetée à 3 classes (joie / colere / neutre)")

    def classe(ligne: dict) -> str | None:
        return reduire_emotion(ligne.get("emotion") or None)

    ids = [p for p, g in gold.items() if g.get("emotion") is not None]
    retenus = [p for p in ids if p in silver and classe(gold[p]) is not None and classe(silver[p]) is not None]
    print(f"posts gold avec émotion : {len(ids)} ; retenus : {len(retenus)} ; "
          f"exclus : {len(ids) - len(retenus)} (dont surprise côté gold : "
          f"{sum(classe(gold[p]) is None for p in ids)})")
    accord = sum(classe(gold[p]) == classe(silver[p]) for p in retenus)
    ligne_accord("accord exact (3 classes)", accord, len(retenus))
    print("effectifs gold (3 classes) : " + compte(classe(gold[p]) for p in retenus))
    print("effectifs silver (3 classes, mêmes posts) : " + compte(classe(silver[p]) for p in retenus))
    paires = Counter((classe(gold[p]), classe(silver[p])) for p in retenus)
    print("paires gold -> silver (3 classes) : " + ", ".join(f"{g}->{s}={n}" for (g, s), n in sorted(paires.items())))


def analyser_lexique(classes, jeux) -> None:
    section("Couverture du lexique d'émotion (approché, voir docstring du module)")
    for e, marqueurs in classes.items():
        utiles = sum(conf in CONFIANCES_UTILES for _, conf in marqueurs)
        print(f"marqueurs {e} : total={len(marqueurs)} ; utiles (haute/moyenne)={utiles}")
    for nom, items in jeux:
        decl = [declenche(classes, t) for t, _ in items]
        print(f"\n[{nom}] posts : {len(items)} ; au moins un marqueur utile : {sum(bool(d) for d in decl)}"
              f" ; aucune émotion (non_evalue) : {sum(not d for d in decl)}")
        for e in sorted(set(classes) | {lab for _, lab in items if lab}):
            fire = sum(e in d for d in decl)
            lab = sum(l == e for _, l in items)
            lab_fire = sum(l == e and e in d for (_, l), d in zip(items, decl))
            print(f"  {e} : posts déclenchés={fire} ; étiquette={lab} dont déclenchés={lab_fire}")


def analyser_chevauchements(gold_ids: set, train_ids: set, lot_ids: set, fige_ids: set,
                            annotes_ids: set, silver_ids: set) -> None:
    section("Chevauchements et lot figé")
    print(f"gold ∩ train_silver : {len(gold_ids & train_ids)}")
    print(f"lot figé ∩ train_silver : {len(lot_ids & train_ids)} ; eval_fige ∩ train_silver : {len(fige_ids & train_ids)}")
    print(f"gold ∩ lot figé : {len(gold_ids & lot_ids)}")
    print(f"ids eval_fige = ids lot figé : {fige_ids == lot_ids} ({len(lot_ids)} posts)")
    print(f"lot figé avec annotation humaine : {len(lot_ids & annotes_ids)}")
    print(f"lot figé avec étiquette silver : {len(lot_ids & silver_ids)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Accord silver/gold : agrégats seulement.")
    parser.add_argument("--corpus", required=True, type=Path, help="dossier du corpus (hors dépôt)")
    parser.add_argument("--lexique", type=Path, default=RACINE / "ressources" / "lexique" / "emotions.yaml")
    parser.add_argument("--emotion-3-classes", action="store_true",
                        help="accord d'émotion projeté à joie / colere / neutre (projection_emotion)")
    args = parser.parse_args()
    ann = args.corpus / "annotation"
    if not ann.is_dir():
        sys.exit("Dossier du corpus invalide : annotation/ absent.")

    fichiers = sorted((ann / "annotations").glob("*.jsonl"))
    if not fichiers:
        sys.exit("Aucune annotation humaine (annotation/annotations/*.jsonl).")
    brut = [r for f in fichiers for r in lire_jsonl(f)]
    annotateurs = {r.get("annotateur") for r in brut}
    if len(annotateurs) != 1:
        sys.exit(f"Le script suppose un gold à un annotateur ; trouvés : {len(annotateurs)}.")
    gold: dict[str, dict] = {}
    for r in brut:  # une ligne par sauvegarde : la dernière l'emporte
        gold[r["post_id"]] = r
    annotes_ids = {r["post_id"] for r in brut}

    silver = {r["post_id"]: r for r in lire_jsonl(ann / "silver" / "final" / "silver_v1.jsonl")}
    train_rows = lire_jsonl(ann / "train_silver.jsonl")
    train = {r["post_id"]: r for r in train_rows}
    lot_eval = {r["post_id"]: r for r in lire_jsonl(ann / "lots" / "lot_eval.jsonl")}
    if not (ann / "eval_fige.json").is_file():
        sys.exit("Fichier absent : eval_fige.json")
    fige = json.loads((ann / "eval_fige.json").read_text(encoding="utf-8"))

    section("Périmètre")
    print(f"gold : {len(brut)} lignes, {len(gold)} posts, annotateurs : {len(annotateurs)}, "
          f"lignes en double retirées : {len(brut) - len(gold)}")
    print(f"silver : {len(silver)} posts ; train_silver : {len(train)} lignes ; "
          f"lot figé : {len(lot_eval)} posts (eval_fige n = {fige.get('n')})")
    print(f"gold présent côté silver : {sum(p in silver for p in gold)}/{len(gold)}")

    analyser_pertinence(gold, silver)
    analyser_cibles(gold, silver)
    analyser_emotion(gold, silver, args.emotion_3_classes)

    # Textes : seulement pour compter les déclenchements, jamais imprimés.
    textes_gold = {}
    for f in sorted((ann / "lots").glob("lot_*.jsonl")):
        for r in lire_jsonl(f):
            if r["post_id"] in gold:
                textes_gold[r["post_id"]] = r.get("text") or ""
    print(f"\ntextes retrouvés pour le gold : {len(textes_gold)}/{len(gold)}")
    classes = charger_lexique(args.lexique)
    gold_emo = [(textes_gold.get(p, ""), g["emotion"]) for p, g in gold.items() if g.get("emotion") is not None]
    train_items = [(r.get("text") or "", r.get("emotion") or None) for r in train_rows]
    analyser_lexique(classes, [("gold, 26 posts avec émotion", gold_emo),
                               ("train_silver (étiquettes silver)", train_items)])

    analyser_chevauchements(set(gold), set(train), set(lot_eval), set(fige["ids"]),
                            annotes_ids, set(silver))


if __name__ == "__main__":
    main()
