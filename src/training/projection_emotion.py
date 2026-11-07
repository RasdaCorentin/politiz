"""Projection des émotions en trois classes : tonalité positive, négative, neutre (option).

Une projection n'est pas un changement de schéma. `annotation/schema.yaml` reste la source unique
des étiquettes (sept émotions), et les données d'origine ne sont jamais modifiées : les fonctions
renvoient de nouvelles valeurs. Elles ne servent que si l'option `--emotion-3-classes` est donnée
à `modele.entrainer` ou à `comparer_gold_silver.py`.

Trois classes, nommées d'après la tonalité du streaming :
- `joie` : tonalité positive (la seule émotion positive du schéma) ;
- `colere` : tonalité négative. Le nom reste celui de l'émotion d'origine : `colere` désigne toute
  émotion négative (colère, dégoût, peur, tristesse) dans cette projection. Les noms sont gardés pour
  que le streaming (`scoring.NEGATIVES`, `deriver_sentiment`) et ClickHouse restent valides sans
  changement ;
- `neutre` : inchangé.

`surprise` est absente de la table : sa polarité n'est pas déterminée, l'exemple est exclu.

Bibliothèque standard seulement.
"""
from __future__ import annotations

REDUCTION_EMOTION = {
    "joie": "joie",
    "colere": "colere",
    "degout": "colere",
    "peur": "colere",
    "tristesse": "colere",
    "neutre": "neutre",
}

def reduire_emotion(valeur: str | None) -> str | None:
    """Valeur projetée. None si la valeur est absente de la table (surprise, None, inconnue)."""
    return REDUCTION_EMOTION.get(valeur)


def reduire_etiquettes(etiquettes: list[str]) -> list[str]:
    """Classes après projection, dans l'ordre d'apparition : avec la liste du schéma, c'est
    `["joie", "colere", "neutre"]`. Les valeurs hors table (surprise) disparaissent."""
    return list(dict.fromkeys(r for r in map(reduire_emotion, etiquettes) if r is not None))
