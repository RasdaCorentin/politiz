"""Sérialisation d'une `Vue` en JSON `tableau` v4, et du catalogue `evenements` v1 (formats définis dans docs/technique/contrats-poc.md).

Seul module qui fixe les noms de clés servies. Aucune formule ici : les nombres sortent bruts,
la page les formate. Les entrées ne contiennent ni texte de post ni identifiant d'auteur : la
sortie n'en contient donc aucun.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import calculs as k
from camps import Lexique, trouver
from calculs import PERIODES
from config import Config
from modele import Vue

SCHEMA_VERSION = 4
SCHEMA_EVENEMENTS = 1
CAMPS = k.CAMPS
LIBELLE_THEME = {
    "economie": "Économie",
    "social-retraites": "Social et retraites",
    "immigration": "Immigration",
    "securite": "Sécurité",
    "ecologie": "Écologie",
    "europe-international": "Europe et international",
    "institutions": "Institutions",
    "sante-education": "Santé et éducation",
    "campagne-sondages": "Campagne et sondages",
    "autre": "Autre",
}


def iso(t: datetime | None) -> str | None:
    """Heure ISO 8601 UTC, forme `AAAA-MM-JJThh:mm:ssZ`."""
    if t is None:
        return None
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _libelle_theme(theme: str) -> str:
    return LIBELLE_THEME.get(theme, theme.replace("-", " ").capitalize())


def _ligne(ligne: k.LigneClassement, lexique: Lexique) -> dict[str, Any]:
    c = ligne.comptes
    entite = trouver(lexique, ligne.entite)
    return {
        "entite": ligne.entite,
        "nom": entite.nom,
        "camp": entite.camp,
        "rang": ligne.rang,
        "pour": c.pour,
        "contre": c.contre,
        "neutre": c.neutre,
        "mention": c.mention,
        "ambigu": c.ambigu,
        "non_evalue": c.non_evalue,
        "cites": c.cites,
        "evalues": c.evalues,
        "indice": c.indice,
        "couverture": c.couverture,
    }


def _camp(r: k.ResultatCamp) -> dict[str, Any]:
    return {"pour": r.pour, "contre": r.contre, "evalues": r.evalues, "indice": r.indice, "candidats": list(r.candidats)}


def _bande(p: k.Position | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {"etat": p.etat, "valeur": p.valeur, "bas": p.bas, "haut": p.haut}


def _barre(v: Vue) -> dict[str, Any]:
    p = v.position
    return {
        **_bande(p),
        "seuil": p.seuil,
        "manquants": dict(p.manquants),
        "camps": {c: _camp(getattr(p, c)) for c in CAMPS},
        "precedente": _bande(v.position_precedente),
    }


def _croisements(c: k.Croisements) -> dict[str, Any]:
    """Section `croisements`. Thèmes : `posts`. Émotions : `occurrences`, car un post qui porte k thèmes
    compte k fois. Libellé de thème : `_libelle_theme`, la fonction de `themes`."""
    return {
        "scoreur": c.scoreur,
        "themes": [{"entite": e, "theme": t, "libelle": _libelle_theme(t), "posts": n} for e, t, n in c.themes],
        "emotions": [{"entite": e, "emotion": m, "occurrences": n} for e, m, n in c.emotions],
    }


def _adjectifs(a: k.Adjectifs | None) -> dict[str, Any] | None:
    """Section `adjectifs` (v4) : `null` quand la table n'existe pas, sinon le scoreur retenu, la
    couverture (`null` sans adjectif sur la période) et les lignes."""
    if a is None:
        return None
    couverture = None
    if a.debut is not None:
        couverture = {"debut": iso(a.debut), "fin": iso(a.fin), "posts_hors": a.posts_hors}
    return {
        "scoreur": a.scoreur,
        "couverture": couverture,
        "lignes": [{"entite": e, "stance": s, "adjectif": m, "posts": n} for e, s, m, n in a.lignes],
    }


def serialiser_evenements(disponible: bool, liste, genere: datetime) -> dict[str, Any]:
    """Catalogue `evenements` v1 : faits datés (titre, catégorie, source, lien), du plus récent au plus ancien."""
    return {
        "schema_version": SCHEMA_EVENEMENTS,
        "generated_at": iso(genere),
        "disponible": disponible,
        "evenements": [
            {"id": e.id, "date": iso(e.date), "titre": e.titre, "categorie": e.categorie, "source": e.source, "lien": e.lien}
            for e in liste
        ],
    }


def serialiser(v: Vue, cfg: Config, genere: datetime) -> dict[str, Any]:
    """`Vue` et configuration vers le dictionnaire JSON v4. `genere` : instant de lecture de la base."""
    b = v.bornes
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": iso(genere),
        "bandeau": cfg.bandeau or None,
        "periode": {
            "code": b.code,
            "debut": iso(b.debut),
            "fin": iso(b.fin),
            "pas_min": b.pas_min,
            "seuil": v.seuil,
            "seuil_defaut": cfg.seuil_defaut,
            "periodes": list(PERIODES),
            "premiere_donnee": iso(v.premiere),
        },
        "etat": {
            "base_vide": v.base_vide,
            "periode_vide": v.periode_vide,
            "fraicheur": v.fraicheur.etat,
            "derniere_maj": iso(v.derniere_maj),
            "fraicheur_ok_min": cfg.fraicheur_ok_min,
            "fraicheur_alerte_min": cfg.fraicheur_alerte_min,
            "lexique_charge": v.lexique.charge,
            "hors_lexique": v.hors_lexique,
            "avertissements": list(v.lexique.avertissements),
        },
        "pipeline": {"posts": v.pipeline.nb_posts, "latence_moyenne_s": v.pipeline.latence_moyenne_s},
        "tranches": [iso(t) for t in b.tranches],
        "volume": list(v.volume),
        "ton": {
            "positif": v.ton.positif,
            "neutre": v.ton.neutre,
            "negatif": v.ton.negatif,
            "non_evalue": v.ton.non_evalue,
        },
        "serie_ton": [{"positif": t.positif, "neutre": t.neutre, "negatif": t.negatif} for t in v.serie_ton],
        "emotions": {e: v.emotions.get(e, 0) for e in k.EMOTIONS},
        "emotions_non_evaluees": v.emotions_sans,
        "themes": [{"theme": t, "libelle": _libelle_theme(t), "posts": n} for t, n in v.themes],
        "candidats": [_ligne(x, v.lexique) for x in v.candidats],
        "partis": [_ligne(x, v.lexique) for x in v.partis],
        "barre": _barre(v),
        "series": {
            e: [{"fin": iso(p.fin), "pour": p.pour, "contre": p.contre, "indice": p.indice} for p in points]
            for e, points in v.series.items()
        },
        "non_classes_evalues": v.non_classes_evalues,
        "croisements": _croisements(v.croisements),
        "serie_camps": v.serie_camps,
        "adjectifs": _adjectifs(v.adjectifs),
    }
