from datetime import datetime, timezone

import calculs as k
from calculs import PERIODES
from camps import camps_des_candidats, charger_lexique, nom_depuis_id, trouver
from config import depuis_env
from donnees import Brut, EtatBase
from modele import construire

T0 = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
YAML = """
version: 1
entites:
  - {id: le pen, type: candidat, camp: null}
  - {id: alpha, nom: "Alpha <b>", type: candidat, camp: gauche}
  - {id: beta, type: candidat, camp: droite}
  - {id: gamma, type: candidat, camp: bizarre}
  - {id: parti x, type: parti, camp: gauche}
"""


def lexique(tmp_path, texte=YAML):
    (tmp_path / "entites.yaml").write_text(texte, encoding="utf-8")
    return charger_lexique(tmp_path)


def test_camp_null_inconnu_et_nom_par_defaut(tmp_path):
    lx = lexique(tmp_path)
    assert trouver(lx, "le pen").camp is None and trouver(lx, "le pen").nom == "Le Pen"
    assert trouver(lx, "gamma").camp is None and any("camp inconnu" in a for a in lx.avertissements)
    assert camps_des_candidats(lx) == {"alpha": "gauche", "beta": "droite"}  # partis exclus de la barre
    assert trouver(lx, "absent").type == "autre"
    assert nom_depuis_id("braun-pivet") == "Braun-Pivet"


def test_lexique_illisible(tmp_path):
    lx = charger_lexique(tmp_path / "nulle-part")
    assert not lx.charge and lx.entites == {}


def _brut(rows, premiere=None):
    """Brut d'une période de 24 h qui se termine à T0 (les lignes à T0 tombent dans la période)."""
    b = k.bornes("24h", T0, None)
    return Brut(bornes=b, etat=EtatBase(premiere, None), cibles=rows, cibles_precedentes=[], posts=[], themes=[], pipeline=[])


def test_tous_camps_null_donne_aucun_camp_et_non_classe(tmp_path):
    lx = lexique(tmp_path, "entites:\n  - {id: a, type: candidat, camp: null}\n  - {id: b, type: candidat, camp: null}\n")
    rows = [(T0, "a", "pour", 30), (T0, "b", "contre", 30)]
    v = construire(_brut(rows), lx, 5, 5, 30, T0)
    assert v.position.etat == "aucun_camp" and v.non_classes_evalues == 60


def test_etats_vide_et_peu_de_donnees(tmp_path):
    lx = lexique(tmp_path)
    v = construire(_brut([]), lx, 20, 5, 30, T0)
    assert v.base_vide and v.periode_vide
    v2 = construire(_brut([(T0, "alpha", "pour", 3), (T0, "beta", "pour", 3)]), lx, 20, 5, 30, T0)
    assert v2.position.etat == "insuffisant" and v2.position.manquants == {"gauche": 17, "droite": 17}


def test_periodes_et_repli_sur_valeurs_invalides():
    assert PERIODES == ("24h", "7j", "30j", "tout")
    cfg = depuis_env({"DASHBOARD_SEUIL_DEFAUT": "abc", "CLICKHOUSE_PORT": "x"})
    assert cfg.seuil_defaut == 20 and cfg.clickhouse_port == 8123
