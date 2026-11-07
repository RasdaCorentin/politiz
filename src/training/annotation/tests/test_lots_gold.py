"""Tests des lots gold sur un corpus synthétique (posts inventés, aucun contenu réel)."""
import json
from datetime import datetime, timezone

import pytest

from annotation import lots_gold


def _ecrire(chemin, lignes):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", encoding="utf-8") as f:
        for r in lignes:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


@pytest.fixture
def corpus(tmp_path):
    """Corpus fictif : 200 posts anciens, 60 nouveaux (ids qui recouvrent ceux de l'ancienne base)."""
    ancien = [{"id_source": i, "created_at": f"2026-10-{1 + i % 28:02d}T10:00:00.000Z",
               "texte": f"message synthétique {i} sur le sujet exemple @compte{i}.test https://ex.test/{i}",
               "contexte_type": None, "contexte_texte": None} for i in range(1, 201)]
    nouveau = [{"id_source": i, "created_at": "2026-10-30T06:00:00.000Z",
                "texte": f"réponse synthétique {i} @autre{i}.test",
                "contexte_type": "reponse" if i % 3 else None,
                "contexte_texte": f"contexte fictif {i} https://ctx.test/{i}" if i % 3 else None}
               for i in range(1, 61)]
    nouveau.append({"id_source": 900, "created_at": "2026-09-20T06:00:00.000Z",
                    "texte": "post daté avant la date minimale", "contexte_type": None, "contexte_texte": None})
    _ecrire(tmp_path / "collecte" / "ancien.jsonl", [{"source": "ancien", **r} for r in ancien])
    _ecrire(tmp_path / "collecte" / "nouveau.jsonl", [{"source": "nouveau", **r} for r in nouveau])
    # Gold : identifiants 1 à 10 de l'ancienne base. Le nouveau post 1 ne doit pas être exclu.
    _ecrire(tmp_path / "annotation" / "annotations" / "corentin.jsonl",
            [{"post_id": str(i), "pertinent": "oui"} for i in range(1, 11)])
    _ecrire(tmp_path / "annotation" / "lots" / "lot_eval.jsonl",
            [{"post_id": str(i), "text": f"message synthétique {i} sur le sujet exemple @compte{i}.test https://ex.test/{i}"}
             for i in range(11, 21)])
    # Silver : identifiants 21 à 30 ; texte d'un post du nouveau corpus pour l'exclusion par texte.
    train = [{"post_id": str(i), "text": f"message synthétique {i} sur le sujet exemple @compte{i}.test https://ex.test/{i}"}
             for i in range(21, 31)]
    train.append({"post_id": "9999", "text": "réponse synthétique 5 @autre5.test"})
    _ecrire(tmp_path / "annotation" / "train_silver.jsonl", train)
    return tmp_path


def _posts(lots):
    return [p for ps in lots.values() for p in ps]


def test_exclusions_par_identifiant_ne_touchent_que_l_ancienne_base(corpus):
    lots, _ = lots_gold.construire(corpus, taille=5, nb_lots=2, avec_contexte=4, graine=1)
    ids = {p["post_id"] for p in _posts(lots)}
    for i in range(1, 31):
        assert f"ancien:{i}" not in ids
    # Le nouveau post d'identifiant 1 n'est pas exclu par l'identifiant de l'ancienne base.
    posts = lots_gold.charger_collecte(corpus)
    ids, textes, _ = lots_gold.exclusions(corpus, posts)
    retenus = {p["post_id"] for p in lots_gold.filtrer(posts, ids, textes)}
    assert "nouveau:1" in retenus


def test_exclusion_par_texte_couvre_l_autre_source(corpus):
    # Le silver contient le texte d'un nouveau post (id 5) sous un autre identifiant : il sort.
    posts = lots_gold.charger_collecte(corpus)
    ids, textes, _ = lots_gold.exclusions(corpus, posts)
    retenus = {p["post_id"] for p in lots_gold.filtrer(posts, ids, textes)}
    assert "nouveau:5" not in retenus


def test_date_minimale_exclut_les_posts_anterieurs(corpus):
    posts = lots_gold.charger_collecte(corpus)
    ids, textes, _ = lots_gold.exclusions(corpus, posts)
    retenus = {p["post_id"] for p in lots_gold.filtrer(posts, ids, textes)}
    assert "nouveau:900" not in retenus


def test_doublons_de_texte_gardent_le_post_avec_contexte(corpus):
    posts = lots_gold.charger_collecte(corpus) + [
        {"post_id": "ancien:777", "source": "ancien", "id_source": 777, "created_at": "2026-10-02T10:00:00.000Z",
         "texte": "RÉPONSE synthétique 7 @autre7.test", "contexte_type": None, "contexte_texte": None},
    ]
    # Le nouveau post 7 a un contexte ; l'ancien post a le même texte, à la casse près.
    garde = {p["post_id"] for p in lots_gold.dedoublonner(lots_gold.filtrer(posts, set(), set()))
             if p["texte"].casefold().startswith("réponse synthétique 7")}
    assert garde == {"nouveau:7"}


def test_graine_reproductible_et_sensible(corpus):
    a, _ = lots_gold.construire(corpus, taille=5, nb_lots=2, avec_contexte=4, graine=7)
    b, _ = lots_gold.construire(corpus, taille=5, nb_lots=2, avec_contexte=4, graine=7)
    c, _ = lots_gold.construire(corpus, taille=5, nb_lots=2, avec_contexte=4, graine=8)
    assert [p["post_id"] for p in _posts(a)] == [p["post_id"] for p in _posts(b)]
    assert [p["post_id"] for p in _posts(a)] != [p["post_id"] for p in _posts(c)]


def test_taille_des_lots_et_pas_de_doublon(corpus):
    lots, man = lots_gold.construire(corpus, taille=5, nb_lots=3, avec_contexte=9, graine=3)
    assert [len(ps) for ps in lots.values()] == [5, 5, 5]
    ids = [p["post_id"] for p in _posts(lots)]
    assert len(ids) == len(set(ids)) == 15
    assert man["avec_contexte_total"] == 9
    assert sum(v["avec_contexte"] for v in man["lots"].values()) == 9


def test_avec_contexte_tous_non_nuls(corpus):
    lots, _ = lots_gold.construire(corpus, taille=5, nb_lots=2, avec_contexte=6, graine=11)
    assert sum(p["contexte_texte"] is not None for p in _posts(lots)) == 6


def test_masquage_texte_et_contexte(corpus):
    lots, _ = lots_gold.construire(corpus, taille=5, nb_lots=2, avec_contexte=6, graine=11)
    for p in _posts(lots):
        assert "@" not in lots_gold.ligne_lot(p, "x")["texte"]
        assert "http" not in lots_gold.ligne_lot(p, "x")["texte"]
    assert lots_gold.masquer("voir @a.b.test et https://x.y/z ok") == "voir [mention] et [url] ok"
    assert lots_gold.masquer(None) is None


def test_ecriture_fichiers_et_manifest_sans_texte(corpus, tmp_path):
    sortie = tmp_path / "sortie"
    man = lots_gold.ecrire(corpus, sortie, taille=5, nb_lots=2, avec_contexte=6, graine=11)
    lignes = [json.loads(ligne) for ligne in (sortie / "lot_gold_01.jsonl").read_text(encoding="utf-8").splitlines()]
    assert set(lignes[0]) == {"post_id", "lot", "source", "created_at", "texte", "contexte_type", "contexte_texte"}
    assert {"lot_gold_01", "lot_gold_02"} == set(man["lots"])
    brut = (sortie / "manifest.json").read_text(encoding="utf-8")
    assert "synthétique" not in brut and "réponse" not in brut
    assert json.loads(brut) == man


def _lignes_lots(sortie):
    return [json.loads(ligne) for f in sorted(sortie.glob("lot_gold_*.jsonl"))
            for ligne in f.read_text(encoding="utf-8").splitlines()]


def test_depuis_date_seule_commence_a_minuit_utc(corpus):
    posts = lots_gold.charger_collecte(corpus)
    depuis = lots_gold.parse_depuis("2026-10-30")
    assert depuis == datetime(2026, 10, 30, tzinfo=timezone.utc)
    retenus = {p["post_id"] for p in lots_gold.filtrer(posts, set(), set(), depuis)}
    assert "nouveau:1" in retenus  # 2026-10-30T06:00Z
    assert not any(i.startswith("ancien:") for i in retenus)  # datés du 1er au 28 octobre
    assert "nouveau:900" not in retenus  # 2026-09-20


def test_depuis_date_heure_avec_fuseau_compare_l_instant(corpus):
    posts = [
        {"post_id": "nouveau:1", "created_at": "2026-10-30T06:00:00.000Z", "texte": "avant"},
        {"post_id": "nouveau:2", "created_at": "2026-10-30T18:30:00.000Z", "texte": "après"},
    ]
    # 2026-10-30T20:00 à +02:00 vaut 18:00 UTC : seul le second post passe.
    depuis = lots_gold.parse_depuis("2026-10-30T20:00:00+02:00")
    assert depuis == datetime(2026, 10, 30, 18, tzinfo=timezone.utc)
    retenus = [p["post_id"] for p in lots_gold.filtrer(posts, set(), set(), depuis)]
    assert retenus == ["nouveau:2"]


def test_depuis_invalide_refuse_avant_tout_tirage(corpus, tmp_path):
    with pytest.raises(SystemExit):
        lots_gold.main(["--corpus", str(corpus), "--sortie", str(tmp_path / "s"), "--depuis", "pas-une-date"])
    assert not (tmp_path / "s").exists()


def test_premier_numerote_les_lots_et_le_champ_lot(corpus, tmp_path):
    sortie = tmp_path / "s"
    lots_gold.ecrire(corpus, sortie, taille=5, nb_lots=2, avec_contexte=4, graine=3, premier=6)
    assert sorted(f.name for f in sortie.glob("lot_gold_*.jsonl")) == ["lot_gold_06.jsonl", "lot_gold_07.jsonl"]
    for nom in ("lot_gold_06", "lot_gold_07"):
        lignes = [json.loads(ligne) for ligne in (sortie / f"{nom}.jsonl").read_text(encoding="utf-8").splitlines()]
        assert lignes and all(r["lot"] == nom for r in lignes)


def test_premier_refuse_zero_et_negatif(corpus, tmp_path):
    for valeur in ("0", "-2", "deux"):
        with pytest.raises(SystemExit):
            lots_gold.main(["--corpus", str(corpus), "--sortie", str(tmp_path / "s"), "--premier", valeur])
    assert not (tmp_path / "s").exists()


def test_refus_ecraser_un_lot(corpus, tmp_path):
    sortie = tmp_path / "s"
    sortie.mkdir()
    (sortie / "lot_gold_01.jsonl").write_text('{"post_id": "x:1", "lot": "lot_gold_01", "texte": "sentinelle"}\n',
                                              encoding="utf-8")
    avant = (sortie / "lot_gold_01.jsonl").read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="lot_gold_01.jsonl"):
        lots_gold.ecrire(corpus, sortie, taille=5, nb_lots=2, avec_contexte=4, graine=3)
    assert (sortie / "lot_gold_01.jsonl").read_text(encoding="utf-8") == avant
    assert not (sortie / "lot_gold_02.jsonl").exists()
    assert not (sortie / "manifest.json").exists()


def test_refus_ecraser_un_manifest(corpus, tmp_path):
    sortie = tmp_path / "s"
    sortie.mkdir()
    (sortie / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="manifest.json"):
        lots_gold.ecrire(corpus, sortie, taille=5, nb_lots=2, avec_contexte=4, graine=3)
    assert (sortie / "manifest.json").read_text(encoding="utf-8") == "{}"
    assert not (sortie / "lot_gold_01.jsonl").exists()


def test_lots_deja_tires_excluent_leurs_identifiants(corpus, tmp_path):
    sortie = tmp_path / "s"
    lots_gold.ecrire(corpus, sortie, taille=5, nb_lots=2, avec_contexte=4, graine=3)
    deja = {p["post_id"] for p in _lignes_lots(sortie)}
    assert len(deja) == 10
    lots, man = lots_gold.construire(corpus, taille=5, nb_lots=2, avec_contexte=4, graine=4,
                                     sortie=sortie, premier=3)
    ids = {p["post_id"] for p in _posts(lots)}
    assert not ids & deja
    assert man["exclusions"]["deja_en_lot"] == 10
    assert man["exclusions"]["lots_existants"] == 2


def test_lots_deja_tires_excluent_leurs_textes(corpus, tmp_path):
    sortie = tmp_path / "s"
    # Post déjà tiré sous un autre identifiant, texte masqué et casse différente.
    _ecrire(sortie / "lot_gold_01.jsonl",
            [{"post_id": "ancien:999", "lot": "lot_gold_01", "texte": "RÉPONSE synthétique 5 [mention]"}])
    posts = lots_gold.charger_collecte(corpus)
    ids, textes, _ = lots_gold.exclusions(corpus, posts)
    ids_lots, textes_lots, _ = lots_gold.lots_existants(sortie)
    retenus = {p["post_id"] for p in lots_gold.filtrer(posts, ids, textes, lots_gold.DATE_MIN, ids_lots, textes_lots)}
    assert "nouveau:5" not in retenus
    assert "nouveau:6" in retenus
    _, man = lots_gold.construire(corpus, taille=5, nb_lots=2, avec_contexte=4, graine=3, sortie=sortie, premier=2)
    assert man["exclusions"]["deja_en_lot"] == 1


def test_manifest_nomme_selon_premier_et_date_ecrite(corpus, tmp_path):
    sortie = tmp_path / "s"
    lots_gold.ecrire(corpus, sortie, taille=5, nb_lots=2, avec_contexte=4, graine=3,
                     depuis=lots_gold.parse_depuis("2026-10-30"), premier=6)
    assert not (sortie / "manifest.json").exists()
    man = json.loads((sortie / "manifest_lot_gold_06_07.json").read_text(encoding="utf-8"))
    assert man["date_minimale"] == "2026-10-30T00:00:00+00:00"
    assert set(man["lots"]) == {"lot_gold_06", "lot_gold_07"}


def test_manifest_premier_1_garde_son_nom(corpus, tmp_path):
    sortie = tmp_path / "s"
    man = lots_gold.ecrire(corpus, sortie, taille=5, nb_lots=2, avec_contexte=4, graine=3)
    assert (sortie / "manifest.json").is_file()
    assert json.loads((sortie / "manifest.json").read_text(encoding="utf-8"))["date_minimale"] == \
        "2026-10-01T00:00:00+00:00"
    assert man["date_minimale"] == "2026-10-01T00:00:00+00:00"


def test_corpus_insuffisant_arrete_sans_rien_ecrire(corpus, tmp_path):
    sortie = tmp_path / "s"
    with pytest.raises(SystemExit, match="Corpus insuffisant"):
        lots_gold.ecrire(corpus, sortie, taille=20, nb_lots=100, avec_contexte=40, graine=3)
    assert not sortie.exists()
