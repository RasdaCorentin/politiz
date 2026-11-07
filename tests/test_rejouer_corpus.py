"""Tests du rejeu de corpus (scripts/rejouer_corpus.py) sur une base SQLite inventée.

Aucun post réel : les textes et les horodatages sont fabriqués. Le marqueur `temoinfuite` vérifie
qu'aucun texte d'entrée ne sort dans les agrégats ni dans la sortie.
"""
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "scripts"))

import rejouer_corpus as rc  # noqa: E402

MARQUEUR = "temoinfuite"
DEPUIS = "2026-10-12T00:00:00Z"
AVANT = "2026-10-12T01:00:00Z"
TEXTES = [
    # (created_at, texte) : dans la période, sauf les cas marqués
    ("2026-10-11T23:59:59.999Z", f"Hors période {MARQUEUR} ancien."),          # avant DEPUIS
    ("2026-10-12T00:00:00.000Z", f"Vive le pen, il a raison sur la retraite {MARQUEUR}."),  # borne incluse
    ("2026-10-12T00:03:10.500Z", f"Vive le pen, il a raison sur la retraite {MARQUEUR}."),  # doublon exact
    ("2026-10-12T00:20:00.000Z", "Je ne vote plus pour le pen, dangereux https://example.org/x @inventee.test"),
    ("2026-10-12T00:30:00.000Z", "Une phrase sans rapport avec la politique."),
    ("2026-10-12T00:40:00.000Z", "https://example.org/seulement-une-url"),       # vide après nettoyage
    ("2026-10-12T00:59:59.999Z", "Joie immense pour la journée."),
    ("2026-10-12T01:00:00.000Z", f"Hors période, borne exclue {MARQUEUR}."),    # avant AVANT
]
AVANT_US = rc.temps_us(rc.formater_borne(AVANT))


@pytest.fixture
def base(tmp_path):
    chemin = tmp_path / "corpus-inventé.db"
    con = sqlite3.connect(chemin)
    con.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,"
                " text TEXT NOT NULL, dedup_key TEXT NOT NULL UNIQUE)")
    for i, (created, texte) in enumerate(TEXTES):
        con.execute("INSERT INTO posts (created_at, text, dedup_key) VALUES (?, ?, ?)",
                    (created, texte, f"cle-{i}"))
    con.commit()
    con.close()
    return chemin


@pytest.fixture(scope="module")
def spark():
    s = rc.creer_session()
    yield s
    s.stop()


class FauxClient:
    """Client ClickHouse simulé : enregistre les insertions, répond aux `count()` et `sum()`.

    `deja` : lignes déjà présentes, pour toutes les tables (entier) ou par table (dictionnaire)."""

    def __init__(self, deja=0):
        self.deja = deja
        self.inserts: dict[str, list] = {}
        self.comptes: list[str] = []

    def query(self, sql, parameters=None):
        class Resultat:
            result_rows = []
        if "count()" in sql:
            table = sql.split("FROM sae.")[1].split()[0]
            self.comptes.append(table)
            n = self.deja.get(table, 0) if isinstance(self.deja, dict) else self.deja
            Resultat.result_rows = [(n,)]
        else:
            table = sql.split("FROM sae.")[1].split()[0]
            indice = 2 if table == "pipeline_fenetre" else -1
            total = sum(int(ligne[indice]) for ligne in self.inserts.get(table, []))
            Resultat.result_rows = [(total,)]
        return Resultat

    def insert(self, table, lignes, column_names):
        self.inserts.setdefault(table.replace("sae.", ""), []).extend(lignes)


def _collecter(lot):
    """Agrégats d'un `Lot` sous la même forme que `agreger` (sans latence)."""
    acc = {}
    for table, agg in lot.agregats().items():
        cles = rc.CLES[table]
        vue = agg.withColumn("fenetre_debut", rc.F.unix_timestamp("fenetre_debut"))
        compteur = Counter()
        for r in vue.select(*cles, "nb_posts").collect():
            compteur[tuple(rc._cle(r[c]) for c in cles)] += r["nb_posts"]
        acc[table] = compteur
    return acc


def test_formater_borne_et_bornes_de_lecture(base):
    assert rc.formater_borne(DEPUIS) == "2026-10-12T00:00:00.000Z"
    assert rc.formater_borne("2026-10-12T00:00:00.5Z") == "2026-10-12T00:00:00.500Z"
    lus = [c for c, _ in rc.lire_posts(base, rc.formater_borne(DEPUIS), rc.formater_borne(AVANT))]
    assert lus == [c for c, _ in TEXTES[1:-1]]  # borne incluse, borne exclue
    assert len(lus) == 6


def test_temps_us_correspond_a_time_us():
    attendu = int(datetime(2026, 10, 12, tzinfo=timezone.utc).timestamp()) * 1_000_000
    assert rc.temps_us("2026-10-12T00:00:00.000Z") == attendu


def test_garde_fou_refuse_un_second_import():
    client = FauxClient(deja=1)
    depuis = datetime(2026, 10, 12, tzinfo=timezone.utc)
    avant = datetime(2026, 10, 19, 16, 25, tzinfo=timezone.utc)
    acc = {t: Counter() for t in rc.CLES}
    with pytest.raises(rc.DejaImporte):
        rc.importer(client, acc, depuis, avant)
    assert client.inserts == {}


def test_import_insere_puis_verifie_les_sommes():
    client = FauxClient(deja=0)
    depuis = datetime(2026, 10, 12, tzinfo=timezone.utc)
    avant = datetime(2026, 10, 19, 16, 25, tzinfo=timezone.utc)
    fen = int(datetime(2026, 10, 12, 0, tzinfo=timezone.utc).timestamp())
    acc = {t: Counter() for t in rc.CLES}
    acc["pipeline_fenetre"][(fen,)] = 3
    acc["posts_fenetre"][(fen, "positif", "joie")] = 2
    acc["posts_fenetre"][(fen, "neutre", "non_evalue")] = 1
    acc["themes_fenetre"][(fen, "economie")] = 1
    rc.importer(client, acc, depuis, avant)
    assert list(client.inserts) == list(rc.ORDRE_INSERTION)
    ligne = client.inserts["pipeline_fenetre"][0]
    assert ligne[1] == datetime.fromtimestamp(fen + 300, timezone.utc)  # derniere_maj = fin de fenêtre
    assert ligne[3] == 0  # somme_latence_ms nulle pour un rejeu


def test_aucun_texte_dans_agregats_ni_sortie(base, spark, capsys):
    posts = rc.lire_posts(base, rc.formater_borne(DEPUIS), rc.formater_borne(AVANT))
    dedup, stats = rc.preparer(spark, posts)
    acc = rc.agreger(spark, dedup, None, AVANT_US, taille=3)
    rc.afficher_comptes(stats, acc)
    sortie = capsys.readouterr().out + repr(acc)
    assert MARQUEUR not in sortie
    assert "example.org" not in sortie
    assert stats == {"lus": 6, "propres": 5, "doublons_espaces": 0}  # URL seule retirée
    assert sum(acc["pipeline_fenetre"].values()) == 4  # 5 propres, 1 doublon exact retiré


def test_rejeu_sans_modele_egal_a_un_appel_direct(base, spark):
    posts = rc.lire_posts(base, rc.formater_borne(DEPUIS), rc.formater_borne(AVANT))
    dedup, _ = rc.preparer(spark, posts)
    par_lots = rc.agreger(spark, dedup, None, AVANT_US, taille=2)
    import job
    direct = _collecter(job.traiter_micro_lot(dedup, spark, 5, maintenant_us=AVANT_US))
    assert par_lots == direct
    assert sum(par_lots["pipeline_fenetre"].values()) == 4  # posts scorés, après dédoublonnage
    assert sum(par_lots["posts_fenetre"].values()) <= 4  # seuls les posts retenus par le filtre fin
    assert {cle[1:] for cle in par_lots["adjectifs_fenetre"]} == {("le pen", "contre", "dangereux", "lexique-v1")}


def test_import_restreint_aux_adjectifs():
    """Période déjà importée sans adjectifs : `--tables adjectifs_fenetre` n'insère qu'eux et ne
    lit que leur table ; une seconde fois, le garde-fou refuse."""
    depuis = datetime(2026, 10, 12, tzinfo=timezone.utc)
    avant = datetime(2026, 10, 19, 16, 25, tzinfo=timezone.utc)
    fen = int(depuis.timestamp())
    acc = {t: Counter() for t in rc.CLES}
    acc["pipeline_fenetre"][(fen,)] = 3
    acc["adjectifs_fenetre"][(fen, "le-pen", "contre", "dangereux", "lexique-v1")] = 2
    tables = rc.lire_tables("adjectifs_fenetre")
    client = FauxClient(deja={"pipeline_fenetre": 7})
    rc.importer(client, acc, depuis, avant, tables)
    assert list(client.inserts) == ["adjectifs_fenetre"]
    assert set(client.comptes) == {"adjectifs_fenetre"}
    with pytest.raises(rc.DejaImporte):
        rc.importer(FauxClient(deja={"adjectifs_fenetre": 1}), acc, depuis, avant, tables)


def test_tables_dans_l_ordre_d_insertion_et_inconnues_refusees():
    assert rc.lire_tables("adjectifs_fenetre, pipeline_fenetre") == ("pipeline_fenetre", "adjectifs_fenetre")
    with pytest.raises(rc.argparse.ArgumentTypeError):
        rc.lire_tables("posts")


def test_agregats_anciens_sans_table_d_adjectifs(tmp_path):
    fen = int(datetime(2026, 10, 12, tzinfo=timezone.utc).timestamp())
    acc = {t: Counter() for t in rc.CLES if t != "adjectifs_fenetre"}
    acc["pipeline_fenetre"][(fen,)] = 5
    rc.ecrire_agregats(tmp_path, acc, {"lus": 5, "propres": 5, "doublons_espaces": 0}, 1.0)
    relu, _ = rc.lire_agregats(tmp_path)
    assert "adjectifs_fenetre" not in relu and relu == acc


def test_agregats_ecrits_puis_relus_a_l_identique(tmp_path):
    fen = int(datetime(2026, 10, 12, tzinfo=timezone.utc).timestamp())
    acc = {t: Counter() for t in rc.CLES}
    acc["cibles_fenetre"][(fen, "le-pen", "contre")] = 2
    acc["croisements_fenetre"][(fen, "", "non_evalue", "neutre", "non_evalue", "autre", "lexique-v1")] = 5
    acc["pipeline_fenetre"][(fen,)] = 5
    stats = {"lus": 6, "propres": 5, "doublons_espaces": 0}
    rc.ecrire_agregats(tmp_path, acc, stats, 12.3)
    relu, stats_relus = rc.lire_agregats(tmp_path)
    assert relu == acc and stats_relus == stats
    assert MARQUEUR not in (tmp_path / "agregats.json").read_text(encoding="utf-8")
