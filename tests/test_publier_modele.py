"""Tests de scripts/publier_modele.py : seule l'étape `mc pipe` lit l'entrée standard."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import publier_modele as P  # noqa: E402


def test_seul_mc_pipe_lit_l_entree_standard():
    etapes = P.commande_distante("modeles/run.tar", "mc:1", "", creer_bucket=True).split("; ")
    lisent = [e for e in etapes if "docker run -i " in e]
    assert len(lisent) == 1 and lisent[0].endswith("pipe sae/modeles/run.tar")
    assert any("mb --ignore-existing sae/modeles </dev/null" in e for e in etapes)


def test_sudo_en_tete_des_commandes_docker():
    etapes = P.commande_distante("modeles/run.tar.sha256", "mc:1", "sudo -n", creer_bucket=False)
    assert "sudo -n docker run -i --rm" in etapes
