"""Requêtes de lecture : agrégation par tranche dans ClickHouse, sans faux client réseau.

Un faux client enregistre le texte des requêtes et renvoie des lignes fixes. Le test vérifie que
chaque lecture agrège par tranche (jamais par fenêtre de 5 minutes) et que la période précédente
n'est lue que lorsqu'elle existe.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

import calculs as k
import donnees
from config import depuis_env
from donnees import EtatBase, lire

MAINTENANT = datetime(2026, 10, 19, 10, 2, 30, tzinfo=timezone.utc)


class Resultat:
    def __init__(self, lignes):
        self.result_rows = lignes


class FauxClient:
    def __init__(self, journal, reponses=None):
        self.journal = journal
        self.reponses = reponses or {}

    def query(self, sql, parameters=None):
        sql = " ".join(sql.split())
        self.journal.append((sql, parameters or {}))
        for table, lignes in self.reponses.items():
            if f"FROM {table}" in sql:
                return Resultat(lignes)
        return Resultat([])


@pytest.fixture
def journal(monkeypatch):
    journal = []
    monkeypatch.setattr(donnees, "client", lambda cfg: FauxClient(journal))
    return journal


CFG = depuis_env({})
ETAT = EtatBase(premiere=datetime(2026, 10, 5, 10, 5, tzinfo=timezone.utc), derniere_maj=MAINTENANT)


def test_7j_agrege_par_tranche_de_6_heures_paris(journal):
    lire(CFG, k.bornes("7j", MAINTENANT, ETAT.premiere), ETAT)
    sql = [s for s, _ in journal]
    assert all("GROUP BY fenetre_debut" not in s for s in sql)
    par_tranche = [s for s in sql if "AS tranche" in s]
    assert len(par_tranche) == 4  # cibles, cibles de la période précédente, posts, pipeline
    assert all("INTERVAL 360 MINUTE" in s and "timeZoneOffset(toDateTime(fenetre_debut, 'Europe/Paris'))" in s for s in par_tranche)
    assert sum("FROM themes_fenetre" in s for s in sql) == 1


def test_precedente_lue_pour_les_periodes_et_absente_pour_tout(journal):
    lire(CFG, k.bornes("24h", MAINTENANT, ETAT.premiere), ETAT)
    assert any("fenetre_debut >= %(prec)s" in s for s, _ in journal)
    journal.clear()
    lire(CFG, k.bornes("tout", MAINTENANT, ETAT.premiere), ETAT)
    assert not any("%(prec)s" in s for s, _ in journal)


def test_30j_et_tout_utilisent_les_expressions_de_jour_et_de_semaine(journal):
    lire(CFG, k.bornes("30j", MAINTENANT, ETAT.premiere), ETAT)
    assert all("toStartOfDay(fenetre_debut, 'Europe/Paris')" in s for s, _ in journal if "AS tranche" in s)
    journal.clear()
    lire(CFG, k.bornes("tout", MAINTENANT, datetime(2026, 1, 1, tzinfo=timezone.utc)), ETAT)
    assert all("toMonday(fenetre_debut, 'Europe/Paris')" in s for s, _ in journal if "AS tranche" in s)


def test_plage_perso_bornes_passees_en_parametres_utc_sans_fuseau(journal):
    b = k.bornes("perso", MAINTENANT, ETAT.premiere, (date(2026, 10, 1), date(2026, 10, 3)))
    lire(CFG, b, ETAT)
    _, params = journal[0]
    assert params["debut"] == datetime(2026, 9, 30, 22, 0) and params["fin"] == datetime(2026, 10, 3, 22, 0)
    assert params["debut"].tzinfo is None


def test_tranches_renvoyees_par_clickhouse_converties_en_utc(monkeypatch):
    """`toStartOfDay` renvoie un datetime de Paris ; `toMonday` une date : les deux donnent un instant UTC."""
    b = k.bornes("30j", MAINTENANT, ETAT.premiere)
    paris_minuit = datetime(2026, 10, 18, 0, 0, tzinfo=k.FUSEAU)
    reponses = {"cibles_fenetre": [(paris_minuit, "alice", "pour", 3)]}
    monkeypatch.setattr(donnees, "client", lambda cfg: FauxClient([], reponses))
    brut = lire(CFG, b, ETAT)
    assert brut.cibles == [(datetime(2026, 10, 17, 22, 0, tzinfo=timezone.utc), "alice", "pour", 3)]


def test_toMonday_renvoie_une_date(monkeypatch):
    b = k.bornes("tout", MAINTENANT, datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(donnees, "client", lambda cfg: FauxClient([], {"cibles_fenetre": [(date(2025, 12, 29), "bob", "contre", 2)]}))
    brut = lire(CFG, b, ETAT)
    assert brut.cibles[0][0] == datetime(2025, 12, 28, 23, 0, tzinfo=timezone.utc)


def test_etat_base_table_vide_donne_none(monkeypatch):
    vide = datetime(1970, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(donnees, "client", lambda cfg: FauxClient([], {"pipeline_fenetre": [(vide, vide)]}))
    assert donnees.etat_base(CFG) == EtatBase(premiere=None, derniere_maj=None)


def test_aucune_requete_par_fenetre(journal):
    lire(CFG, k.bornes("30j", MAINTENANT, ETAT.premiere), ETAT)
    assert not any("fenetre_debut" in s.split("GROUP BY")[1] for s, _ in journal if "GROUP BY" in s)


def test_six_heures_renvoyees_comme_heure_murale_de_paris(monkeypatch):
    """Une clé 6 h renvoyée comme heure murale (06:00) vaut 04:00 UTC en octobre (Paris = UTC+2)."""
    b = k.bornes("7j", MAINTENANT, ETAT.premiere)
    murale = datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(donnees, "client", lambda cfg: FauxClient([], {"cibles_fenetre": [(murale, "alice", "pour", 1)]}))
    brut = lire(CFG, b, ETAT)
    assert brut.cibles[0][0] == datetime(2026, 10, 14, 4, 0, tzinfo=timezone.utc)


class FauxCroisements:
    """Répond aux requêtes de croisements selon leur GROUP BY ; les autres requêtes renvoient vide."""

    def __init__(self, journal, scoreurs=(), themes=(), emotions=()):
        self.journal = journal
        self.motifs = {"GROUP BY scoreur": scoreurs, "GROUP BY entite, theme": themes, "GROUP BY entite, emotion": emotions}

    def query(self, sql, parameters=None):
        sql = " ".join(sql.split())
        self.journal.append((sql, parameters or {}))
        for motif, lignes in self.motifs.items():
            if motif in sql:
                return Resultat(list(lignes))
        return Resultat([])


def test_croisements_un_seul_scoreur_le_plus_recent(monkeypatch):
    journal = []
    monkeypatch.setattr(donnees, "client", lambda cfg: FauxCroisements(
        journal,
        scoreurs=[("lexique-v1", MAINTENANT - timedelta(days=2)), ("modele-fictif", MAINTENANT - timedelta(hours=1))],
        themes=[("alice-fictive", "economie", 7)],
        emotions=[("alice-fictive", "colere", 4)],
    ))
    brut = lire(CFG, k.bornes("7j", MAINTENANT, ETAT.premiere), ETAT)
    assert brut.scoreur == "modele-fictif"
    assert brut.croisements_themes == [("alice-fictive", "economie", 7)]
    assert brut.croisements_emotions == [("alice-fictive", "colere", 4)]
    filtrees = [p for s, p in journal if "scoreur = %(scoreur)s" in s]
    assert len(filtrees) == 2 and all(p["scoreur"] == "modele-fictif" for p in filtrees)


def test_croisements_fenetre_vide_ne_lit_ni_themes_ni_emotions(monkeypatch):
    journal = []
    monkeypatch.setattr(donnees, "client", lambda cfg: FauxCroisements(journal))
    brut = lire(CFG, k.bornes("7j", MAINTENANT, ETAT.premiere), ETAT)
    assert brut.scoreur is None and brut.croisements_themes == [] and brut.croisements_emotions == []
    assert not any("scoreur = %(scoreur)s" in s for s, _ in journal)


def test_croisements_agreges_et_bornes_sur_la_periode(monkeypatch):
    journal = []
    monkeypatch.setattr(donnees, "client", lambda cfg: FauxCroisements(journal, scoreurs=[("lexique-v1", MAINTENANT)]))
    b = k.bornes("30j", MAINTENANT, ETAT.premiere)
    lire(CFG, b, ETAT)
    croisements = [(s, p) for s, p in journal if "FROM croisements_fenetre" in s]
    assert len(croisements) == 3  # scoreur, thèmes, émotions
    assert "scoreur != ''" in croisements[0][0]
    for sql, params in croisements:
        assert "fenetre_debut >= %(debut)s AND fenetre_debut < %(fin)s" in sql
        assert params["debut"] == b.debut.replace(tzinfo=None) and params["fin"] == b.fin.replace(tzinfo=None)
        assert "GROUP BY" in sql and ("max(fenetre_debut)" in sql or "sum(nb_posts)" in sql)
        assert "AS tranche" not in sql and "SELECT *" not in sql


class FauxFacultatives:
    """Simule `system.tables` (tables facultatives présentes) et répond aux requêtes d'adjectifs et du catalogue."""

    def __init__(self, journal, presentes=(), scoreurs=(), adjectifs=(), evenements=(), hors=0):
        self.journal = journal
        self.presentes = presentes
        self.hors = hors
        self.motifs = {"FROM adjectifs_fenetre WHERE": None, "GROUP BY entite, stance, adjectif": adjectifs,
                       "FROM evenements FINAL": evenements}
        self.scoreurs = scoreurs

    def query(self, sql, parameters=None):
        sql = " ".join(sql.split())
        self.journal.append((sql, parameters or {}))
        if "FROM system.tables" in sql:
            return Resultat([(n,) for n in self.presentes if n in parameters["noms"]])
        if "FROM adjectifs_fenetre" in sql and "GROUP BY scoreur" in sql:
            return Resultat(list(self.scoreurs))
        if "FROM pipeline_fenetre" in sql and "adj_debut" in sql:
            return Resultat([(self.hors,)])
        for motif, lignes in self.motifs.items():
            if lignes is not None and motif in sql:
                return Resultat(list(lignes))
        return Resultat([])


def test_adjectifs_table_absente_donne_none_sans_requete(monkeypatch):
    journal = []
    monkeypatch.setattr(donnees, "client", lambda cfg: FauxFacultatives(journal))
    brut = lire(CFG, k.bornes("7j", MAINTENANT, ETAT.premiere), ETAT)
    assert brut.adjectifs is None and brut.scoreur_adjectifs is None
    assert not any("FROM adjectifs_fenetre" in s for s, _ in journal)


def test_adjectifs_un_seul_scoreur_et_stances_evaluees(monkeypatch):
    journal = []
    monkeypatch.setattr(donnees, "client", lambda cfg: FauxFacultatives(
        journal, presentes=("adjectifs_fenetre",),
        scoreurs=[("lexique-v1", MAINTENANT - timedelta(days=1), MAINTENANT - timedelta(days=6)),
                  ("modele-fictif", MAINTENANT, MAINTENANT - timedelta(days=2))],
        adjectifs=[("alice-fictive", "pour", "clair", 4)],
        hors=17,
    ))
    b = k.bornes("7j", MAINTENANT, ETAT.premiere)
    brut = lire(CFG, b, ETAT)
    assert brut.scoreur_adjectifs == "modele-fictif" and brut.adjectifs == [("alice-fictive", "pour", "clair", 4)]
    sql, params = next((s, p) for s, p in journal if "GROUP BY entite, stance, adjectif" in s)
    assert "stance IN ('pour', 'contre')" in sql and params["scoreur"] == "modele-fictif"
    assert "fenetre_debut >= %(debut)s AND fenetre_debut < %(fin)s" in sql and "AS tranche" not in sql
    # couverture : fenêtres du scoreur retenu ; posts scorés hors d'elle lus dans pipeline_fenetre
    assert brut.couverture_adjectifs == (MAINTENANT - timedelta(days=2), MAINTENANT)
    assert brut.posts_hors_adjectifs == 17
    sql, params = next((s, p) for s, p in journal if "FROM pipeline_fenetre" in s and "adj_debut" in s)
    assert "fenetre_debut >= %(debut)s AND fenetre_debut < %(fin)s" in sql
    assert params["adj_debut"] == (MAINTENANT - timedelta(days=2)).replace(tzinfo=None)


def test_adjectifs_table_vide_donne_liste_vide(monkeypatch):
    monkeypatch.setattr(donnees, "client", lambda cfg: FauxFacultatives([], presentes=("adjectifs_fenetre",)))
    brut = lire(CFG, k.bornes("7j", MAINTENANT, ETAT.premiere), ETAT)
    assert brut.adjectifs == [] and brut.scoreur_adjectifs is None
    assert brut.couverture_adjectifs is None and brut.posts_hors_adjectifs == 0


def test_catalogue_absent(monkeypatch):
    monkeypatch.setattr(donnees, "client", lambda cfg: FauxFacultatives([]))
    assert donnees.evenements(CFG) == (False, [])


def test_catalogue_lu_et_liens_filtres(monkeypatch):
    journal = []
    d = datetime(2026, 10, 16, 16, 30)
    monkeypatch.setattr(donnees, "client", lambda cfg: FauxFacultatives(
        journal, presentes=("evenements",),
        evenements=[("e1", d, "Titre inventé", "loi", "exemple", "https://example.org/a"),
                    ("e2", d, "Autre titre", "inconnue", "exemple", "javascript:alert(1)")],
    ))
    disponible, liste = donnees.evenements(CFG)
    assert disponible and [e.id for e in liste] == ["e1", "e2"]
    assert liste[0].date == datetime(2026, 10, 16, 16, 30, tzinfo=timezone.utc)
    assert liste[0].lien == "https://example.org/a" and liste[1].lien is None
    assert liste[0].categorie == "loi" and liste[1].categorie == "autre"
    sql, params = next((s, p) for s, p in journal if "FROM evenements" in s)
    assert "FINAL" in sql and "LIMIT %(n)s" in sql and params["n"] == k.EVENEMENTS_MAX
