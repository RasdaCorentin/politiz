"""Tire des lots gold (annotation humaine) à partir de la collecte, hors dépôt.

    python -m annotation.lots_gold --corpus <dossier> [--taille 20] [--lots 3]
        [--avec-contexte 40] [--graine 2027] [--depuis DATE] [--premier 1]
        [--sortie <dossier>]

Lit <corpus>/collecte/ancien.jsonl et <corpus>/collecte/nouveau.jsonl (une ligne par post :
source, id_source, created_at, texte, contexte_type, contexte_texte).

Règles :
- exclut les posts déjà annotés (annotation/annotations/*.jsonl), le lot d'évaluation figé
  (annotation/lots/lot_eval.jsonl) et le silver d'entraînement (annotation/train_silver.jsonl) ;
  les identifiants de ces fichiers désignent des posts de l'ancienne base (source « ancien ») ;
  les textes exclus (texte normalisé) écartent aussi les posts de l'autre source ;
- exclut les posts déjà présents dans un lot du dossier de sortie (lot_gold_*.jsonl), par
  identifiant ou par texte masqué ;
- ne garde que created_at >= --depuis (défaut 2026-10-01 UTC ; sans fuseau, UTC) ;
- supprime les doublons de texte (NFKC, casse et espaces ignorés ; le post avec contexte l'emporte) ;
- tire, avec une graine fixe et sans remise, un échantillon avec contexte et un échantillon
  sans contexte, puis répartit l'ensemble en lots de taille fixe, numérotés à partir de --premier ;
- masque les mentions (@...) et les URL dans le texte et dans le contexte ;
- écrit <sortie>/lot_gold_NN.jsonl et <sortie>/manifest.json (ou manifest_lot_gold_NN_MM.json
  si --premier n'est pas 1), sans aucun texte. N'écrase jamais un fichier existant.

Bibliothèque standard et PyYAML (via common). Aucun identifiant ni texte réel dans ce module.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .common import MENTION_RE, URL_RE

DATE_MIN = datetime(2026, 10, 1, tzinfo=timezone.utc)
GRAINE = 2027
TAILLE = 20
NB_LOTS = 3
AVEC_CONTEXTE = 40
PREMIER = 1
SOURCES = ("ancien", "nouveau")


def lire_jsonl(chemin: Path) -> list[dict]:
    if not chemin.is_file():
        raise SystemExit(f"Fichier absent : {chemin}")
    with chemin.open(encoding="utf-8") as f:
        return [json.loads(ligne) for ligne in f if ligne.strip()]


def cle_texte(texte: str | None) -> str:
    """Clé de comparaison : NFKC, casse ignorée, espaces réduits. Ponctuation, URL et mentions gardées."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", texte or "")).strip().casefold()


def parse_date(valeur: str) -> datetime:
    d = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_depuis(valeur: str) -> datetime:
    """Date ou date-heure ISO 8601 pour --depuis ; sans fuseau, UTC."""
    try:
        return parse_date(valeur)
    except ValueError:
        raise argparse.ArgumentTypeError(f"date invalide : {valeur!r} (ISO 8601 attendu, ex. 2026-10-31)")


def parse_premier(valeur: str) -> int:
    try:
        n = int(valeur)
    except ValueError:
        raise argparse.ArgumentTypeError(f"entier attendu : {valeur!r}")
    if n < 1:
        raise argparse.ArgumentTypeError("--premier doit être un entier supérieur ou égal à 1")
    return n


def masquer(texte: str | None) -> str | None:
    """Remplace les URL par [url] puis les mentions par [mention]."""
    if texte is None:
        return None
    return MENTION_RE.sub("[mention]", URL_RE.sub("[url]", texte))


def charger_collecte(dossier: Path) -> list[dict]:
    posts = []
    for source in SOURCES:
        for r in lire_jsonl(dossier / "collecte" / f"{source}.jsonl"):
            posts.append({
                "post_id": f"{source}:{r['id_source']}",
                "source": source,
                "id_source": r["id_source"],
                "created_at": r["created_at"],
                "texte": r["texte"] or "",
                "contexte_type": r.get("contexte_type"),
                "contexte_texte": r.get("contexte_texte") or None,
            })
    return posts


def exclusions(dossier: Path, posts: list[dict]) -> tuple[set[str], set[str], dict]:
    """Renvoie (identifiants exclus, textes normalisés exclus, compteurs)."""
    ann = dossier / "annotation"
    gold = [r for f in sorted((ann / "annotations").glob("*.jsonl")) for r in lire_jsonl(f)]
    lot_eval = lire_jsonl(ann / "lots" / "lot_eval.jsonl")
    train = lire_jsonl(ann / "train_silver.jsonl")

    ids_exclus = {f"ancien:{r['post_id']}" for r in gold + lot_eval + train}
    ancien = {p["post_id"]: p for p in posts if p["source"] == "ancien"}
    textes = {cle_texte(r["text"]) for r in lot_eval + train if r.get("text")}
    textes |= {cle_texte(ancien[i]["texte"]) for i in ids_exclus if i in ancien}
    textes.discard("")
    compte = {
        "gold": len(gold),
        "lot_eval": len(lot_eval),
        "train_silver": len(train),
        "identifiants_sans_post": len(ids_exclus - {p["post_id"] for p in posts}),
    }
    return ids_exclus, textes, compte


def lots_existants(sortie: Path) -> tuple[set[str], set[str], int]:
    """Renvoie (identifiants, textes normalisés masqués, nombre de fichiers) des lots déjà tirés."""
    fichiers = sorted(sortie.glob("lot_gold_*.jsonl")) if sortie.is_dir() else []
    lignes = [r for f in fichiers for r in lire_jsonl(f)]
    ids = {r["post_id"] for r in lignes}
    textes = {cle_texte(r["texte"]) for r in lignes if r.get("texte")}
    textes.discard("")
    return ids, textes, len(fichiers)


def filtrer(posts: list[dict], ids_exclus: set[str], textes_exclus: set[str],
            depuis: datetime = DATE_MIN, ids_lots: set[str] = frozenset(),
            textes_lots: set[str] = frozenset()) -> list[dict]:
    """Posts hors exclusions (identifiant ou texte), déjà en lot (identifiant ou texte masqué),
    et datés à partir de `depuis`."""
    return [p for p in posts
            if p["post_id"] not in ids_exclus
            and p["post_id"] not in ids_lots
            and parse_date(p["created_at"]) >= depuis
            and cle_texte(p["texte"]) not in textes_exclus
            and cle_texte(masquer(p["texte"])) not in textes_lots]


def dedoublonner(posts: list[dict]) -> list[dict]:
    """Un seul post par texte. Le post avec contexte l'emporte, puis l'ordre source et identifiant."""
    ordre = sorted(posts, key=lambda p: (p["contexte_texte"] is None, p["source"], p["id_source"]))
    vus: set[str] = set()
    uniques = []
    for p in ordre:
        cle = cle_texte(p["texte"])
        if cle not in vus:
            vus.add(cle)
            uniques.append(p)
    return uniques


def tirer(posts: list[dict], taille: int, nb_lots: int, avec_contexte: int, graine: int) -> list[list[dict]]:
    total = taille * nb_lots
    if avec_contexte > total:
        raise SystemExit("--avec-contexte dépasse la taille totale des lots.")
    pool_ctx = sorted((p for p in posts if p["contexte_texte"] is not None), key=lambda p: p["post_id"])
    pool_sans = sorted((p for p in posts if p["contexte_texte"] is None), key=lambda p: p["post_id"])
    if len(pool_ctx) < avec_contexte or len(pool_sans) < total - avec_contexte:
        raise SystemExit(f"Corpus insuffisant : {len(pool_ctx)} avec contexte, {len(pool_sans)} sans.")
    rng = random.Random(graine)
    choisis = rng.sample(pool_ctx, avec_contexte) + rng.sample(pool_sans, total - avec_contexte)
    rng.shuffle(choisis)
    return [choisis[i * taille:(i + 1) * taille] for i in range(nb_lots)]


def ligne_lot(post: dict, lot: str) -> dict:
    return {
        "post_id": post["post_id"],
        "lot": lot,
        "source": post["source"],
        "created_at": post["created_at"],
        "texte": masquer(post["texte"]),
        "contexte_type": post["contexte_type"],
        "contexte_texte": masquer(post["contexte_texte"]),
    }


def nom_manifest(premier: int, nb_lots: int) -> str:
    if premier == 1:
        return "manifest.json"
    return f"manifest_lot_gold_{premier:02d}_{premier + nb_lots - 1:02d}.json"


def manifest(lots: dict[str, list[dict]], graine: int, taille: int, avec_contexte: int,
             exclus: dict, eligibles: dict, depuis: datetime) -> dict:
    return {
        "graine": graine,
        "taille_lot": taille,
        "avec_contexte_cible": avec_contexte,
        "date_minimale": depuis.isoformat(),
        "exclusions": exclus,
        "eligibles": eligibles,
        "lots": {
            nom: {
                "posts": len(posts),
                "par_source": dict(sorted(Counter(p["source"] for p in posts).items())),
                "avec_contexte": sum(p["contexte_texte"] is not None for p in posts),
            }
            for nom, posts in lots.items()
        },
        "avec_contexte_total": sum(p["contexte_texte"] is not None for ps in lots.values() for p in ps),
    }


def construire(dossier: Path, taille: int, nb_lots: int, avec_contexte: int, graine: int,
               sortie: Path | None = None, depuis: datetime = DATE_MIN,
               premier: int = PREMIER) -> tuple[dict, dict]:
    """Renvoie (lots : nom -> posts bruts, manifest) sans rien écrire."""
    sortie = sortie or dossier / "annotation" / "lots_gold"
    posts = charger_collecte(dossier)
    ids_exclus, textes_exclus, compte = exclusions(dossier, posts)
    ids_lots, textes_lots, compte["lots_existants"] = lots_existants(sortie)
    compte["deja_en_lot"] = sum(
        1 for p in posts if p["post_id"] in ids_lots or cle_texte(masquer(p["texte"])) in textes_lots)
    filtres = filtrer(posts, ids_exclus, textes_exclus, depuis, ids_lots, textes_lots)
    retenus = dedoublonner(filtres)
    tires = tirer(retenus, taille, nb_lots, avec_contexte, graine)
    lots = {f"lot_gold_{premier + i:02d}": groupe for i, groupe in enumerate(tires)}
    eligibles = {
        "apres_exclusions_et_date": len(filtres),
        "doublons_de_texte_retires": len(filtres) - len(retenus),
        "total": len(retenus),
        "avec_contexte": sum(p["contexte_texte"] is not None for p in retenus),
    }
    man = manifest(lots, graine, taille, avec_contexte, compte, eligibles, depuis)
    return lots, man


def ecrire(dossier: Path, sortie: Path, taille: int, nb_lots: int, avec_contexte: int, graine: int,
           depuis: datetime = DATE_MIN, premier: int = PREMIER) -> dict:
    lots, man = construire(dossier, taille, nb_lots, avec_contexte, graine,
                           sortie=sortie, depuis=depuis, premier=premier)
    cibles = [sortie / f"{nom}.jsonl" for nom in lots] + [sortie / nom_manifest(premier, nb_lots)]
    existants = [c.name for c in cibles if c.exists()]
    if existants:
        raise SystemExit("Fichiers déjà présents, rien n'est écrit : " + ", ".join(existants)
                         + ". Changer --premier ou --sortie.")
    sortie.mkdir(parents=True, exist_ok=True)
    for nom, posts in lots.items():
        with (sortie / f"{nom}.jsonl").open("x", encoding="utf-8") as f:
            for p in posts:
                f.write(json.dumps(ligne_lot(p, nom), ensure_ascii=False) + "\n")
    with (sortie / nom_manifest(premier, nb_lots)).open("x", encoding="utf-8") as f:
        f.write(json.dumps(man, ensure_ascii=False, indent=2) + "\n")
    return man


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True, type=Path, help="dossier du corpus (hors dépôt)")
    ap.add_argument("--taille", type=int, default=TAILLE, help="posts par lot")
    ap.add_argument("--lots", type=int, default=NB_LOTS, help="nombre de lots")
    ap.add_argument("--avec-contexte", type=int, default=AVEC_CONTEXTE, help="posts avec contexte, sur l'ensemble des lots")
    ap.add_argument("--graine", type=int, default=GRAINE)
    ap.add_argument("--depuis", type=parse_depuis, default=DATE_MIN, metavar="DATE",
                    help="date ou date-heure ISO 8601 minimale (défaut : 2026-10-01 UTC)")
    ap.add_argument("--premier", type=parse_premier, default=PREMIER, help="numéro du premier lot (défaut : 1)")
    ap.add_argument("--sortie", type=Path, help="dossier de sortie (défaut : <corpus>/annotation/lots_gold)")
    args = ap.parse_args(argv)
    sortie = args.sortie or args.corpus / "annotation" / "lots_gold"
    man = ecrire(args.corpus, sortie, args.taille, args.lots, args.avec_contexte, args.graine,
                 depuis=args.depuis, premier=args.premier)
    print(json.dumps(man, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
