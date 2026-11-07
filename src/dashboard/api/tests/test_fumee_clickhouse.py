"""Test de fumée sur un ClickHouse jetable peuplé par `outils/donnees_synthetiques.py`.

Ignoré sans `CLICKHOUSE_TEST_PORT` (ex. 18223), et ignoré aussi si ce port ne répond pas sur
127.0.0.1. Mot de passe : `CLICKHOUSE_PASSWORD` (compte dashboard).
"""

import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import calculs as k
import donnees
from camps import charger_lexique
from config import depuis_env
from donnees import ErreurBase, lire
from modele import construire

PORT = os.environ.get("CLICKHOUSE_TEST_PORT")
pytestmark = pytest.mark.skipif(not PORT, reason="CLICKHOUSE_TEST_PORT non défini")
OUTIL = Path(__file__).resolve().parents[1] / "outils" / "donnees_synthetiques.py"


def _cfg(port=None):
    return depuis_env({"CLICKHOUSE_HOST": "127.0.0.1", "CLICKHOUSE_PORT": str(port or PORT),
                       "CLICKHOUSE_PASSWORD": os.environ.get("CLICKHOUSE_PASSWORD", "dashboard-dev"),
                       "LEXIQUE_DIR": os.environ.get("LEXIQUE_DIR", "/nonexistent")})


@pytest.fixture(scope="module", autouse=True)
def base_normale(tmp_path_factory):
    try:  # port fermé : ignoré, pas en erreur. Un échec plus loin (générateur, identifiants) reste une erreur.
        socket.create_connection(("127.0.0.1", int(PORT)), timeout=2).close()
    except OSError as exc:
        pytest.skip(f"ClickHouse injoignable sur 127.0.0.1:{PORT} ({type(exc).__name__})")
    lex = tmp_path_factory.mktemp("lex")
    subprocess.run(
        [sys.executable, str(OUTIL), "--port", PORT, "--scenario", "normal", "--jours", "35", "--lexique-out", str(lex)],
        check=True,
    )
    os.environ["LEXIQUE_DIR"] = str(lex)


@pytest.mark.parametrize("code", ["24h", "7j", "30j", "tout"])
def test_lecture_et_calcul(code):
    cfg = _cfg()
    now = datetime.now(timezone.utc)
    etat = donnees.etat_base(cfg)
    bornes = k.bornes(code, now, etat.premiere)
    vue = construire(lire(cfg, bornes, etat), charger_lexique(cfg.lexique_dir), 20, 5, 30, now)
    assert not vue.periode_vide and vue.pipeline.nb_posts > 0 and vue.candidats
    assert len(bornes.tranches) <= 400 and vue.position.etat == "ok"
    assert (vue.position_precedente is None) == (code == "tout")
    assert vue.croisements.scoreur == "lexique-v1" and vue.croisements.themes and vue.croisements.emotions
    assert vue.adjectifs is not None and vue.adjectifs.scoreur == "lexique-v1" and vue.adjectifs.lignes
    assert len(vue.serie_camps) == len(bornes.tranches) and any(t["droite"]["contre"] for t in vue.serie_camps)


def test_catalogue_lu():
    disponible, liste = donnees.evenements(_cfg())
    assert disponible and len(liste) == 5 and all(e.titre.startswith("[Simulation]") for e in liste)
    assert liste == sorted(liste, key=lambda e: e.date, reverse=True)


def test_erreur_de_connexion():
    with pytest.raises(ErreurBase):
        donnees.etat_base(_cfg(port=1))
