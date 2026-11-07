"""Identité de l'entrée du modèle : le streaming produit les mêmes jetons que l'entraînement.

`src/streaming/` ne importe pas `src/training/` : ce test, hors `src/`, charge les deux modules par
leur chemin et compare, sur des textes et des cibles inventés, les identifiants de jetons
(stance et émotion, avec et sans `normaliser`, avec et sans `noms_cibles`, troncature comprise).
Tokenizer minuscule construit sans réseau.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]


def _charger(nom: str, chemin: Path):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module  # requis par @dataclass
    spec.loader.exec_module(module)
    return module


# donnees.py importe projection_stance et projection_emotion, à la racine de src/training/.
sys.path.insert(0, str(RACINE / "src" / "training"))
donnees = _charger("entree_entrainement", RACINE / "src/training/modele/donnees.py")
streaming = _charger("entree_streaming", RACINE / "src/streaming/modeles.py")

# Textes et cibles inventés : accents, majuscules, ponctuation, cible hors liste de noms.
TEXTES = [
    "Zib zob ÉLÉPHANT alpha soutien, vraiment !",
    "bof mystère lfi : Crème brûlée à Noël",
    "Le Pen rage zib zob",
    "joie zob été éteint, gouvernement et groupe-politique",
    "court",
    "entite-inconnue zob alpha " * 6,
]
CIBLES = ["alpha", "lfi", "le pen", "gouvernement", "groupe-politique", "entite-inconnue"]
NOMS = {"alpha": "Alpha Ésa", "lfi": "LFI", "le pen": "Marine Le Pen"}


@pytest.fixture(scope="module")
def tokenizer():
    from tokenizers import Tokenizer, models, pre_tokenizers, processors, trainers
    from transformers import PreTrainedTokenizerFast

    tk = Tokenizer(models.WordPiece(unk_token="<unk>"))
    tk.pre_tokenizer = pre_tokenizers.Whitespace()
    corpus = TEXTES + CIBLES + list(NOMS.values()) + ["Éléphant", "Crème", "été", "Noël"]
    tk.train_from_iterator(corpus, trainers.WordPieceTrainer(
        vocab_size=200, special_tokens=["<s>", "<pad>", "</s>", "<unk>", "<mask>"]))
    tk.post_processor = processors.TemplateProcessing(
        single="<s> $A </s>", pair="<s> $A </s> </s> $B </s>",
        special_tokens=[("<s>", tk.token_to_id("<s>")), ("</s>", tk.token_to_id("</s>"))])
    return PreTrainedTokenizerFast(
        tokenizer_object=tk, bos_token="<s>", eos_token="</s>", unk_token="<unk>", sep_token="</s>",
        cls_token="<s>", pad_token="<pad>", mask_token="<mask>")


@pytest.mark.parametrize("normaliser", [False, True])
@pytest.mark.parametrize("noms", [NOMS, {}], ids=["noms", "sans_noms"])
@pytest.mark.parametrize("longueur_max", [16, 64])
def test_stance_jetons_identiques(tokenizer, normaliser, noms, longueur_max):
    attendu = donnees.jetons(tokenizer, TEXTES, CIBLES, "stance", noms, longueur_max, normaliser)
    obtenu = streaming.jetons(tokenizer, TEXTES, CIBLES, "stance", noms, longueur_max, normaliser)
    assert obtenu == attendu
    assert all(len(ids) <= longueur_max for ids in obtenu)


@pytest.mark.parametrize("normaliser", [False, True])
@pytest.mark.parametrize("longueur_max", [16, 64])
def test_emotion_jetons_identiques(tokenizer, normaliser, longueur_max):
    attendu = donnees.jetons(tokenizer, TEXTES, None, "emotion", {}, longueur_max, normaliser)
    obtenu = streaming.jetons(tokenizer, TEXTES, None, "emotion", {}, longueur_max, normaliser)
    assert obtenu == attendu


@pytest.mark.parametrize("normaliser", [False, True])
def test_paires_entree_identiques(normaliser):
    for texte, cible in zip(TEXTES, CIBLES):
        attendu = donnees.entree_modele(texte, cible, NOMS, normaliser)
        assert streaming.entree_modele(texte, cible, NOMS, normaliser) == attendu
    for texte in TEXTES:
        assert streaming.entree_modele(texte, None, {}, normaliser) == donnees.entree_modele(texte, None, {}, normaliser)


def test_normalisation_identique():
    for texte in TEXTES + CIBLES:
        assert streaming.normaliser_contrat(texte) == donnees.normaliser_contrat(texte)
        assert streaming.nom_cible(texte) == donnees.nom_cible(texte)


# Textes inventés pour le nettoyage : URL (http, https, www), handles, did:, accents, majuscules,
# espaces multiples, tabulations, chaîne vide.
CHAINES_NETTOYAGE = [
    "Bonjour   LE   monde !!",
    "Voir https://exemple.org/a?b=c, c'est bien",
    "lien http://exemple.fr/page fin",
    "lien www.exemple.fr/page fin",
    "@alice.bsky.social soutien total",
    "Mélange @Zoé.Dupont et https://x.y/z fin",
    "did:plc:abc123 pour le candidat",
    "Élève à l'école, Noël très ÉTÉ",
    "tab\tet\nretour  à la ligne",
    "Sans rien à masquer.",
    "Ça  coûte   1 000 € ; 3 % d'ÉCART",
    "",
]


def test_nettoyage_identique_au_job_spark():
    # pii importe pyspark : seul ce test est sauté si pyspark manque (hors environnement d'entraînement).
    pytest.importorskip("pyspark")
    pii = _charger("entree_streaming_pii", RACINE / "src/streaming/pii.py")
    for texte in CHAINES_NETTOYAGE:
        assert donnees.nettoyer_comme_spark(texte) == pii.nettoyer_texte(texte), texte
    assert donnees.nettoyer_comme_spark(None) == pii.nettoyer_texte(None) == ""
