"""Tests de scripts/analyse_lexique.py et de la bibliothèque ressources/lexique/.

Lancer : uv run --with pyyaml --with pytest pytest tests/test_analyse_lexique.py
Tous les textes ci-dessous sont inventés (aucun post réel).
"""
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import analyse_lexique as A  # noqa: E402


@pytest.fixture(scope="module")
def lex():
    return A.load_lexique()


def n(text):
    return A.strip_mentions(A.normalize(text))


# --- normalisation ------------------------------------------------------------
def test_normalize_accents_et_casse():
    assert A.normalize("Présidentielle MÉLENCHON") == "presidentielle melenchon"


def test_normalize_identique_a_l_ingestion():
    """Même résultat que src/ingestion/ingestion.py (si le fichier est présent)."""
    path = os.path.join(A.REPO_ROOT, "src", "ingestion", "ingestion.py")
    if not os.path.exists(path):
        pytest.skip("ingestion.py absent")
    src = open(path, encoding="utf-8").read()
    ns = {}
    start = src.index("def normalize")
    end = src.index("# classes machine-lisibles")
    exec("import re\nimport unicodedata\n" + src[start:end], ns)
    for t in ["Élisabeth Borne", "Hé ! ÇA va", "été 2026 — ñ"]:
        assert ns["normalize"](t) == A.normalize(t)


def test_strip_mentions():
    assert "attal" not in A.strip_mentions(A.normalize("hello @gabriel-attal.bsky.social voila"))
    assert "lfi" in A.strip_mentions(A.normalize("vive la LFI @lfi.bsky.social"))


def test_ngrams_sans_mots_vides_aux_bords():
    toks = A.tokenize("le second tour de la presidentielle")
    assert "second tour" in A.ngrams(toks, 2)
    assert "tour de" not in A.ngrams(toks, 2)
    assert "le second" not in A.ngrams(toks, 2)


def test_tokenize_retire_les_urls():
    assert A.tokenize("voir https://exemple.org/page lfi") == ["voir", "lfi"]


def test_emojis():
    assert A.emojis_of("ok 🤮 et 🇫🇷!") [0] == "🤮"
    assert A.emojis_of("texte sans emoji") == []


def test_alt_regex_frontieres_de_mot():
    import re
    rx = re.compile(A.alt_regex(["loi"]))
    assert rx.search("la loi passe")
    assert not rx.search("un loisir")


def test_parse_keywords_classes():
    kw = A.parse_keywords(A.DEFAULT_KEYWORDS)
    assert set(kw) == set(A.SECTIONS_KEYWORDS)
    assert "melenchon" in kw["identites"] and "gauche" in kw["orientations"]


def test_quasi_doublons():
    posts = [{"norm": A.normalize(f"Rapport {i} : chaud jamais enregistré cet été ici")} for i in range(6)]
    posts.append({"norm": "autre chose"})
    kept, retires = A.dedoublonner(posts)
    assert retires == 5 and len(kept) == 2


# --- chargement et schéma -------------------------------------------------------
def test_lexique_charge(lex):
    assert len(lex.entites) > 50 and len(lex.stance) > 20 and len(lex.themes) == 9


def test_entites_valeurs_autorisees(lex):
    for e in lex.entites:
        assert e["type"] in A.TYPES_ENTITE
        assert e["camp"] in A.CAMPS_ENTITE
        assert "nom" not in e or e["nom"].strip()
        for a in e["alias"]:
            assert a["forme"] == A.normalize(a["forme"])
            assert isinstance(a["ambigu"], bool)


def test_camp_nom_renseignes(lex):
    assert all(e.get("nom") for e in lex.entites)
    assert {e["camp"] for e in lex.entites} == {"gauche", "centre", "droite", None}


def test_camps_coherents_avec_le_document(lex):
    """Le tableau de docs/technique/camps-candidats.md reprend id et camp de entites.yaml."""
    doc = os.path.join(os.path.dirname(__file__), "..", "docs", "technique", "camps-candidats.md")
    tableau = {}
    for ligne in open(doc, encoding="utf-8"):
        if ligne.startswith("| `"):
            cellules = [c.strip() for c in ligne.strip().strip("|").split("|")]
            tableau[cellules[0].strip("`")] = cellules[3]
    attendu = {e["id"]: (e["camp"] or "null") for e in lex.entites}
    assert tableau == attendu


def test_alias_de_keywords_tous_couverts(lex):
    kw = A.parse_keywords(A.DEFAULT_KEYWORDS)["identites"]
    manquants = [k for k in kw if k not in lex.alias]
    assert manquants == []


def test_stance_valeurs_autorisees(lex):
    ids = {e["id"] for e in lex.entites}
    for r in lex.stance:
        assert r["stance"] in A.STANCES
        assert r["confiance"] in A.CONFIANCES
        assert r["cible"] in A.CIBLES_SPECIALES or r["cible"] in ids


def test_themes_et_emotions_dans_le_contrat(lex):
    for t in lex.themes:
        assert t["theme"] in A.THEMES
    for e in lex.emotions:
        assert e["emotion"] in A.EMOTIONS


def test_exemples_de_chaque_regle(lex):
    """Chaque exemple positif déclenche la règle, chaque négatif ne la déclenche pas."""
    for r in lex.stance:
        for ex in r["exemples"]["positifs"]:
            assert r["_re"].search(n(ex)), (r["id"], ex)
        for ex in r["exemples"]["negatifs"]:
            assert not r["_re"].search(n(ex)), (r["id"], ex)


def _ids(lex, text):
    return {h["regle"]: h for h in A.stance_matches(lex, n(text))}


# --- motifs : vrais et faux positifs inventés ---------------------------------
def test_votez_resout_la_cible(lex):
    h = _ids(lex, "Allez, votez Glucksmann !")
    assert h["soutien-votez"]["cible"] == "glucksmann"
    assert h["soutien-votez"]["stance"] == "pour"


def test_negation_je_ne_voterai_pas(lex):
    h = _ids(lex, "Je ne voterai pas Mélenchon")
    assert "rejet-jamais-voter" in h and "soutien-je-vote" not in h


def test_citation_entre_guillemets_ecartee(lex):
    assert "soutien-je-vote" not in _ids(lex, 'il me dit "je voterai Mélenchon" mais je doute')


def test_double_negation_ne_decide_pas(lex):
    assert "rejet-jamais-voter" not in _ids(lex, "je ne voterai jamais pas pour Mélenchon, au contraire")


def test_faux_positif_connu_ironie(lex):
    """Limite documentée : l'ironie passe la règle. Le test fige le comportement."""
    assert "soutien-votez" in _ids(lex, "Votez Hollande, ça marchera mieux que la dernière fois, sûrement")


def test_mention_handle_ne_compte_pas(lex):
    assert lex.entites_dans(n("promo @gabriel-attal.bsky.social cliquez")) == set()
    assert lex.entites_dans(n("Attal arrive")) == {"attal"}


def test_surnom_ambigu_reste_ambigu(lex):
    h = _ids(lex, "on va voter Méluche")
    assert h["surnom-meluche"]["stance"] == "ambigu"


def test_camp_pas_entite(lex):
    h = _ids(lex, "ces islamo-gauchistes")
    assert h["disq-islamo-gauchiste"]["cible"] == "camp"


def test_sondage_mention(lex):
    h = _ids(lex, "Le Pen (RN) : 35 % ; Hollande (PS) : 7 %")
    assert h["mention-sondage"]["stance"] == "mention"


def test_stances_et_cibles_du_contrat():
    assert A.STANCES == ("pour", "contre", "neutre", "mention", "ambigu")
    assert "groupe-politique" in A.CIBLES_SPECIALES


def test_refus_de_soutien_est_contre(lex):
    for texte, regle in [("Je ne voterai pas Mélenchon", "rejet-jamais-voter"),
                         ("je ne voterai jamais Philippe", "rejet-jamais-voter"),
                         ("Je ne soutiens pas Glucksmann", "rejet-ne-soutiens-pas")]:
        assert _ids(lex, texte)[regle]["stance"] == "contre"


def test_aucune_regle_neutre_sur_format_de_sondage(lex):
    assert not [r for r in lex.stance if r["famille"] == "information" and r["stance"] != "mention"]


def test_cible_groupe_politique_acceptee(copie):
    p = copie / "stance.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("cible: camp\n", "cible: groupe-politique\n", 1), encoding="utf-8")
    assert any(r["cible"] == "groupe-politique" for r in A.load_lexique(str(copie)).stance)


def test_themes(lex):
    th = {t for t, _, c in A.theme_matches(lex, n("La réforme des retraites et le budget")) if c == "haute"}
    assert {"social-retraites", "economie"} <= th
    assert not A.theme_matches(lex, n("bonjour tout le monde"))


def test_emojis_emotion(lex):
    em = A.emotion_matches(lex, "beurk 🤮", n("beurk 🤮"))
    assert ("degout", "🤮|🤢", "haute") in em


# --- validation du schéma : les erreurs sont détectées ---------------------------
@pytest.fixture
def copie(tmp_path):
    d = tmp_path / "lexique"
    shutil.copytree(A.DEFAULT_LEXIQUE, d)
    return d


def test_schema_stance_invalide(copie):
    p = copie / "stance.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("stance: pour", "stance: favorable", 1), encoding="utf-8")
    with pytest.raises(A.LexiqueError, match="stance"):
        A.load_lexique(str(copie))


def test_schema_theme_hors_contrat(copie):
    p = copie / "themes.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("theme: economie", "theme: finances", 1), encoding="utf-8")
    with pytest.raises(A.LexiqueError, match="thème"):
        A.load_lexique(str(copie))


def test_schema_camp_invalide(copie):
    p = copie / "entites.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("camp: droite", "camp: extreme", 1), encoding="utf-8")
    with pytest.raises(A.LexiqueError, match="camp"):
        A.load_lexique(str(copie))


def test_schema_nom_vide(copie):
    p = copie / "entites.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace('nom: "Marine Le Pen"', 'nom: ""', 1), encoding="utf-8")
    with pytest.raises(A.LexiqueError, match="nom"):
        A.load_lexique(str(copie))


def test_schema_type_entite_invalide(copie):
    p = copie / "entites.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("type: parti", "type: mouvement", 1), encoding="utf-8")
    with pytest.raises(A.LexiqueError, match="type"):
        A.load_lexique(str(copie))


def test_schema_emotion_hors_contrat(copie):
    p = copie / "emotions.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("emotion: joie", "emotion: euphorie", 1), encoding="utf-8")
    with pytest.raises(A.LexiqueError, match="émotion"):
        A.load_lexique(str(copie))
