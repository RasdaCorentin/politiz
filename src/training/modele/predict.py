"""Prédicteur CPU : charge un modèle entraîné une fois, prédit par lots, mesure la latence.

C'est le chemin d'inférence que le job Spark reproduira : un modèle chargé une fois par executor,
des lots de textes, des probabilités en sortie. Le dossier d'un run est l'unique contrat :

    <run>/model/        modèle et tokenizer Hugging Face (save_pretrained)
    <run>/modele.json   tâche, étiquettes, gabarit d'entrée, longueur maximale, noms des cibles

Aucun texte n'est journalisé.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np

from . import donnees


class Predicteur:
    """Modèle d'un run, prêt à prédire. `threads` fixe le nombre de threads de calcul de torch ;
    `appareil` est `cpu` (défaut) ou `cuda`."""

    def __init__(self, dossier: Path | str, threads: int | None = None, appareil: str = "cpu"):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if appareil not in ("cpu", "cuda"):
            raise ValueError(f"appareil inconnu : {appareil} (attendu : cpu ou cuda)")
        if appareil == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA demandé, mais aucune carte n'est disponible")
        self.dossier = Path(dossier)
        self.appareil = appareil
        self.meta = json.loads((self.dossier / "modele.json").read_text(encoding="utf-8"))
        if threads:
            torch.set_num_threads(threads)
        self.tokenizer = AutoTokenizer.from_pretrained(self.dossier / "model")
        self.modele = AutoModelForSequenceClassification.from_pretrained(self.dossier / "model").to(appareil)
        self.modele.eval()
        self.etiquettes: list[str] = self.meta["etiquettes"]
        self.tache: str = self.meta["tache"]
        self.longueur_max: int = self.meta["entree"]["longueur_max"]
        self.normaliser: bool = self.meta["entree"]["normaliser"]
        # Absente des runs antérieurs : leur entrée reste celle d'origine.
        self.nettoyer: bool = bool(self.meta["entree"].get("nettoyer", False))
        self.noms: dict[str, str] = self.meta.get("noms_cibles", {})

    def encoder(self, textes: list[str], cibles: list[str] | None = None,
                normaliser: bool | None = None) -> list[list[int]]:
        """Identifiants de jetons, sans remplissage. stance : paire (nom de la cible, texte)."""
        normaliser = self.normaliser if normaliser is None else normaliser
        if self.nettoyer:
            textes = [donnees.preparer_texte(t) for t in textes]
        return donnees.jetons(self.tokenizer, textes, cibles, self.tache, self.noms,
                              self.longueur_max, normaliser)

    def probabilites(self, textes: list[str], cibles: list[str] | None = None, taille_lot: int = 16,
                     normaliser: bool | None = None) -> np.ndarray:
        """Matrice (n, K) de probabilités, dans l'ordre des textes. Les lots regroupent des longueurs
        voisines pour limiter le remplissage ; l'ordre d'entrée est restitué."""
        import torch

        ids = self.encoder(textes, cibles, normaliser)
        ordre = sorted(range(len(ids)), key=lambda i: len(ids[i]))
        sortie = np.zeros((len(ids), len(self.etiquettes)), dtype=np.float32)
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
                logits = self.modele(input_ids=entree.to(self.appareil), attention_mask=masque.to(self.appareil)).logits
                sortie[idx] = torch.softmax(logits.float(), dim=-1).cpu().numpy()
        return sortie

    def predire(self, textes: list[str], cibles: list[str] | None = None, taille_lot: int = 16,
                normaliser: bool | None = None) -> list[dict]:
        """Une prédiction par texte : étiquette, confiance (probabilité maximale) et probabilités.
        La confiance n'est pas calibrée : un seuil se règle sur le gold."""
        proba = self.probabilites(textes, cibles, taille_lot, normaliser)
        sortie = []
        for p in proba:
            k = int(p.argmax())
            sortie.append({"etiquette": self.etiquettes[k], "confiance": float(p[k]),
                           "probabilites": {e: float(v) for e, v in zip(self.etiquettes, p)}})
        return sortie


def mesurer_latence(predicteur: Predicteur, textes: list[str], cibles: list[str] | None = None,
                    threads: tuple[int, ...] = (2, 3), tailles_lot: tuple[int, ...] = (1, 16),
                    n_max: int = 32) -> dict:
    """Temps d'inférence par post, en ms, selon les threads et la taille de lot.

    Mesuré sur le poste courant, sous la charge du moment (indiquée) : un ordre de grandeur pour
    dimensionner les workers, pas une garantie.
    """
    import torch

    textes = textes[:n_max]
    cibles = cibles[:n_max] if cibles else None
    jetons = predicteur.encoder(textes, cibles)
    resultat: dict = {
        "n_posts": len(textes),
        "jetons_moyens": round(float(np.mean([len(x) for x in jetons])), 1),
        "charge_systeme_1min": round(os.getloadavg()[0], 2),
        "ms_par_post": {},
    }
    avant = torch.get_num_threads()
    try:
        for t in threads:
            torch.set_num_threads(t)
            for lot in tailles_lot:
                predicteur.probabilites(textes[:lot], cibles[:lot] if cibles else None, lot)   # échauffement
                debut = time.perf_counter()
                for i in range(0, len(textes), lot):
                    predicteur.probabilites(textes[i:i + lot], cibles[i:i + lot] if cibles else None, lot)
                ms = (time.perf_counter() - debut) * 1000 / len(textes)
                resultat["ms_par_post"][f"threads={t},lot={lot}"] = round(ms, 1)
    finally:
        torch.set_num_threads(avant)
    return resultat
