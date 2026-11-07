import json
from datetime import datetime, timezone

import pytest
from pyspark.sql import functions as F

import job
import pii

MARQUEUR = "temoinfuite"
DID = "did:plc:syntheticfuite"
FEN_US = 5 * 60 * 1_000_000
# 2026-10-08T04:40:00Z : début d'une fenêtre ; les +delta restent dans la fenêtre
DEBUT_US = int(datetime(2026, 10, 8, 4, 40, tzinfo=timezone.utc).timestamp()) * 1_000_000


def evenement(texte, delta_s=61, langs=("fr",), operation="create", did=DID):
    return json.dumps({
        "did": did, "time_us": DEBUT_US + delta_s * 1_000_000 + 123, "kind": "commit",
        "commit": {"rev": "r", "operation": operation, "collection": "app.bsky.feed.post",
                   "rkey": "rk" + MARQUEUR, "cid": "bafy" + MARQUEUR,
                   "record": {"$type": "app.bsky.feed.post", "createdAt": "2026-10-08T04:41:00Z",
                              "langs": list(langs), "text": texte,
                              "reply": {"parent": {"uri": f"at://{did}/x/y", "cid": "c"}}}},
    })


def lot(spark, evenements, now_delta_s=90):
    df = spark.createDataFrame([(e,) for e in evenements], ["value"])
    propre = pii.nettoyer(pii.projeter(df)).dropDuplicates(["hash"]).select("time_us", "texte")
    return job.traiter_micro_lot(propre, spark, 5, DEBUT_US + now_delta_s * 1_000_000)


def _en_texte(df):
    """Horodatages en texte UTC (la session Spark est en UTC, pas le poste de test)."""
    return df.select([F.col(c).cast("string").alias(c) if t == "timestamp" else F.col(c)
                      for c, t in df.dtypes])


def tout(lot_):
    return {nom: [r.asDict() for r in _en_texte(df).collect()]
            for nom, df in {"posts": lot_.posts, **lot_.agregats()}.items()}


def test_candidat_unique(spark):
    r = tout(lot(spark, [evenement(f"Je voterai Glucksmann au premier tour {MARQUEUR}")]))
    assert len(r["posts"]) == 1
    p = r["posts"][0]
    assert (p["entite"], p["stance"], p["sentiment"], p["langue"], p["scoreur"]) == (
        "glucksmann", "pour", "positif", "fr", "lexique-v1")
    assert p["dt"] == "2026-10-08"
    assert p["fenetre_debut"] == "2026-10-08 04:40:00"
    assert r["cibles_fenetre"] == [{"fenetre_debut": "2026-10-08 04:40:00",
                                    "entite": "glucksmann", "stance": "pour", "nb_posts": 1}]
    assert r["posts_fenetre"][0]["nb_posts"] == 1
    pf = r["pipeline_fenetre"][0]
    assert (pf["nb_posts"], pf["somme_latence_ms"]) == (1, 28999)  # 90 s - 61,000123 s, tronqué à la ms
    assert pf["derniere_maj"] == "2026-10-08 04:41:30"
    assert {t["theme"] for t in r["themes_fenetre"]} >= {"campagne-sondages"}


def test_deux_candidats_deux_lignes_un_post(spark):
    r = tout(lot(spark, [evenement("Votez Glucksmann, jamais Bardella")]))
    assert {p["entite"] for p in r["posts"]} == {"glucksmann", "bardella"}
    assert sum(c["nb_posts"] for c in r["cibles_fenetre"]) == 2
    assert sum(c["nb_posts"] for c in r["posts_fenetre"]) == 1
    assert r["pipeline_fenetre"][0]["nb_posts"] == 1


def test_aucun_candidat_ligne_a_entite_nulle(spark):
    r = tout(lot(spark, [evenement("La dette publique inquiète, le budget aussi")]))
    assert [p["entite"] for p in r["posts"]] == [None]
    assert r["cibles_fenetre"] == []
    assert {t["theme"] for t in r["themes_fenetre"]} == {"economie"}


def test_post_sans_rien_de_reconnu_compte_dans_le_pipeline_seulement(spark):
    r = tout(lot(spark, [evenement("Il fait beau ce matin à Lyon")]))
    assert r["posts"] == [] and r["cibles_fenetre"] == []
    assert r["posts_fenetre"] == [] and r["themes_fenetre"] == []
    assert r["pipeline_fenetre"][0]["nb_posts"] == 1


def test_doublon_compte_une_fois(spark):
    e = [evenement("Votez Glucksmann", did="did:plc:a"), evenement("Votez  GLUCKSMANN", did="did:plc:b")]
    r = tout(lot(spark, e))
    assert r["pipeline_fenetre"][0]["nb_posts"] == 1


def test_non_francais_et_non_create_ecartes(spark):
    e = [evenement("Vote Glucksmann", langs=("en",)), evenement("Vote Glucksmann", operation="delete")]
    r = tout(lot(spark, e))
    assert all(v == [] for v in r.values())


def test_troncature_a_la_fenetre_et_deux_fenetres(spark):
    e = [evenement("Votez Glucksmann", delta_s=1), evenement("Vote Bardella demain", delta_s=299),
         evenement("Votez Attal", delta_s=301)]
    r = tout(lot(spark, e, now_delta_s=400))
    debuts = {c["fenetre_debut"] for c in r["pipeline_fenetre"]}
    assert debuts == {"2026-10-08 04:40:00", "2026-10-08 04:45:00"}
    for lignes in r.values():
        for ligne in lignes:
            assert ligne["fenetre_debut"][14:] in ("40:00", "45:00")


def test_aucun_texte_ni_identifiant_en_sortie(spark):
    e = [evenement(f"Je voterai Glucksmann {MARQUEUR} https://exemple.test/x @bob.test {DID}"),
         evenement(f"{MARQUEUR} la dette inquiète", did="did:plc:autre")]
    lot_ = lot(spark, e)
    r = tout(lot_)
    brut = json.dumps(r, default=str)
    assert MARQUEUR not in brut and "did:" not in brut and "exemple" not in brut and "bob" not in brut
    schemas = {nom: set(df.columns) for nom, df in {"posts": lot_.posts, **lot_.agregats()}.items()}
    assert schemas["posts"] == {"fenetre_debut", "langue", "entite", "stance", "sentiment", "emotion",
                                "themes", "confiance", "scoreur", "dt"}
    assert schemas["cibles_fenetre"] == {"fenetre_debut", "entite", "stance", "nb_posts"}
    assert schemas["posts_fenetre"] == {"fenetre_debut", "sentiment", "emotion", "nb_posts"}
    assert schemas["themes_fenetre"] == {"fenetre_debut", "theme", "nb_posts"}
    assert schemas["pipeline_fenetre"] == {"fenetre_debut", "nb_posts", "somme_latence_ms",
                                           "derniere_maj"}


def test_flux_dedoublonne_dans_le_filigrane(spark, tmp_path):
    """Chemin streaming complet (source fichiers à la place de Kafka)."""
    entree = tmp_path / "in"
    entree.mkdir()
    (entree / "a.json").write_text("\n".join([
        evenement("Votez Glucksmann", delta_s=10, did="did:plc:a"),
        evenement("Votez Glucksmann", delta_s=20, did="did:plc:b"),
        evenement("Je voterai Bardella", delta_s=30, did="did:plc:c"),
    ]) + "\n")
    brut = spark.readStream.format("text").load(str(entree)).withColumnRenamed("value", "value")
    flux = job.preparer_flux(brut, 10)
    recu = []

    def collecter(df, _id):
        recu.extend(r.asDict() for r in df.collect())

    q = (flux.writeStream.foreachBatch(collecter)
         .option("checkpointLocation", str(tmp_path / "ck")).start())
    q.processAllAvailable()
    q.stop()
    assert sorted(r["texte"] for r in recu) == ["je voterai bardella", "votez glucksmann"]
    assert set(recu[0]) == {"time_us", "texte"}


def test_config_depuis_env():
    c = job.Config.depuis_env({"FENETRE_MINUTES": "10", "KAFKA_TOPIC": "t"})
    assert (c.fenetre_minutes, c.kafka_topic, c.trigger_seconds, c.watermark_minutes) == (10, "t", 30, 10)


# --- croisements_fenetre (historique long, 365 jours) ----------------------------
TEXTE_DEUX_CIBLES = "Votez Glucksmann, jamais Bardella, la dette publique inquiète"
TEXTE_SANS_CIBLE = "La dette publique inquiète, le budget aussi"


def croisements(r):
    return {(c["entite"], c["stance"], c["sentiment"], c["emotion"], c["theme"], c["scoreur"]):
            c["nb_posts"] for c in r["croisements_fenetre"]}


def test_post_deux_cibles_deux_themes_quatre_occurrences(spark):
    r = tout(lot(spark, [evenement(TEXTE_DEUX_CIBLES)]))
    assert croisements(r) == {
        ("glucksmann", "pour", "positif", "non_evalue", "economie", "lexique-v1"): 1,
        ("glucksmann", "pour", "positif", "non_evalue", "campagne-sondages", "lexique-v1"): 1,
        ("bardella", "non_evalue", "positif", "non_evalue", "economie", "lexique-v1"): 1,
        ("bardella", "non_evalue", "positif", "non_evalue", "campagne-sondages", "lexique-v1"): 1,
    }
    assert sum(c["nb_posts"] for c in r["croisements_fenetre"]) == 4


def test_post_sans_cible_entite_vide(spark):
    r = tout(lot(spark, [evenement(TEXTE_SANS_CIBLE)]))
    assert r["cibles_fenetre"] == []
    assert croisements(r) == {("", "non_evalue", "non_evalue", "non_evalue", "economie", "lexique-v1"): 1}


def test_croisements_coherents_avec_cibles_fenetre(spark):
    """Propriété : pour chaque (fenêtre, cible, stance), un post compte une fois par cible et
    par thème qu'il porte. Donc :
      - pour un thème donné, nb_posts(croisement) <= nb_posts(cibles_fenetre) ;
      - la somme sur les thèmes = somme des thèmes des posts de cette cible (exact) ;
      - cibles_fenetre donne le nombre de posts distincts (exact)."""
    textes = [TEXTE_DEUX_CIBLES, "Votez Glucksmann", "Je voterai Glucksmann au premier tour",
              TEXTE_SANS_CIBLE]
    lot_ = lot(spark, [evenement(t, did=f"did:plc:{i}") for i, t in enumerate(textes)])
    r = tout(lot_)
    cibles = {(c["entite"], c["stance"]): c["nb_posts"] for c in r["cibles_fenetre"]}
    par_theme, somme = {}, {}
    for c in r["croisements_fenetre"]:
        if c["entite"] == "":
            continue
        cle = (c["entite"], c["stance"])
        par_theme[(cle, c["theme"])] = par_theme.get((cle, c["theme"]), 0) + c["nb_posts"]
        somme[cle] = somme.get(cle, 0) + c["nb_posts"]
    attendu_somme = {}
    for p in lot_.posts.collect():
        if p["entite"] is None:
            continue
        cle = (p["entite"], p["stance"])
        attendu_somme[cle] = attendu_somme.get(cle, 0) + len(p["themes"])
    assert cibles == {("glucksmann", "pour"): 3, ("bardella", "non_evalue"): 1}
    assert somme == attendu_somme == {("glucksmann", "pour"): 4, ("bardella", "non_evalue"): 2}
    for (cle, _theme), n in par_theme.items():
        assert n <= cibles[cle]
    for cle, n in cibles.items():
        assert max(v for (c2, _), v in par_theme.items() if c2 == cle) <= n <= somme[cle]


def test_colonnes_et_types_du_contrat_croisements(spark):
    lot_ = lot(spark, [evenement(TEXTE_DEUX_CIBLES)])
    assert lot_.croisements_fenetre.dtypes == [
        ("fenetre_debut", "timestamp"), ("entite", "string"), ("stance", "string"),
        ("sentiment", "string"), ("emotion", "string"), ("theme", "string"),
        ("scoreur", "string"), ("nb_posts", "bigint")]
    assert "croisements_fenetre" in job.TABLES_CLICKHOUSE


def adjectifs_lot(r):
    return {(a["entite"], a["stance"], a["adjectif"], a["scoreur"]): a["nb_posts"]
            for a in r["adjectifs_fenetre"]}


def test_adjectifs_par_cible_evaluee(spark):
    """Un post compte une fois par (cible pour ou contre, adjectif) ; une cible non évaluée, un
    post sans cible et un adjectif répété n'ajoutent rien."""
    textes = ["Je voterai Glucksmann au premier tour, un candidat crédible et crédible",
              "Je ne voterai jamais Mélenchon, dangereux",
              "Votez Glucksmann, jamais Bardella, dangereux",
              "La dette publique est dangereuse"]
    r = tout(lot(spark, [evenement(t, did=f"did:plc:{i}") for i, t in enumerate(textes)]))
    assert adjectifs_lot(r) == {
        ("glucksmann", "pour", "crédible", "lexique-v1"): 1,
        ("glucksmann", "pour", "dangereux", "lexique-v1"): 1,
        ("melenchon", "contre", "dangereux", "lexique-v1"): 1,
    }
    assert {a["fenetre_debut"] for a in r["adjectifs_fenetre"]} == {"2026-10-08 04:40:00"}


def test_colonnes_et_types_du_contrat_adjectifs(spark):
    lot_ = lot(spark, [evenement(f"Je ne voterai jamais Mélenchon, dangereux {MARQUEUR} {DID}")])
    assert lot_.adjectifs_fenetre.dtypes == [
        ("fenetre_debut", "timestamp"), ("entite", "string"), ("stance", "string"),
        ("adjectif", "string"), ("scoreur", "string"), ("nb_posts", "bigint")]
    assert "adjectifs_fenetre" in job.TABLES_CLICKHOUSE
    brut = json.dumps(tout(lot_)["adjectifs_fenetre"], default=str)
    assert MARQUEUR not in brut and "did:" not in brut


def test_croisements_sans_texte_ni_identifiant(spark):
    lot_ = lot(spark, [evenement(f"{MARQUEUR} {TEXTE_DEUX_CIBLES} {DID}")])
    cols = set(lot_.croisements_fenetre.columns)
    assert cols == {"fenetre_debut", "entite", "stance", "sentiment", "emotion", "theme",
                    "scoreur", "nb_posts"}
    brut = json.dumps(tout(lot_)["croisements_fenetre"], default=str)
    assert MARQUEUR not in brut and "did:" not in brut
