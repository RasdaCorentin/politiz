"""Scoreur provisoire `lexique-v1` (docs/technique/contrats-poc.md).

Les règles viennent de `ressources/lexique/*.yaml` (variable `LEXIQUE_DIR`), lues comme des
données. Le lexique se charge une fois par processus. `scorer(texte)` est une fonction pure ;
`scorer_serie` en est la version vectorisée pour un `pandas_udf`.

Les adjectifs viennent d'un lexique fermé (`adjectifs.yaml`) : formes fléchies écrites en
entier, cherchées en mots entiers. Aucun autre mot du texte ne sort du scoreur (slide 5).

Entrée : texte nettoyé (minuscules, sans accents, URL et @handles masqués).
"""
from __future__ import annotations

import functools
import os
import re
from dataclasses import dataclass, field

import pandas as pd
import yaml

import modeles as mdl

SCOREUR = "lexique-v1"
CONFIANCES_UTILES = ("haute", "moyenne")
_RANG = {"haute": 2, "moyenne": 1, "basse": 0}
NEGATIVES = ("colere", "degout", "peur", "tristesse")

_HANDLE = re.compile(r"@[a-z0-9][a-z0-9._\-]*")


class LexiqueError(ValueError):
    """Fichier du lexique mal formé."""


@dataclass
class Lexique:
    alias: dict[str, dict]            # forme -> {entite, ambigu}
    alias_sur_re: re.Pattern          # alias non ambigus seulement
    regles: list[dict]                # règles de stance, motif compilé dans `_re`
    themes: list[dict]
    emotions: list[dict]
    ids: set[str] = field(default_factory=set)
    adjectifs: dict[str, str] = field(default_factory=dict)   # forme -> adjectif affiché
    adjectifs_re: re.Pattern = re.compile(r"(?!)x")            # formes des adjectifs non ambigus


def _alternance(formes) -> str:
    ordre = sorted(set(formes), key=len, reverse=True)
    if not ordre:
        return r"(?!)x"
    return "(?:" + "|".join(re.escape(f) for f in ordre) + ")"


def _lire(dossier: str, nom: str) -> dict:
    with open(os.path.join(dossier, nom), encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise LexiqueError(f"{nom} : mapping attendu")
    return data


def charger_adjectifs(dossier: str) -> dict[str, str]:
    """Formes des adjectifs non ambigus -> adjectif affiché. Une forme appartient à un seul
    adjectif ; un adjectif `ambigu` n'est jamais compté (README du lexique)."""
    liste = _lire(dossier, "adjectifs.yaml").get("adjectifs")
    if not isinstance(liste, list):
        raise LexiqueError("clé 'adjectifs' (liste) attendue")
    formes: dict[str, str] = {}
    vues: dict[str, str] = {}
    for a in liste:
        nom, fl = a.get("adjectif"), a.get("formes")
        if not nom or not isinstance(fl, list) or not fl:
            raise LexiqueError(f"adjectif mal formé : {a!r}")
        for f in fl:
            if f in vues:
                raise LexiqueError(f"forme {f!r} dans {vues[f]!r} et {nom!r}")
            vues[f] = nom
            if not a.get("ambigu"):
                formes[f] = nom
    return formes


def charger_lexique(dossier: str) -> Lexique:
    ent = _lire(dossier, "entites.yaml").get("entites")
    reg = _lire(dossier, "stance.yaml").get("regles")
    the = _lire(dossier, "themes.yaml").get("themes")
    emo = _lire(dossier, "emotions.yaml").get("emotions")
    for nom, val in (("entites", ent), ("regles", reg), ("themes", the), ("emotions", emo)):
        if not isinstance(val, list):
            raise LexiqueError(f"clé {nom!r} (liste) attendue")
    alias, ids = {}, set()
    for e in ent:
        ids.add(e["id"])
        for a in e["alias"]:
            alias[a["forme"]] = {"entite": e["id"], "ambigu": bool(a.get("ambigu"))}
    tous = _alternance(alias)
    regles = []
    for r in reg:
        r = dict(r)
        r["_re"] = re.compile(r["motif"].replace("{ENTITE}", tous))
        regles.append(r)
    themes = [{"theme": t["theme"],
               "termes": [(re.compile(m["motif"]), m["confiance"]) for m in t["termes"]]}
              for t in the]
    emotions = [{"emotion": e["emotion"],
                 "marqueurs": [(re.compile(m["motif"]), m["confiance"]) for m in e["marqueurs"]]}
                for e in emo]
    adjectifs = charger_adjectifs(dossier)
    return Lexique(alias, re.compile(r"\b" + _alternance(
        [f for f, v in alias.items() if not v["ambigu"]]) + r"\b"), regles, themes, emotions, ids,
        adjectifs, re.compile(r"\b" + _alternance(adjectifs) + r"\b"))


@functools.lru_cache(maxsize=None)
def _lexique_de(dossier: str) -> Lexique:
    return charger_lexique(dossier)


def lexique() -> Lexique:
    """Lexique du processus (chargé au premier appel, `LEXIQUE_DIR`)."""
    return _lexique_de(os.environ.get("LEXIQUE_DIR", "/opt/lexique"))


# --- briques ---------------------------------------------------------------------
def entites_citees(lex: Lexique, texte: str) -> set[str]:
    """Entités citées par un alias non ambigu, hors @handles."""
    sans = _HANDLE.sub(" ", texte)
    return {lex.alias[m.group(0)]["entite"] for m in lex.alias_sur_re.finditer(sans)}


def adjectifs_du_texte(lex: Lexique, texte: str) -> list[str]:
    """Adjectifs du lexique présents dans le texte, hors @handles : chacun une fois, triés."""
    sans = _HANDLE.sub(" ", texte)
    return sorted({lex.adjectifs[m.group(0)] for m in lex.adjectifs_re.finditer(sans)})


def declenchements(lex: Lexique, texte: str) -> list[dict]:
    """Toutes les règles de stance déclenchées, quelle que soit leur confiance.

    `cibles` : entités visées ; `camp` : la règle vise un groupe, pas une entité.
    Un alias ambigu capturé par une règle de stance vise son entité : le contexte de la règle
    (verbe de vote, « démission de »…) lève l'ambiguïté. Une règle `co_mentionnee` sans entité
    citée a des `cibles` vides et `camp` faux : elle ne décide rien.
    """
    sans = _HANDLE.sub(" ", texte)
    citees = None
    sortie = []
    for r in lex.regles:
        ms = list(r["_re"].finditer(sans))
        if not ms:
            continue
        cible, cibles, camp = r["cible"], set(), False
        if cible == "entite_capturee":
            for m in ms:
                info = lex.alias.get(m.group("cible"))
                if info:  # la règle désambiguïse l'alias (« je ne vote plus PS »)
                    cibles.add(info["entite"])
        elif cible == "co_mentionnee":
            if citees is None:
                citees = entites_citees(lex, texte)
            cibles = set(citees)
        elif cible in ("camp", "groupe-politique"):
            camp = True
        elif cible in lex.ids:
            cibles = {cible}
        sortie.append({"regle": r["id"], "stance": r["stance"], "confiance": r["confiance"],
                       "cibles": sorted(cibles), "camp": camp})
    return sortie


def _trancher(hits: list[tuple[str, str]]) -> tuple[str, str]:
    """(stance, confiance) d'une cible à partir de ses règles. Aucune règle : non_evalue."""
    if not hits:
        return "non_evalue", "aucune"
    stances = {s for s, _ in hits}
    if {"pour", "contre"} <= stances:
        stance = "ambigu"
    elif "pour" in stances or "contre" in stances:
        stance = "pour" if "pour" in stances else "contre"
    else:
        stance = next(s for s in ("ambigu", "mention", "neutre") if s in stances)
    conf = max([c for s, c in hits if s == stance] or [c for _, c in hits], key=_RANG.get)
    return stance, conf


def _emotion(lex: Lexique, texte: str) -> str:
    meilleure, rang = "non_evalue", -1
    for e in lex.emotions:
        for motif, conf in e["marqueurs"]:
            if conf in CONFIANCES_UTILES and _RANG[conf] > rang and motif.search(texte):
                meilleure, rang = e["emotion"], _RANG[conf]
    return meilleure


def _themes(lex: Lexique, texte: str) -> list[str]:
    trouves = [t["theme"] for t in lex.themes
               if any(c in CONFIANCES_UTILES and m.search(texte) for m, c in t["termes"])]
    return trouves or ["autre"]


def deriver_sentiment(hits: list[dict], emotion: str) -> str:
    """Règle de dérivation du sentiment ; `hits` = règles de stance décisives."""
    pour = sum(h["stance"] == "pour" for h in hits)
    contre = sum(h["stance"] == "contre" for h in hits)
    if pour or contre:
        return "positif" if pour > contre else "negatif" if contre > pour else "neutre"
    if emotion == "joie":
        return "positif"
    if emotion in NEGATIVES:
        return "negatif"
    if any(h["stance"] in ("neutre", "mention", "ambigu") for h in hits):
        return "neutre"
    return "non_evalue"


def _analyser(texte: str, lex: Lexique) -> dict:
    """Étapes lexicales : cibles et règles utiles, émotion, thèmes, adjectifs. Sans modèle."""
    utiles = [h for h in declenchements(lex, texte)
              if h["confiance"] in CONFIANCES_UTILES and (h["cibles"] or h["camp"])]
    par_cible: dict[str, list[tuple[str, str]]] = {e: [] for e in entites_citees(lex, texte)}
    camp = []
    for h in utiles:
        for e in h["cibles"]:
            par_cible.setdefault(e, []).append((h["stance"], h["confiance"]))
        if h["camp"]:
            camp.append((h["stance"], h["confiance"]))
    if par_cible:
        cibles = [dict(zip(("entite", "stance", "confiance"), (e, *_trancher(par_cible[e]))))
                  for e in sorted(par_cible)]
    else:  # aucune entité : une cible nulle, stance éventuelle d'une règle de camp
        cibles = [dict(zip(("entite", "stance", "confiance"), (None, *_trancher(camp))))]
    emotion = _emotion(lex, texte)
    themes = _themes(lex, texte)
    # filtre fin : fixé par le lexique, avant tout modèle
    retenu = (any(c["entite"] is not None for c in cibles)
              or themes != ["autre"] or emotion != "non_evalue")
    return {"cibles": cibles, "utiles": utiles, "emotion": emotion, "themes": themes,
            "adjectifs": adjectifs_du_texte(lex, texte), "retenu": retenu}


def _sortie(analyse: dict, stance_modele: bool) -> dict:
    """Sortie du scoreur. Avec un modèle de stance, le sentiment se dérive d'une voix par cible
    (stance finale) et des règles de camp ; sans modèle, des règles décisives, comme avant.
    `retenu` ne dépend jamais des modèles : c'est le filtre fin du lexique."""
    if stance_modele:
        hits = ([{"stance": c["stance"]} for c in analyse["cibles"] if c["entite"] is not None]
                + [h for h in analyse["utiles"] if h["camp"]])
    else:
        hits = analyse["utiles"]
    return {"cibles": analyse["cibles"],
            "sentiment": deriver_sentiment(hits, analyse["emotion"]),
            "emotion": analyse["emotion"], "themes": analyse["themes"],
            "adjectifs": analyse["adjectifs"], "retenu": analyse["retenu"]}


def _appliquer_modeles(analyses: list[dict], textes: list[str], modeles: mdl.Modeles) -> None:
    """Remplace, par lot, la stance de chaque cible détectée et l'émotion du post (runs CamemBERT actifs)."""
    if modeles.stance is not None:
        paires = [(i, c) for i, a in enumerate(analyses) for c in a["cibles"] if c["entite"] is not None]
        if paires:
            sorties = mdl.predire(modeles, "stance", [textes[i] for i, _ in paires],
                                  [c["entite"] for _, c in paires])
            for (_, c), (etiquette, confiance) in zip(paires, sorties):
                c["stance"], c["confiance"] = etiquette, confiance
    if modeles.emotion is not None:
        sorties = mdl.predire(modeles, "emotion", textes)
        for a, (etiquette, _) in zip(analyses, sorties):
            a["emotion"] = etiquette


def libelle_scoreur(modeles: mdl.Modeles | None = None) -> str:
    """Valeur de `scoreur` : `lexique-v1` sans modèle actif, sinon `camembert:` et les runs actifs."""
    if modeles is None or not modeles.actifs:
        return SCOREUR
    return "camembert:" + "+".join(modeles.noms())


def scorer(texte: str, lex: Lexique | None = None) -> dict:
    """Texte nettoyé -> {cibles, sentiment, emotion, themes, adjectifs, retenu} (fonction pure, sans modèle)."""
    lex = lex or lexique()
    return _sortie(_analyser(texte or "", lex), stance_modele=False)


def scorer_serie(textes: pd.Series, modeles: mdl.Modeles | None = None) -> pd.DataFrame:
    """Version vectorisée pour `pandas_udf` (schéma Spark : `job.SCHEMA_SCORE`).

    Sans modèle actif, le résultat est celui de `scorer`, texte par texte. Avec un modèle, son
    inférence se fait sur tout le lot, une seule fois."""
    lex = lexique()
    textes = [t or "" for t in textes]
    analyses = [_analyser(t, lex) for t in textes]
    actifs = modeles is not None and modeles.actifs
    if actifs:
        _appliquer_modeles(analyses, textes, modeles)
    stance_modele = modeles is not None and modeles.stance is not None
    lignes = [_sortie(a, stance_modele) for a in analyses]
    return pd.DataFrame(lignes, columns=["cibles", "sentiment", "emotion", "themes", "adjectifs", "retenu"])
