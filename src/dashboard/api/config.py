"""Configuration par variables d'environnement (liste dans docs/technique/contrats-poc.md)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PERIODE_DEFAUT = "7j"  # périodes admises : calculs.PERIODES (routes du contrat)


def _entier(env: Mapping[str, str], nom: str, defaut: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(env.get(nom, defaut)))
    except (TypeError, ValueError):
        return defaut


def _dossier_lexique(env: Mapping[str, str]) -> Path:
    """`LEXIQUE_DIR`, sinon `/app/lexique` (Docker), sinon le dossier du dépôt (lancement local)."""
    if env.get("LEXIQUE_DIR"):
        return Path(env["LEXIQUE_DIR"])
    docker = Path("/app/lexique")
    if docker.is_dir():
        return docker
    return Path(__file__).resolve().parents[3] / "ressources" / "lexique"  # src/dashboard/api -> racine


@dataclass(frozen=True)
class Config:
    clickhouse_host: str
    clickhouse_port: int
    clickhouse_user: str
    clickhouse_password: str
    clickhouse_db: str
    lexique_dir: Path
    fraicheur_ok_min: int  # sans mise à jour depuis moins de N min : à jour
    fraicheur_alerte_min: int  # jusqu'à N min : en retard ; au-delà : arrêté
    seuil_defaut: int  # posts évalués minimum pour afficher un indice
    bandeau: str  # texte du bandeau d'avertissement (ex. « données synthétiques »)


def depuis_env(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    return Config(
        clickhouse_host=env.get("CLICKHOUSE_HOST", "clickhouse"),
        clickhouse_port=_entier(env, "CLICKHOUSE_PORT", 8123, 1),
        clickhouse_user=env.get("CLICKHOUSE_USER", "dashboard"),
        clickhouse_password=env.get("CLICKHOUSE_PASSWORD", ""),
        clickhouse_db=env.get("CLICKHOUSE_DB", "sae"),
        lexique_dir=_dossier_lexique(env),
        fraicheur_ok_min=_entier(env, "FRAICHEUR_OK_MIN", 5, 1),
        fraicheur_alerte_min=_entier(env, "FRAICHEUR_ALERTE_MIN", 30, 2),
        seuil_defaut=_entier(env, "DASHBOARD_SEUIL_DEFAUT", 20, 1),
        bandeau=env.get("DASHBOARD_BANDEAU", "").strip(),
    )
