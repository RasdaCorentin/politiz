"""Reprise après expiration de l'état du checkpoint (règle M6). Sans Spark : fonctions pures et faux."""
import pytest

import job

# message réel de Spark après l'expiration de `streaming/state/` (constaté le 26/10)
MESSAGE_ETAT_PERDU = (
    "IllegalStateException: Error reading delta file "
    "s3a://checkpoints/streaming/state/0/0/1.delta of HDFSStateStoreProvider"
    "[id = (op=0,part=0)]: s3a://checkpoints/streaming/state/0/0/1.delta does not exist"
    " java.io.FileNotFoundException: No such file or directory"
)


class FauxFileSystem:
    def __init__(self):
        self.appels = []

    def delete(self, chemin, recursif):
        self.appels.append((chemin, recursif))
        return True


def test_message_reel_etat_perdu():
    assert job.etat_checkpoint_perdu(MESSAGE_ETAT_PERDU) is True


def test_file_not_found_hors_state_non_reinitialise():
    message = "FileNotFoundException: s3a://checkpoints/streaming/offsets/3 does not exist"
    assert job.etat_checkpoint_perdu(message) is False


def test_autre_erreur_non_reinitialisee():
    assert job.etat_checkpoint_perdu("ValueError: colonne inconnue, chemin streaming/state/") is False


def test_chaine_de_causes_repere_l_etat_perdu():
    cause = OSError(MESSAGE_ETAT_PERDU)
    exc = RuntimeError("StreamingQueryException: le micro-lot a échoué")
    exc.__cause__ = cause
    assert job.etat_checkpoint_perdu(job.chaine_messages(exc)) is True


def test_chaine_de_causes_sans_boucle_infinie():
    a = RuntimeError("a")
    b = RuntimeError("b")
    a.__cause__ = b
    b.__cause__ = a
    assert job.chaine_messages(a) == "a\nb"


def test_suppression_recursive_du_checkpoint():
    fs = FauxFileSystem()
    chemin = "s3a://checkpoints/streaming/"
    job.supprimer_checkpoint(fs, chemin)
    assert fs.appels == [(chemin, True)]


def test_etat_perdu_declenche_suppression_puis_sortie_non_nulle():
    appels = []
    with pytest.raises(SystemExit) as sortie:
        job.traiter_arret(RuntimeError(MESSAGE_ETAT_PERDU), lambda: appels.append("efface"))
    assert sortie.value.code == job.CODE_REINITIALISATION != 0
    assert appels == ["efface"]


def test_autre_erreur_relancee_sans_suppression():
    appels = []
    erreur = ValueError("erreur sans rapport avec le checkpoint")
    with pytest.raises(ValueError) as recu:
        job.traiter_arret(erreur, lambda: appels.append("efface"))
    assert recu.value is erreur
    assert appels == []


def test_file_not_found_hors_state_relancee_sans_suppression():
    appels = []
    erreur = RuntimeError("FileNotFoundException: s3a://checkpoints/streaming/commits/7")
    with pytest.raises(RuntimeError):
        job.traiter_arret(erreur, lambda: appels.append("efface"))
    assert appels == []


def test_chemin_checkpoint_depuis_la_configuration():
    cfg = job.Config(bucket_checkpoints="checkpoints")
    assert job.chemin_checkpoint(cfg) == "s3a://checkpoints/streaming/"
