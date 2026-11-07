"""Fixtures partagées : corpus factice et petit modèle, construits dans un dossier temporaire."""
import pytest

from modele.tests import outils


@pytest.fixture
def corpus(tmp_path):
    """Corpus factice (silver, pilote, évaluation figée), hors dépôt."""
    return outils.creer_corpus(tmp_path / "corpus")


@pytest.fixture(scope="session")
def modele_minuscule(tmp_path_factory):
    """Dossier d'un CamemBERT aléatoire minuscule, construit une fois par session."""
    return outils.creer_modele_minuscule(tmp_path_factory.mktemp("tiny"))
