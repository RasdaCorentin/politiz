"""Tests du prédicteur sur des runs produits par la CLI, avec le modèle minuscule et un corpus inventé."""
import numpy as np
import pytest
import torch

from modele import donnees
from modele.entrainer import analyser_arguments, executer
from modele.predict import Predicteur, mesurer_latence
from modele.tests import outils


@pytest.fixture(scope="session")
def runs(modele_minuscule, tmp_path_factory):
    """Un run stance et un run emotion, entraînés une époque chacun (CPU, 2 threads)."""
    torch.set_num_threads(2)
    racine = tmp_path_factory.mktemp("runs-predict")
    corpus = outils.creer_corpus(racine / "corpus")
    sorties = {}
    for tache in ("stance", "emotion"):
        args = analyser_arguments(["--tache", tache, "--corpus", str(corpus), "--sortie", str(racine / tache),
                                   "--base", str(modele_minuscule), "--appareil", "cpu",
                                   "--longueur-max", "64", "--epoques", "1", "--lr", "3e-3"])
        sorties[tache] = executer(args)
    return sorties


def test_predire_stance_forme_et_probabilites(runs):
    p = Predicteur(runs["stance"], threads=2)
    textes = ["bravo soutien Melenchon puis honte demission Glucksmann", "mais equilibre LFI"]
    cibles = ["melenchon", "lfi"]
    res = p.predire(textes, cibles)
    assert len(res) == 2
    for r in res:
        assert r["etiquette"] in donnees.etiquettes("stance")
        assert set(r["probabilites"]) == set(donnees.etiquettes("stance"))
        assert sum(r["probabilites"].values()) == pytest.approx(1.0, abs=1e-4)
        assert r["confiance"] == pytest.approx(max(r["probabilites"].values()))


def test_stance_exige_une_cible_par_texte(runs):
    p = Predicteur(runs["stance"], threads=2)
    with pytest.raises(ValueError, match="cible"):
        p.predire(["texte inventé"])
    with pytest.raises(ValueError, match="cible"):
        p.predire(["texte inventé", "autre texte"], ["lfi"])


def test_emotion_sans_cible(runs):
    p = Predicteur(runs["emotion"], threads=2)
    res = p.predire(["youpi lundi", "rage mardi", "factuel"])
    assert all(r["etiquette"] in donnees.etiquettes("emotion") for r in res)


def test_lots_sans_effet_sur_le_resultat(runs):
    """Le remplissage et le masque ne changent pas les probabilités : lot de 1 ou de 16, même résultat."""
    p = Predicteur(runs["stance"], threads=2)
    textes = [f"bravo soutien Melenchon {'puis honte demission ' * (i % 4)}lundi {i}" for i in range(9)]
    cibles = ["melenchon"] * 9
    un_a_un = p.probabilites(textes, cibles, taille_lot=1)
    par_lots = p.probabilites(textes, cibles, taille_lot=16)
    assert np.allclose(un_a_un, par_lots, atol=1e-5)


def test_ordre_des_textes_restitue(runs):
    p = Predicteur(runs["stance"], threads=2)
    textes = ["texte un", "un texte beaucoup plus long que le premier pour mélanger les longueurs", "trois"]
    cibles = ["lfi", "lfi", "le pen"]
    complet = p.probabilites(textes, cibles)
    seul = p.probabilites([textes[1]], [cibles[1]])
    assert np.allclose(complet[1], seul[0], atol=1e-5)


def test_appareil_inconnu_ou_indisponible_refuse(runs):
    with pytest.raises(ValueError):
        Predicteur(runs["stance"], appareil="mps")
    if not torch.cuda.is_available():
        with pytest.raises(RuntimeError, match="CUDA"):
            Predicteur(runs["stance"], appareil="cuda")


def test_mesure_de_latence_structure(runs):
    p = Predicteur(runs["emotion"], threads=2)
    res = mesurer_latence(p, ["youpi", "rage", "factuel", "triste"], threads=(2,), tailles_lot=(1, 4), n_max=4)
    assert res["n_posts"] == 4
    assert set(res["ms_par_post"]) == {"threads=2,lot=1", "threads=2,lot=4"}
    assert all(v >= 0 for v in res["ms_par_post"].values())


def test_ancien_run_sans_cle_nettoyer_garde_son_entree(runs, tmp_path):
    """Un run écrit avant l'option n'a pas la clé `nettoyer` : son entrée reste celle d'origine."""
    import json
    import shutil

    brut = ["voir https://exemple.org/a [url] youpi [mention] lundi", "rage @dan.test mardi"]
    ancien = tmp_path / "ancien"
    shutil.copytree(runs["emotion"], ancien)
    meta = json.loads((ancien / "modele.json").read_text(encoding="utf-8"))
    del meta["entree"]["nettoyer"]
    (ancien / "modele.json").write_text(json.dumps(meta), encoding="utf-8")

    p_ancien = Predicteur(ancien, threads=2)
    assert p_ancien.nettoyer is False
    assert p_ancien.encoder(brut) == donnees.jetons(p_ancien.tokenizer, brut, None, "emotion", {}, 64, True)

    p_nouveau = Predicteur(runs["emotion"], threads=2)
    assert p_nouveau.nettoyer is True
    prepares = [donnees.preparer_texte(t) for t in brut]
    assert p_nouveau.encoder(brut) == donnees.jetons(p_nouveau.tokenizer, prepares, None, "emotion", {}, 64, True)
