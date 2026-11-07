"""Périodes, pas et tranches (JSON `tableau` du contrat) : bornes, alignement sur Paris, changement d'heure, plages.

Calcul pur : aucun ClickHouse. Les dates de changement d'heure 2026 : 29 mars (passage à +2 h)
et 25 octobre (retour à +1 h, jour de 25 h).
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import calculs as k

PARIS = ZoneInfo("Europe/Paris")
MAINTENANT = datetime(2026, 10, 19, 10, 2, 30, tzinfo=timezone.utc)  # 12:02 à Paris
PREMIERE = datetime(2026, 10, 5, 10, 5, tzinfo=timezone.utc)


def local(t):
    return t.astimezone(PARIS)


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


# --- périodes nommées -------------------------------------------------------------------------
def test_24h_une_tranche_par_heure_et_fin_de_tranche_en_cours():
    b = k.bornes("24h", MAINTENANT, PREMIERE)
    assert b.pas_min == 60 and len(b.tranches) == 24
    assert b.fin == utc(2026, 10, 19, 11) and b.fin - b.debut == timedelta(hours=24)


def test_7j_tranches_de_6_heures_et_precedente_de_meme_taille():
    b = k.bornes("7j", MAINTENANT, PREMIERE)
    assert b.pas_min == 360 and len(b.tranches) == 28
    assert b.fin == utc(2026, 10, 19, 16) and b.debut == utc(2026, 10, 12, 16)
    assert b.precedente == (utc(2026, 10, 5, 16), utc(2026, 10, 12, 16))


def test_30j_tranches_de_jour_et_minuit_paris():
    b = k.bornes("30j", MAINTENANT, PREMIERE)
    assert b.pas_min == 1440 and len(b.tranches) == 30
    assert all(local(t).hour == 0 and local(t).minute == 0 for t in b.tranches)


def test_tranches_alignees_sur_paris_pour_chaque_pas():
    for pas in (60, 360, 1440, 10080):
        for t in k.tranches_entre(k.debut_tranche(utc(2026, 10, 1, 3, 17), pas), utc(2026, 11, 20), pas):
            loc = local(t)
            assert loc.minute == 0 and loc.second == 0
            if pas == 60:
                continue
            if pas == 360:
                assert loc.hour % 6 == 0
            elif pas == 1440:
                assert loc.hour == 0
            else:
                assert loc.hour == 0 and loc.weekday() == 0


def test_tout_sans_donnee_donne_une_tranche_du_jour():
    b = k.bornes("tout", MAINTENANT, None)
    assert b.pas_min == 1440 and len(b.tranches) == 1 and b.precedente is None
    assert b.debut == k.debut_tranche(MAINTENANT, 1440)


def test_tout_pas_de_jour_puis_de_semaine_au_dela_de_180_jours():
    court = k.bornes("tout", MAINTENANT, PREMIERE)
    assert court.pas_min == 1440 and court.debut == utc(2026, 10, 4, 22)  # minuit paris du 5 octobre
    long = k.bornes("tout", MAINTENANT, utc(2026, 1, 1))
    assert long.pas_min == 10080 and local(long.debut).weekday() == 0 and local(long.debut).hour == 0
    assert long.precedente is None


def test_premiere_donnee_dans_le_futur_ne_casse_pas_les_bornes():
    b = k.bornes("tout", MAINTENANT, MAINTENANT + timedelta(days=1))
    assert b.debut <= b.fin and len(b.tranches) == 1


# --- changement d'heure -----------------------------------------------------------------------
def test_jour_du_retour_a_l_heure_normale_a_25_heures():
    debut, fin = k.minuit_paris(date(2026, 10, 25)), k.minuit_paris(date(2026, 10, 26))
    assert fin - debut == timedelta(hours=25)
    assert len(k.tranches_entre(debut, fin, 60)) == 25
    assert len(k.tranches_entre(debut, fin, 1440)) == 1


def test_tranches_de_6_heures_le_jour_du_retour_durent_7_heures_une_fois():
    debut, fin = k.minuit_paris(date(2026, 10, 25)), k.minuit_paris(date(2026, 10, 26))
    t = list(k.tranches_entre(debut, fin, 360)) + [fin]
    durees = [int((t[i + 1] - t[i]) / timedelta(hours=1)) for i in range(len(t) - 1)]
    assert durees == [7, 6, 6, 6]


def test_jour_du_passage_a_l_heure_d_ete_a_23_heures_et_tranches_de_5_heures():
    debut, fin = k.minuit_paris(date(2026, 3, 29)), k.minuit_paris(date(2026, 3, 30))
    assert fin - debut == timedelta(hours=23)
    t = list(k.tranches_entre(debut, fin, 360)) + [fin]
    assert [int((t[i + 1] - t[i]) / timedelta(hours=1)) for i in range(len(t) - 1)] == [5, 6, 6, 6]


def test_periode_7j_traverse_le_changement_sans_tranche_manquante():
    b = k.bornes("7j", utc(2026, 10, 28, 12), None)
    assert len(b.tranches) == 28 and b.fin - b.debut >= timedelta(days=7) - timedelta(hours=1)


# --- plages de dates (perso) ------------------------------------------------------------------
@pytest.mark.parametrize(
    "jours, pas",
    [(1, 60), (2, 60), (3, 360), (14, 360), (15, 1440), (180, 1440), (181, 10080)],
)
def test_pas_selon_la_longueur_de_la_plage(jours, pas):
    assert k.pas_pour_jours(jours) == pas


def test_plage_perso_fin_incluse_et_precedente_de_meme_nombre_de_tranches():
    b = k.bornes("perso", MAINTENANT, PREMIERE, (date(2026, 10, 1), date(2026, 10, 3)))
    assert b.code == "perso" and b.pas_min == 360 and len(b.tranches) == 12
    assert b.debut == utc(2026, 9, 30, 22) and b.fin == utc(2026, 10, 3, 22)  # minuit du 1er au minuit suivant le 3
    assert b.precedente == (utc(2026, 9, 27, 22), utc(2026, 9, 30, 22))


def test_plage_d_un_seul_jour_fait_24_tranches_horaires():
    b = k.bornes("perso", MAINTENANT, PREMIERE, (date(2026, 10, 18), date(2026, 10, 18)))
    assert b.pas_min == 60 and len(b.tranches) == 24


def test_plage_longue_s_aligne_sur_le_lundi():
    b = k.bornes("perso", MAINTENANT, PREMIERE, (date(2026, 1, 1), date(2026, 8, 1)))
    assert b.pas_min == 10080 and local(b.debut).weekday() == 0 and local(b.debut).hour == 0
    assert local(b.fin).weekday() == 0 and b.fin >= k.minuit_paris(date(2026, 8, 2))


@pytest.mark.parametrize(
    "code, plage",
    [
        ("perso", (date(2026, 10, 3), date(2026, 10, 1))),  # inversée
        ("perso", (date(2026, 10, 1), date(2026, 10, 30))),  # fin dans le futur
        ("perso", (date(2000, 1, 1), date(2026, 10, 1))),  # plus de trois ans
        ("perso", None),
        ("1h", None),
        ("7j", (date(2026, 10, 1), date(2026, 10, 2))),
    ],
)
def test_periodes_absurdes_refusees(code, plage):
    with pytest.raises(k.PeriodeInvalide):
        k.bornes(code, MAINTENANT, PREMIERE, plage)
