"""Modèles CamemBERT du scoreur : chargement d'un run et prédiction par lots (scoreur à modèles et contrat du modèle : contrats-poc.md).

Un run est un dossier : `model/` (Hugging Face, `save_pretrained`) et `modele.json`. Le module lit
ce dossier et n'importe rien de `src/training/` : l'entrée (nom de la cible, texte) est recopiée de
`modele/donnees.py`, et `tests/test_entree_modele_identique.py` prouve l'identité des jetons.

Aucun texte ni probabilité n'est journalisé. torch et transformers ne sont importés qu'au premier
chargement : le reste du module (et la suite lexicale) fonctionne sans eux.
"""
from __future__ import annotations

import functools
import json
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ENV_STANCE = "MODELE_STANCE_DIR"
ENV_EMOTION = "MODELE_EMOTION_DIR"
TAILLE_LOT = 16
THREADS = 2
SEUIL_HAUTE = 0.8
SEUIL_MOYENNE = 0.5
TACHES = ("stance", "emotion")


class ModeleError(RuntimeError):
    """Run désigné mais illisible, ou mal formé. Le message ne contient aucun texte de post."""


# --------------------------------------------------------------------------- entrée du modèle
# Copie de src/training/modele/donnees.py (normaliser_contrat, nom_cible, entree_modele, jetons).
# Toute modification côté entraînement doit être reportée ici : le test d'identité échoue sinon.
def normaliser_contrat(texte: str) -> str:
    """Étape de nettoyage du job Spark : minuscules, sans accents."""
    decompose = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


NOMS_SPECIAUX = {"gouvernement": "Gouvernement", "groupe-politique": "Groupe politique", "autre": "Autre"}


def nom_cible(identifiant: str) -> str:
    """Nom de repli d'une cible absente de `noms_cibles` (même règle que l'entraînement)."""
    if identifiant in NOMS_SPECIAUX:
        return NOMS_SPECIAUX[identifiant]
    mots = identifiant.split()
    if len(mots) == 1 and "-" not in identifiant and len(identifiant) <= 4:
        return identifiant.upper()
    return " ".join("-".join(p.capitalize() for p in mot.split("-")) for mot in mots)


def entree_modele(texte: str, cible: str | None, noms: dict[str, str],
                  normaliser: bool = False) -> tuple[str, str | None]:
    """(premier segment, second segment) donnés au tokenizer. stance : (nom, texte) ; émotion : (texte, None)."""
    if normaliser:
        texte = normaliser_contrat(texte)
    if cible is None:
        return texte, None
    nom = noms.get(cible) or nom_cible(cible)
    return (normaliser_contrat(nom) if normaliser else nom), texte


def jetons(tokenizer, textes: list[str], cibles: list[str] | None, tache: str, noms: dict[str, str],
           longueur_max: int, normaliser: bool = False) -> list[list[int]]:
    """Identifiants de jetons, sans remplissage. stance : seul le texte est tronqué."""
    if tache not in TACHES:
        raise ValueError(f"tâche inconnue : {tache}")
    if tache == "stance":
        if cibles is None or len(cibles) != len(textes):
            raise ValueError("la stance demande une cible par texte")
        entrees = [entree_modele(t, c, noms, normaliser) for t, c in zip(textes, cibles)]
        enc = tokenizer([a for a, _ in entrees], [b for _, b in entrees],
                        truncation="only_second", max_length=longueur_max)
    else:
        entrees = [entree_modele(t, None, noms, normaliser) for t in textes]
        enc = tokenizer([a for a, _ in entrees], truncation=True, max_length=longueur_max)
    return enc["input_ids"]


def niveau_confiance(probabilite: float) -> str:
    """`haute` (>= 0,8), `moyenne` (>= 0,5), sinon `aucune` (seuils du scoreur à modèles)."""
    if probabilite >= SEUIL_HAUTE:
        return "haute"
    if probabilite >= SEUIL_MOYENNE:
        return "moyenne"
    return "aucune"


# --------------------------------------------------------------------------- runs
def lire_meta(dossier: Path, tache: str) -> dict:
    """Lit et valide `modele.json` d'un run de la tâche attendue. Lève ModeleError sinon."""
    def refus(raison: str) -> ModeleError:
        return ModeleError(f"run {tache} illisible ({dossier}) : {raison}")

    if not dossier.is_dir():
        raise refus("dossier absent")
    if not (dossier / "model").is_dir():
        raise refus("sous-dossier model/ absent")
    try:
        meta = json.loads((dossier / "modele.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise refus("modele.json absent ou illisible") from None
    if not isinstance(meta, dict) or meta.get("tache") != tache:
        raise refus(f"tâche attendue « {tache} »")
    entree = meta.get("entree")
    if (not isinstance(meta.get("etiquettes"), list) or not isinstance(entree, dict)
            or not isinstance(entree.get("longueur_max"), int) or not isinstance(entree.get("normaliser"), bool)):
        raise refus("etiquettes ou entree manquants")
    if not isinstance(meta.get("noms_cibles", {}), dict):
        raise refus("noms_cibles mal formé")
    return meta


class Predicteur:
    """Modèle d'un run tenu en mémoire. Chargé une fois par processus (voir `charger`)."""

    def __init__(self, dossier: Path, tache: str):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        meta = lire_meta(dossier, tache)
        torch.set_num_threads(THREADS)
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(dossier / "model")
            self.modele = AutoModelForSequenceClassification.from_pretrained(dossier / "model")
        except Exception as e:  # le message ne contient que le type d'erreur
            raise ModeleError(f"run {tache} illisible ({dossier}) : {type(e).__name__}") from None
        self.modele.eval()
        self.tache = tache
        self.etiquettes: list[str] = meta["etiquettes"]
        self.longueur_max: int = meta["entree"]["longueur_max"]
        self.normaliser: bool = meta["entree"]["normaliser"]
        self.noms: dict[str, str] = meta.get("noms_cibles", {})

    def predire(self, textes: list[str], cibles: list[str] | None = None,
                taille_lot: int = TAILLE_LOT) -> list[tuple[str, str]]:
        """(étiquette, confiance) par texte, dans l'ordre d'entrée. Lots de `taille_lot`, longueurs voisines."""
        import torch

        if not textes:
            return []
        ids = jetons(self.tokenizer, textes, cibles, self.tache, self.noms, self.longueur_max, self.normaliser)
        ordre = sorted(range(len(ids)), key=lambda i: len(ids[i]))
        sortie: list[tuple[str, str]] = [("", "aucune")] * len(ids)
        pad = self.tokenizer.pad_token_id
        with torch.inference_mode():
            for debut in range(0, len(ordre), taille_lot):
                idx = ordre[debut:debut + taille_lot]
                largeur = max(len(ids[i]) for i in idx)
                entree = torch.full((len(idx), largeur), pad, dtype=torch.long)
                masque = torch.zeros((len(idx), largeur), dtype=torch.long)
                for r, i in enumerate(idx):
                    entree[r, :len(ids[i])] = torch.tensor(ids[i])
                    masque[r, :len(ids[i])] = 1
                logits = self.modele(input_ids=entree, attention_mask=masque).logits
                proba, classe = torch.softmax(logits.float(), dim=-1).max(dim=-1)
                for r, i in enumerate(idx):
                    sortie[i] = (self.etiquettes[int(classe[r])], niveau_confiance(float(proba[r])))
        return sortie


@functools.lru_cache(maxsize=None)
def charger(dossier: str, tache: str) -> Predicteur:
    """Modèle du run, une fois par processus Python (un executor = un jeu de modèles)."""
    return Predicteur(Path(dossier), tache)


@dataclass(frozen=True)
class Modeles:
    """Runs actifs : dossier de la stance et dossier de l'émotion. None : la tâche garde les règles."""
    stance: str | None = None
    emotion: str | None = None

    @staticmethod
    def depuis_env(env=os.environ) -> "Modeles":
        def lire(nom: str) -> str | None:
            return (env.get(nom) or "").strip() or None
        return Modeles(stance=lire(ENV_STANCE), emotion=lire(ENV_EMOTION))

    @property
    def actifs(self) -> bool:
        return self.stance is not None or self.emotion is not None

    def verifier(self) -> None:
        """Contrôle du driver, au démarrage : métadonnées et sous-dossiers. Les poids se chargent dans les executors."""
        for tache, dossier in (("stance", self.stance), ("emotion", self.emotion)):
            if dossier is not None:
                lire_meta(Path(dossier), tache)

    def noms(self) -> list[str]:
        """Noms des runs actifs, stance puis émotion (ex. `stance-20261019-1636`)."""
        return [Path(d).name for d in (self.stance, self.emotion) if d is not None]


def predire(modeles: Modeles, tache: str, textes: list[str], cibles: list[str] | None = None
            ) -> list[tuple[str, str]]:
    """Prédiction du run actif de `tache` : (étiquette, confiance) par texte."""
    dossier = modeles.stance if tache == "stance" else modeles.emotion
    if dossier is None:
        raise ValueError(f"aucun run actif pour la tâche {tache}")
    return charger(dossier, tache).predire(textes, cibles)
