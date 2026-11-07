from collections import Counter

from annotation import prepare
from annotation.common import (ENTITES_PATH, alias_map, detect_entities, entity_choices, load_entites,
                               load_schema, normalize)
from annotation.tests.conftest import make_posts

ENT = [
    {"id": "le pen", "alias": [{"forme": "le pen", "ambigu": False}, {"forme": "marine le pen", "ambigu": False}]},
    {"id": "rassemblement national", "alias": [{"forme": "rn", "ambigu": False},
                                               {"forme": "rassemblement national", "ambigu": False}]},
    {"id": "melenchon", "alias": [{"forme": "melenchon", "ambigu": False}, {"forme": "jean-luc melenchon", "ambigu": False}]},
    {"id": "lfi", "alias": [{"forme": "lfi", "ambigu": False}]},
    {"id": "edouard philippe", "alias": [{"forme": "edouard philippe", "ambigu": False}, {"forme": "philippe", "ambigu": True}]},
    {"id": "attal", "alias": [{"forme": "attal", "ambigu": False}]},
]


def test_normalize_retire_url_mention_accents():
    assert normalize("Mélenchon @truc.bsky.social https://x.fr/a ÉCOUTE !!") == "melenchon ecoute"


def test_entites_lues_dans_le_fichier_du_lexique():
    ent = load_entites()
    ids = {e["id"] for e in ent}
    assert ENTITES_PATH.name == "entites.yaml" and ENTITES_PATH.exists()
    assert {"le pen", "rassemblement national", "melenchon", "lfi", "attal"} <= ids
    choix = entity_choices(load_schema(), ent)
    assert set(choix) == ids | {"gouvernement", "groupe-politique", "autre"}
    assert choix[-3:] == ["gouvernement", "groupe-politique", "autre"]
    assert len(choix) == len(set(choix))


def test_plus_de_liste_groupes_dans_le_code():
    import annotation.common as c
    assert not hasattr(c, "GROUPES") and not hasattr(c, "read_identites")


def test_detection_personne_et_parti_distincts():
    amap = alias_map(ENT)
    assert detect_entities("Le RN et Le Pen, rassemblement national", amap)[0] == ["rassemblement national", "le pen"]
    assert detect_entities("Mélenchon puis LFI", amap)[0] == ["melenchon", "lfi"]
    assert detect_entities("Jean-Luc Mélenchon", amap)[0] == ["melenchon"]
    assert detect_entities("le journal ouvrier tourne", amap) == ([], [])  # 'rn' dans 'journal' : pas de match
    assert detect_entities("le gouvernement tombe", amap)[0] == ["gouvernement"]


def test_alias_ambigu_propose_comme_incertain():
    amap = alias_map(ENT)
    assert detect_entities("Philippe a parlé", amap) == ([], ["edouard philippe"])
    assert detect_entities("Edouard Philippe puis philippe", amap) == (["edouard philippe"], [])


def test_handles_retires_avant_detection():
    amap = alias_map(ENT)
    assert detect_entities("promo @gabriel-attal.bsky.social cliquez", amap) == ([], [])
    assert detect_entities("Attal arrive, merci @attal.bsky.social", amap)[0] == ["attal"]


def test_fichier_reel_toutes_entites_detectables():
    amap = alias_map(load_entites())
    assert detect_entities("Marine Le Pen et le RN", amap)[0] == ["le pen", "rassemblement national"]
    assert detect_entities("@gabriel-attal.bsky.social", amap) == ([], [])


def test_filtre_posts_courts():
    posts = [{"text": "ok merci"}, {"text": "https://a.fr @x trois mots ici"}, {"text": "assez de mots dans ce post"}]
    kept, n = prepare.filter_short(posts)
    assert n == 2 and kept[0]["text"].startswith("assez")


def test_dedoublonnage_exact_et_quasi():
    base = "le candidat a parlé de la retraite et de la sécurité hier soir à la télé"
    posts = [
        {"post_id": "1", "created_at": "2026-10-01T10:00:00Z", "text": base},
        {"post_id": "2", "created_at": "2026-10-01T11:00:00Z", "text": base.upper() + " https://x.fr"},   # exact après normalisation
        {"post_id": "3", "created_at": "2026-10-01T12:00:00Z", "text": base + " vraiment"},                # quasi
        {"post_id": "4", "created_at": "2026-10-01T13:00:00Z", "text": "tout autre sujet sans rapport du tout avec le reste"},
    ]
    out, st = prepare.dedupe(posts)
    assert [p["post_id"] for p in out] == ["1", "4"]
    assert st == {"exacts": 1, "quasi": 1}


def test_quasi_doublon_ne_touche_pas_les_textes_differents():
    posts = [{"post_id": str(i), "created_at": "2026-10-01T10:00:00Z",
              "text": f"sujet {i} {w}"} for i, w in enumerate(["alpha beta gamma delta", "epsilon zeta eta theta"])]
    assert len(prepare.dedupe(posts)[0]) == 2


def _prep(n=60):
    posts = make_posts(n)
    prepare.annotate_entities(posts, alias_map(
        [{"id": n, "alias": [{"forme": n, "ambigu": False}]} for n in ("dupont", "martin", "durand")]))
    prepare.assign_slots(posts)
    prepare.assign_strata(posts)
    return posts


def test_tirage_reproductible_et_sans_doublon():
    posts = _prep()
    a = prepare.stratified_sample(posts, 20, seed=1)
    b = prepare.stratified_sample(posts, 20, seed=1)
    c = prepare.stratified_sample(posts, 20, seed=2)
    assert [p["post_id"] for p in a] == [p["post_id"] for p in b]
    assert [p["post_id"] for p in a] != [p["post_id"] for p in c]
    assert len({p["post_id"] for p in a}) == 20


def test_tirage_stratifie_parts_egales_et_part_aucune():
    posts = _prep(60)  # 15 'aucune', 15 de chaque entité
    ech = prepare.stratified_sample(posts, 20, seed=1, part_aucune=0.25)
    c = Counter(p["strate"] for p in ech)
    assert c["aucune"] == 5
    assert set(c) - {"aucune"} == {"dupont", "martin", "durand"}
    assert max(c[e] for e in ("dupont", "martin", "durand")) - min(c[e] for e in ("dupont", "martin", "durand")) <= 1


def test_petite_strate_prise_en_entier_et_reste_redistribue():
    posts = _prep(60)
    rares = [p for p in posts if p["strate"] == "dupont"][:2]
    autres = [p for p in posts if p["strate"] != "dupont"]
    ech = prepare.stratified_sample(rares + autres, 30, seed=1)
    assert len(ech) == 30
    assert sum(p["strate"] == "dupont" for p in ech) == 2


def test_tirage_tourne_sur_les_tranches_temporelles():
    posts = _prep(60)
    ech = [p for p in prepare.stratified_sample(posts, 30, seed=3) if p["strate"] == "martin"]
    assert len({p["slot"] for p in ech}) > 1


def test_decoupe_en_tranches_du_jour_dominant():
    posts = [{"created_at": "2026-10-12T0%dh".replace("%d", "1") + ":00:00Z"} for _ in range(9)]
    posts.append({"created_at": "2026-10-01T10:00:00Z"})
    prepare.assign_slots(posts)
    assert posts[0]["slot"] == "2026-10-12T00h" and posts[-1]["slot"] == "2026-10-01"


def test_lots_sans_recouvrement_et_complets():
    posts = _prep(60)
    lots = prepare.build_lots(posts, pilote=5, n_eval=10, taille_lot=20, seed=7)
    ids = [p["post_id"] for rows in lots.values() for p in rows]
    assert len(ids) == len(set(ids)) == 60
    assert len(lots["lot_00_pilote"]) == 5 and len(lots["lot_eval"]) == 10
    assert list(lots)[2:] == ["lot_01", "lot_02", "lot_03"]


def test_pipeline_cli_sur_base_synthetique(db, tmp_path, monkeypatch):
    cdir = tmp_path / "corpus"
    prepare.main(["--db", str(db), "--corpus-dir", str(cdir), "--pilote", "1", "--eval", "1", "--taille-lot", "5"])
    plan = (cdir / "annotation" / "lots" / "plan.json").read_text()
    assert '"bruts": 5' in plan and '"trop_courts": 1' in plan and '"doublons_exacts": 1' in plan
