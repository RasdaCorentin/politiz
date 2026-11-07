"""Tests du comptage d'adjectifs sur données synthétiques, avec un tagueur factice (sans spaCy)."""
from adjectifs.comptage import (adjectifs_du_texte, cibles_du_post, charger_entites, compter,
                                controle_gold, distance_levenshtein, ecrire_csv, lignes, masquer,
                                normaliser, regrouper, vue)

ENTITES = {
    "bardella": {"id": "bardella", "type": "candidat", "nom": "Jordan Bardella", "parti": "rn"},
    "rn": {"id": "rn", "type": "parti", "nom": "Rassemblement national"},
    "glucksmann": {"id": "glucksmann", "type": "candidat", "nom": "Raphaël Glucksmann"},
    "autre": {"id": "autre", "type": "parti", "nom": "Autre"},
}
# Tagueur factice : texte -> couples (forme, lemme) des adjectifs.
TAGS = {
    "Bardella est ridicule et ridicule.": [("ridicule", "ridicule"), ("ridicule", "ridicule")],
    "Glucksmann est brillant. Brillant !": [("brillant", "brillant"), ("Brillant", "brillant")],
    "Le RN est dangereux et court.": [("dangereux", "dangereux"), ("court", "court")],
    "Il est là.": [("là", "là")],
}


def tagueur(textes):
    return [TAGS.get(t, []) for t in textes]


def post(pid, texte, *cibles):
    return {"post_id": pid, "text": texte,
            "cibles": [{"entite": e, "stance": s} for e, s in cibles]}


def test_masquer_urls_et_mentions_casse_conservee():
    texte = "Voir https://exemple.org/x et @alice.bsky ici, Bardella est Fort"
    assert masquer(texte) == "Voir <url> et @utilisateur ici, Bardella est Fort"


def test_phrase_fabriquee_produit_les_bonnes_lignes():
    posts = [post(1, "Bardella est ridicule et ridicule.", ("bardella", "contre"))]
    compte, stats = compter(posts, ENTITES, tagueur)
    assert lignes(compte) == [("ridicule", "Rassemblement national", "Jordan Bardella", "contre", 1)]
    assert (stats["posts"], stats["posts_avec_cible"]) == (1, 1)


def test_parti_sans_representant_et_parti_resolu_pour_candidat():
    posts = [post(1, "Le RN est dangereux et court.", ("rn", "pour")),
             post(2, "Bardella est ridicule et ridicule.", ("bardella", "pour"))]
    compte, _ = compter(posts, ENTITES, tagueur)
    assert ("dangereux", "Rassemblement national", "", "pour") in compte
    assert ("ridicule", "Rassemblement national", "Jordan Bardella", "pour") in compte


def test_candidat_sans_champ_parti_laisse_parti_vide():
    assert cibles_du_post(post(1, "x", ("glucksmann", "pour")), ENTITES) == {("", "Raphaël Glucksmann", "pour")}


def test_post_sans_cible_ne_produit_rien():
    posts = [post(1, "Bardella est ridicule et ridicule.")]
    assert compter(posts, ENTITES, tagueur)[0] == {}


def test_cible_hors_lexique_ignoree():
    posts = [post(1, "Bardella est ridicule et ridicule.", ("groupe-politique", "contre"))]
    assert compter(posts, ENTITES, tagueur)[0] == {}


def test_stance_reprise_telle_quelle():
    posts = [post(1, "Glucksmann est brillant. Brillant !", ("glucksmann", "mention"))]
    compte, _ = compter(posts, ENTITES, tagueur)
    assert {cle[3] for cle in compte} == {"mention"}


def test_occurrences_par_post_distinct():
    # « ridicule » apparaît deux fois dans le post 1 : compté une fois.
    posts = [post(1, "Bardella est ridicule et ridicule.", ("bardella", "contre")),
             post(2, "Bardella est ridicule et ridicule.", ("bardella", "contre")),
             post(3, "Bardella est ridicule et ridicule.", ("bardella", "pour"))]
    compte, _ = compter(posts, ENTITES, tagueur)
    assert compte[("ridicule", "Rassemblement national", "Jordan Bardella", "contre")] == 2
    assert compte[("ridicule", "Rassemblement national", "Jordan Bardella", "pour")] == 1


def test_adjectif_de_moins_de_3_caracteres_ignore():
    assert adjectifs_du_texte([("là", "là"), ("court", "court")]) == {"court"}


def test_lemme_en_minuscules():
    assert adjectifs_du_texte([("Brillant", "Brillant")]) == {"brillant"}


def test_csv_en_tete_exact_et_quoting(tmp_path):
    chemin = tmp_path / "adjectifs.csv"
    ecrire_csv(chemin, [('a"b', "", "Jordan Bardella", "contre", 2)])
    lignes_ = chemin.read_text(encoding="utf-8").splitlines()
    assert lignes_[0] == '"adjectif","parti","représentant",stance,occurrences'
    assert lignes_[1] == '"a""b","","Jordan Bardella",contre,2'


def test_controle_gold_compte_sans_compter_les_posts():
    silver = {"1": {"post_id": "1", "cibles": [{"entite": "bardella", "stance": "contre"}]},
              "2": {"post_id": "2", "cibles": [{"entite": "rn", "stance": "pour"}]}}
    gold = [{"post_id": "1", "cibles": [{"entite": "bardella", "stance": "pour"}]},
            {"post_id": "2", "cibles": [{"entite": "rn", "stance": "pour"}, {"entite": "inconnu", "stance": "pour"}]},
            {"post_id": "9", "cibles": []}]
    # Post 1 : même entité, stance différente. Post 2 : une cible de plus côté gold.
    assert controle_gold(gold, silver, ENTITES) == {
        "posts_gold": 3, "absents_silver": 1, "cibles_hors_lexique": 1,
        "entites_identiques": 1, "cibles_identiques": 0}


LIGNES = [
    ("fort", "", "A", "pour", 5),
    ("fort", "", "A", "contre", 9),
    ("nul", "", "A", "contre", 4),
    ("rare", "", "A", "contre", 2),   # sous le seuil de 3
    ("beau", "", "B", "pour", 3),     # au seuil : retenu
    ("beau", "", "B", "neutre", 40),  # autre stance : jamais dans une vue pour/contre
]


def test_vue_popularite_ne_garde_que_pour_classee_et_seuil():
    assert vue(LIGNES, "pour") == [("fort", "", "A", "pour", 5), ("beau", "", "B", "pour", 3)]


def test_vue_depopularite_ne_garde_que_contre_classee_et_seuil():
    assert vue(LIGNES, "contre") == [("fort", "", "A", "contre", 9), ("nul", "", "A", "contre", 4)]


def test_vues_sont_des_sous_ensembles_sans_modifier_la_source():
    avant = list(LIGNES)
    assert set(vue(LIGNES, "pour")) <= set(LIGNES) and set(vue(LIGNES, "contre")) <= set(LIGNES)
    assert LIGNES == avant


def test_lexique_reel_lisible():
    entites = charger_entites()
    assert entites["rassemblement national"]["type"] == "parti"
    assert entites["bardella"]["type"] == "candidat"


def test_normaliser_casse_accents_et_pluriel():
    assert normaliser("POLITIQUE") == normaliser("Politique") == normaliser("politique") == "politique"
    assert normaliser("énorme") == normaliser("enorme") == "enorme"
    assert normaliser("politiques") == "politique"
    assert normaliser("grands") == "grand"
    assert normaliser("heureux") == "heureu"


def test_normaliser_garde_les_mots_courts_au_pluriel():
    # Moins de 5 lettres : le `s` final reste (« gros » n'est pas « gro »).
    assert normaliser("gros") == "gros"
    assert normaliser("bas") == "bas"


def test_forme_affichee_garde_les_accents_et_la_plus_frequente():
    tags = {
        "un": [("énorme", "énorme")],
        "deux": [("énorme", "énorme")],
        "trois": [("enorme", "enorme")],
    }
    posts = [post(1, "un", ("bardella", "contre")), post(2, "deux", ("bardella", "contre")),
             post(3, "trois", ("bardella", "contre"))]
    compte, _ = compter(posts, ENTITES, lambda ts: [tags[t] for t in ts])
    assert compte == {("énorme", "Rassemblement national", "Jordan Bardella", "contre"): 3}


def test_casse_pluriel_et_accent_comptent_une_seule_fois_par_post():
    tags = {
        "a": [("Politique", "Politique")],
        "b": [("politiques", "politiques")],
        "c": [("POLITIQUE", "POLITIQUE"), ("politique", "politique")],
    }
    posts = [post(1, "a", ("bardella", "pour")), post(2, "b", ("bardella", "pour")),
             post(3, "c", ("bardella", "pour"))]
    compte, stats = compter(posts, ENTITES, lambda ts: [tags[t] for t in ts])
    assert compte == {("politique", "Rassemblement national", "Jordan Bardella", "pour"): 3}
    # Lemmes « politique » et « politiques » (casse ignorée) : 2 lemmes, 1 adjectif affiché.
    assert stats["lemmes_distincts"] == 2
    assert stats["adjectifs_distincts"] == 1


def test_regrouper_forme_la_plus_frequente_puis_alphabetique():
    pids = {"grands": {"1", "2"}, "grand": {"3"}, "bas": {"4"}, "bass": {"5"}}
    affichee = regrouper(pids)
    assert affichee["grands"] == affichee["grand"] == "grands"
    assert affichee["bas"] == "bas"
    # Égalité de fréquence : ordre alphabétique.
    assert regrouper({"zebre": {"1"}, "Zebre": {"2"}}) == {"zebre": "Zebre", "Zebre": "Zebre"}


def test_exclusion_testee_sur_la_clé_normalisee():
    # « Même » et « meme » sont exclus ; « Seules » aussi (clé « seule »).
    assert adjectifs_du_texte([("Même", "Même"), ("meme", "meme"), ("Seules", "Seules")]) == set()
    assert adjectifs_du_texte([("court", "court")]) == {"court"}


def test_distance_levenshtein():
    assert distance_levenshtein("chat", "chats") == 1
    assert distance_levenshtein("kitten", "sitting") == 3
    assert distance_levenshtein("", "abc") == 3
    assert distance_levenshtein("abc", "abc") == 0


def test_faute_de_deux_lettres_sur_mot_long_rattachee_au_plus_frequent():
    # « politqve » : une lettre en moins, une substitution (distance 2, mot de 8 lettres).
    pids = {"politique": {str(i) for i in range(10)}, "politqve": {"10", "11"}}
    affichee = regrouper(pids)
    assert affichee["politique"] == affichee["politqve"] == "politique"
    compte, _ = compter(
        [post(i, "t", ("bardella", "contre")) for i in range(12)],
        ENTITES,
        lambda ts: [[("politique", "politique")] if i < 10 else [("politqve", "politqve")]
                    for i, _ in enumerate(ts)],
    )
    assert compte == {("politique", "Rassemblement national", "Jordan Bardella", "contre"): 12}


def test_faute_sur_mot_court_non_regroupee():
    # « beau » et « bleu » : distance 2 sur des mots de 4 lettres. Seule une distance 1 est admise.
    affichee = regrouper({"beau": {"1", "2", "3"}, "bleu": {"4"}})
    assert affichee == {"beau": "beau", "bleu": "bleu"}


def test_faute_d_une_lettre_sur_mot_court_regroupee():
    assert regrouper({"gros": {"1", "2", "3"}, "gras": {"4"}}) == {"gros": "gros", "gras": "gros"}


def test_initiale_differente_jamais_regroupee():
    affichee = regrouper({"politique": {"1", "2"}, "xolitique": {"3"}})
    assert affichee == {"politique": "politique", "xolitique": "xolitique"}


def test_regroupement_deterministe_a_frequence_egale():
    # Même fréquence de clé : la clé alphabétiquement première sert de représentante.
    pids = {"politique": {"1", "2"}, "politqve": {"3", "4"}}
    attendu = {"politique": "politique", "politqve": "politique"}
    assert regrouper(pids) == attendu
    assert regrouper(dict(reversed(list(pids.items())))) == attendu
