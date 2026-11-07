"""Lecture de `entites.yaml` (donnée du lexique) : noms, types et camps des entités.

Le fichier est une donnée en lecture seule, partagée avec le job Spark. Aucun import de code d'un
autre dossier de `src/`. Un camp absent (`null`) place l'entité dans « non classé ».
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

CAMPS = ("gauche", "centre", "droite")
LIBELLE_CAMP = {"gauche": "Gauche", "centre": "Centre", "droite": "Droite", None: "Non classé"}
TYPES = ("candidat", "parti")


@dataclass(frozen=True, slots=True)
class Entite:
    id: str
    nom: str
    type: str  # candidat | parti | autre
    camp: str | None  # gauche | centre | droite | None


@dataclass(frozen=True, slots=True)
class Lexique:
    entites: dict[str, Entite] = field(default_factory=dict)
    avertissements: tuple[str, ...] = ()
    charge: bool = True  # False : fichier introuvable ou illisible


_MOT = re.compile(r"(^|[\s\-'’])(\w)")


def nom_depuis_id(id_: str) -> str:
    """Id en majuscules initiales : `le pen` donne `Le Pen`, `braun-pivet` donne `Braun-Pivet`."""
    return _MOT.sub(lambda m: m.group(1) + m.group(2).upper(), " ".join(id_.split()))


def _lire(chemin: Path) -> Lexique:
    try:
        brut = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return Lexique(avertissements=(f"{chemin.name} illisible ({type(exc).__name__})",), charge=False)
    liste = brut.get("entites") if isinstance(brut, dict) else brut
    if not isinstance(liste, list):
        return Lexique(avertissements=(f"{chemin.name} : liste « entites » absente",), charge=False)
    entites: dict[str, Entite] = {}
    avertissements: list[str] = []
    for i, item in enumerate(liste):
        if not isinstance(item, dict) or not str(item.get("id", "")).strip():
            avertissements.append(f"entrée {i} sans id ignorée")
            continue
        id_ = " ".join(str(item["id"]).split())
        camp = item.get("camp")
        camp = str(camp).strip().lower() if camp is not None else None
        if camp not in CAMPS:
            if camp not in (None, "", "null"):
                avertissements.append(f"camp inconnu pour une entité : traité comme non classé ({camp!r})")
            camp = None
        nom = " ".join(str(item.get("nom") or "").split()) or nom_depuis_id(id_)
        entites[id_] = Entite(id=id_, nom=nom, type=str(item.get("type") or "autre").strip().lower(), camp=camp)
    return Lexique(entites=entites, avertissements=tuple(avertissements))


@lru_cache(maxsize=4)
def _lire_si_modifie(chemin: str, mtime_ns: int) -> Lexique:  # noqa: ARG001 (mtime_ns sert de clé)
    return _lire(Path(chemin))


def charger_lexique(dossier: Path) -> Lexique:
    """Charge `entites.yaml` ; relu quand le fichier change (montage en lecture seule)."""
    chemin = dossier / "entites.yaml"
    try:
        mtime = chemin.stat().st_mtime_ns
    except OSError:
        return Lexique(avertissements=(f"{chemin.name} introuvable",), charge=False)
    return _lire_si_modifie(str(chemin), mtime)


def trouver(lexique: Lexique, id_: str) -> Entite:
    """Entité du lexique, ou entité inconnue (type `autre`, non classée) : un id nouveau ne casse rien."""
    return lexique.entites.get(id_) or Entite(id=id_, nom=nom_depuis_id(id_), type="autre", camp=None)


def camps_des_candidats(lexique: Lexique) -> dict[str, str]:
    """`id -> camp` des seuls candidats rattachés à un camp : l'entrée de la barre d'opinion."""
    return {e.id: e.camp for e in lexique.entites.values() if e.type == "candidat" and e.camp in CAMPS}


def candidats_du_camp(lexique: Lexique, camp: str) -> list[Entite]:
    return sorted((e for e in lexique.entites.values() if e.type == "candidat" and e.camp == camp), key=lambda e: e.nom)
