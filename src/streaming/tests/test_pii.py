import json
import sys
import unicodedata
from pathlib import Path

import pii

RACINE = Path(__file__).resolve().parents[3]


def normalize_ingestion(text):  # copie de ingestion.normalize, pour le test d'équivalence
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def test_normaliser_equivaut_a_ingestion():
    for t in ["Présidentielle ÉLYSÉE", "Ça été où ? Œuvre ﬁnale", "Noël à Zürich 🤮", "ñandú", ""]:
        assert pii.normaliser(t) == normalize_ingestion(t)


def test_nettoyage_masque_url_handle_did():
    t = pii.nettoyer_texte("Vu chez @alice.test.social : https://exemple.test/a?b=1 did:plc:synthetic0001 ÉLYSÉE")
    assert t == "vu chez : elysee"
    assert "http" not in t and "@" not in t and "did:" not in t


def test_nettoyage_texte_vide():
    assert pii.nettoyer_texte(None) == "" and pii.nettoyer_texte("   ") == ""


EVENEMENT = {
    "did": "did:plc:synthetic0001", "time_us": 1791434542041435, "kind": "commit",
    "commit": {
        "rev": "revinvente", "operation": "create", "collection": "app.bsky.feed.post",
        "rkey": "rkeyinvente", "cid": "bafyinvente",
        "record": {
            "$type": "app.bsky.feed.post", "createdAt": "2026-10-08T04:42:16.721Z",
            "langs": ["fr"], "text": "Texte inventé avec @bob.test et #tag",
            "reply": {"root": {"uri": "at://did:plc:synthetic0002/app.bsky.feed.post/x", "cid": "c1"},
                      "parent": {"uri": "at://did:plc:synthetic0003/app.bsky.feed.post/y", "cid": "c2"}},
            "embed": {"$type": "app.bsky.embed.external", "external": {"uri": "https://exemple.test"}},
            "facets": [
                {"index": {"byteStart": 0, "byteEnd": 3},
                 "features": [{"$type": "app.bsky.richtext.facet#mention", "did": "did:plc:synthetic0004"}]},
                {"index": {"byteStart": 5, "byteEnd": 9},
                 "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": "tag"}]},
                {"features": [{"$type": "app.bsky.richtext.facet#link", "uri": "https://exemple.test"}]},
            ],
        },
    },
}


def test_projection_liste_blanche(spark):
    df = spark.createDataFrame([(json.dumps(EVENEMENT),)], ["value"])
    plat = pii.projeter(df)
    assert tuple(plat.columns) == pii.COLONNES_PROJETEES
    ligne = plat.collect()[0]
    assert ligne["hashtags"] == ["tag"] and ligne["langs"] == ["fr"]
    texte_sortie = json.dumps([str(v) for k, v in ligne.asDict().items() if k != "texte_brut"])
    for interdit in ("did:", "synthetic", "rkey", "bafy", "at://", "revinvente", "2026-10-08"):
        assert interdit not in texte_sortie


def test_schema_sans_champ_identifiant():
    noms = set()

    def parcourir(t):
        if hasattr(t, "fields"):
            for f in t.fields:
                noms.add(f.name)
                parcourir(f.dataType)
        elif hasattr(t, "elementType"):
            parcourir(t.elementType)
    parcourir(pii.SCHEMA_EVENEMENT)
    assert not noms & {"did", "rkey", "cid", "rev", "reply", "embed", "createdAt", "uri", "index"}


def test_nettoyer_sortie_sans_texte_brut_ni_identifiant(spark):
    ev2 = json.loads(json.dumps(EVENEMENT))
    ev2["commit"]["record"]["langs"] = ["en"]
    ev3 = json.loads(json.dumps(EVENEMENT))
    ev3["commit"]["operation"] = "delete"
    df = spark.createDataFrame([(json.dumps(e),) for e in (EVENEMENT, ev2, ev3)], ["value"])
    sortie = pii.nettoyer(pii.projeter(df))
    assert sorted(sortie.columns) == ["event_time", "hash", "texte", "time_us"]
    lignes = sortie.collect()
    assert len(lignes) == 1
    assert lignes[0]["texte"] == "texte invente avec et #tag"
    assert len(lignes[0]["hash"]) == 64
