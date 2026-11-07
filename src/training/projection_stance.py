"""Projection des étiquettes de stance : `mention` est regroupée avec `neutre` (option).

Une projection n'est pas un changement de schéma. `annotation/schema.yaml` reste la source unique
des étiquettes, et les données d'origine ne sont jamais modifiées : les fonctions renvoient de
nouvelles valeurs. Elles ne servent que si l'option `--stance-regroupe-neutre` est donnée à
`annotation.export` ou à `modele.entrainer`.

Bibliothèque standard seulement. Module partagé par `annotation/` et `modele/` : ces deux paquets
ne s'importent pas entre eux, et ce module ne dépend d'aucun des deux.
"""
from __future__ import annotations

FUSIONS_STANCE = {"mention": "neutre"}


def regrouper_stance(stance: str | None) -> str | None:
    """`mention` devient `neutre`. Toute autre valeur, y compris None, est renvoyée telle quelle."""
    return FUSIONS_STANCE.get(stance, stance)


def regrouper_cibles(cibles: list[dict] | None) -> list[dict]:
    """Nouvelle liste de cibles, stance projetée. Les dictionnaires d'origine ne changent pas."""
    return [{**c, "stance": regrouper_stance(c.get("stance"))} for c in cibles or []]


def regrouper_lignes(lignes: list[dict]) -> list[dict]:
    """Nouvelles lignes d'export, cibles projetées. Une ligne sans cibles (None) est recopiée telle quelle."""
    sortie = []
    for ligne in lignes:
        if ligne.get("cibles") is None:
            sortie.append(dict(ligne))
        else:
            sortie.append({**ligne, "cibles": regrouper_cibles(ligne["cibles"])})
    return sortie


def regrouper_etiquettes(etiquettes: list[str]) -> list[str]:
    """Classes après fusion : les classes fusionnées disparaissent, l'ordre du schéma est conservé."""
    return [e for e in etiquettes if e not in FUSIONS_STANCE]
