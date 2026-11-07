"""Tests de distant/lancer.py : commandes construites, sans SSH réel (subprocess simulé)."""
from __future__ import annotations

import re
import shlex
import subprocess

import pytest

from distant import lancer


class Faux:
    """Remplace subprocess.run : enregistre les appels, renvoie une sortie fixée."""

    def __init__(self, sortie: str = "", code: int = 0):
        self.appels: list[list[str]] = []
        self.sortie = sortie
        self.code = code

    def __call__(self, argv, **kwargs):
        self.appels.append(list(argv))
        return subprocess.CompletedProcess(argv, self.code, stdout=self.sortie, stderr="")

    def script_du_dernier_appel(self) -> str:
        """Script distant envoyé par ssh : `sh -c '<script>'` est décodé ici."""
        return shlex.split(self.appels[-1][-1])[2]


@pytest.fixture
def faux(monkeypatch):
    f = Faux()
    monkeypatch.setattr(lancer.subprocess, "run", f)
    return f


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SAE_GPU_HOTE", "hote-test")
    monkeypatch.setenv("SAE_GPU_SSH_OPTIONS", "-o BatchMode=yes -o UserKnownHostsFile=/tmp/kh-test")
    monkeypatch.setenv("SAE_CORPUS_DIR", str(tmp_path / "corpus"))
    monkeypatch.delenv("SAE_GPU_DOSSIER", raising=False)
    return tmp_path


def corpus_factice(racine):
    """Corpus inventé : deux fichiers du contrat et des fichiers qui ne doivent jamais partir."""
    (racine / "annotation").mkdir(parents=True)
    (racine / "annotation" / "train_silver.jsonl").write_text('{"post_id": "p1"}\n', encoding="utf-8")
    (racine / "annotation" / "eval_fige.json").write_text('{"n": 1}', encoding="utf-8")
    for rel in ("annotation/annotations/alice.jsonl", "annotation/lots/lot_eval.jsonl",
                "annotation/silver/silver.jsonl", "annotation/train.jsonl"):
        (racine / rel).parent.mkdir(parents=True, exist_ok=True)
        (racine / rel).write_text("{}\n", encoding="utf-8")
    return racine


# --------------------------------------------------------------------------- configuration
def test_hote_obligatoire(monkeypatch, faux, capsys):
    monkeypatch.delenv("SAE_GPU_HOTE", raising=False)
    with pytest.raises(lancer.ErreurDistant, match="SAE_GPU_HOTE"):
        lancer.charger_config()
    assert lancer.main(["verifier"]) == 1
    assert "SAE_GPU_HOTE" in capsys.readouterr().err
    assert faux.appels == []


def test_options_ssh_decoupees(env):
    config = lancer.charger_config()
    assert config.options_ssh == ("-o", "BatchMode=yes", "-o", "UserKnownHostsFile=/tmp/kh-test")
    assert config.dossier == "~/sae-data"


def test_racine_distante_quotee(env):
    assert lancer.racine_shell(lancer.Config("h", (), "~/sae-data", None)) == '"$HOME"/sae-data'
    assert lancer.racine_shell(lancer.Config("h", (), "~", None)) == '"$HOME"'
    assert lancer.racine_shell(lancer.Config("h", (), "/data/sae data", None)) == "'/data/sae data'"


def test_chemin_rsync_relatif(env):
    assert lancer.chemin_rsync(lancer.Config("h", (), "~/sae-data", None), "code", "src") == "sae-data/code/src"
    assert lancer.chemin_rsync(lancer.Config("h", (), "~", None), "code") == "code"


def test_ssh_argv_passe_le_script_quote(env, faux):
    config = lancer.charger_config()
    lancer.distant(config, 'echo "a b"; echo $HOME')
    argv = faux.appels[-1]
    assert argv[0] == "ssh" and argv[-2] == "hote-test"
    assert shlex.split(argv[-1]) == ["sh", "-c", 'D="$HOME"/sae-data\nexport D\necho "a b"; echo $HOME']


# --------------------------------------------------------------------------- commandes
def test_verifier_controle_carte_torch_et_disque(env, faux):
    assert lancer.main(["verifier"]) == 0
    script = faux.script_du_dernier_appel()
    assert "/usr/lib/wsl/lib/nvidia-smi" in script
    assert '"$D/venv/bin/python"' in script
    assert "torch.cuda.is_available()" in script
    assert "df -Ph" in script


def test_envoyer_corpus_seulement_deux_fichiers(env, faux):
    racine = corpus_factice(env / "corpus")
    faux.sortie = "\n".join(str((racine / rel).stat().st_size) for rel in lancer.FICHIERS_CORPUS)
    assert lancer.main(["envoyer-corpus", "--oui"]) == 0
    rsync = next(a for a in faux.appels if a[0] == "rsync")
    sources = [a for a in rsync if str(racine) in a]
    assert sorted(sources) == sorted([
        str(racine / "annotation" / "eval_fige.json"),
        str(racine / "annotation" / "train_silver.jsonl"),
    ])
    assert rsync[-1] == "hote-test:sae-data/corpus/annotation/"
    assert "--chmod=F600,D700" in rsync


def test_envoyer_corpus_sans_confirmation_n_envoie_rien(env, faux, monkeypatch):
    corpus_factice(env / "corpus")
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert lancer.main(["envoyer-corpus"]) == 1
    assert not any(a[0] == "rsync" for a in faux.appels)


def test_envoyer_corpus_avec_confirmation_envoie(env, faux, monkeypatch):
    racine = corpus_factice(env / "corpus")
    monkeypatch.setattr("builtins.input", lambda _: "o")
    # Le contrôle lit les tailles distantes : on renvoie les mêmes que les locales.
    faux.sortie = "\n".join(str((racine / rel).stat().st_size) for rel in lancer.FICHIERS_CORPUS)
    assert lancer.main(["envoyer-corpus"]) == 0
    assert any(a[0] == "rsync" for a in faux.appels)


def test_envoyer_corpus_detecte_une_difference_de_taille(env, faux, monkeypatch):
    corpus_factice(env / "corpus")
    monkeypatch.setattr("builtins.input", lambda _: "o")
    faux.sortie = "0\n0"
    assert lancer.main(["envoyer-corpus"]) == 1


def test_envoyer_code_exclut_caches_et_sorties(env, faux):
    assert lancer.main(["envoyer-code"]) == 0
    rsync = [a for a in faux.appels if a[0] == "rsync"]
    assert len(rsync) == 2
    code = rsync[0]
    for motif in ("__pycache__", ".pytest_cache", "modeles", "runs"):
        assert motif in code
    assert "--delete" in code
    assert code[-2] == f"{lancer.TRAINING_DIR}/"
    assert rsync[1][-2] == f"{lancer.LEXIQUE_LOCAL}/"


def test_entrainer_construit_la_commande(env, faux):
    faux.sortie = ""  # garde : aucun entraînement en cours
    assert lancer.main(["entrainer", "--tache", "stance", "--epoques", "3", "--plafond", "12"]) == 0
    assert len(faux.appels) == 2
    script = faux.script_du_dernier_appel()
    assert "setsid sh -c" in script
    assert "modele.entrainer" in script
    assert "--tache stance" in script
    assert "--epoques" in script and "--plafond" in script
    assert "journaux/stance-$(date +%Y%m%d-%H%M).log" in script
    assert "HF_HOME" in script and "cache/hf" in script


def test_entrainer_module_d_essai(env, faux):
    faux.sortie = ""
    lancer.main(["entrainer", "--tache", "emotion", "--module", "distant.tests.factice_entrainer"])
    assert "distant.tests.factice_entrainer" in faux.script_du_dernier_appel()


def test_entrainer_quote_les_options(env, faux):
    faux.sortie = ""
    valeur = "a'b c"
    lancer.main(["entrainer", "--tache", "emotion", "--plafond", valeur])
    script = faux.script_du_dernier_appel()
    ligne = next(l for l in script.splitlines() if l.startswith("setsid sh -c "))
    jetons = shlex.split(shlex.split(ligne)[3])
    assert jetons[jetons.index("--plafond") + 1] == valeur


def test_entrainer_refuse_options_reservees(env, faux, capsys):
    assert lancer.main(["entrainer", "--tache", "emotion", "--corpus", "/ailleurs"]) == 1
    assert faux.appels == []
    assert "--corpus" in capsys.readouterr().err


def test_entrainer_refuse_si_un_run_tourne(env, faux, capsys):
    faux.sortie = "/home/u/sae-data/journaux/stance-20261019-1000.log.pid\n"
    assert lancer.main(["entrainer", "--tache", "stance"]) == 1
    assert len(faux.appels) == 1
    assert "tourne déjà" in capsys.readouterr().err


def test_suivre_rejette_un_nom_de_journal_invalide(env, faux):
    assert lancer.main(["suivre", "--journal", "../../etc/passwd"]) == 1
    assert faux.appels == []


def test_rapatrier_rejette_un_nom_de_run_invalide(env, faux):
    assert lancer.main(["rapatrier", "--run", "../x"]) == 1
    assert faux.appels == []


def test_purger_cibles_limitees(env, faux):
    assert lancer.main(["purger", "--oui"]) == 0
    cibles = re.findall(r'rm -rf -- "\$D"/(\w+)', faux.script_du_dernier_appel())
    assert cibles == ["corpus", "runs", "journaux"]


def test_purger_avec_code(env, faux):
    assert lancer.main(["purger", "--oui", "--code"]) == 0
    cibles = re.findall(r'rm -rf -- "\$D"/(\w+)', faux.script_du_dernier_appel())
    assert cibles == ["corpus", "runs", "journaux", "code"]
    for protege in ("venv", "outils", "cache"):
        assert protege not in cibles


def test_purger_refuse_un_run_non_rapatrie(env, faux, capsys):
    faux.sortie = "emotion-20261019-1528/model/model.safetensors\t445000000\n"
    assert lancer.main(["purger", "--oui"]) == 1
    assert "emotion-20261019-1528" in capsys.readouterr().err
    assert not any("rm -rf" in " ".join(a) for a in faux.appels)


def test_purger_accepte_un_run_rapatrie_en_entier(env, faux):
    run = env / "corpus" / "modeles" / "emotion-20261019-1528" / "model"
    run.mkdir(parents=True)
    (run / "model.safetensors").write_bytes(b"x" * 12)
    faux.sortie = "emotion-20261019-1528/model/model.safetensors\t12\n"
    assert lancer.main(["purger", "--oui"]) == 0


def test_purger_refuse_une_copie_tronquee(env, faux):
    run = env / "corpus" / "modeles" / "emotion-20261019-1528" / "model"
    run.mkdir(parents=True)
    (run / "model.safetensors").write_bytes(b"x" * 5)
    faux.sortie = "emotion-20261019-1528/model/model.safetensors\t12\n"
    assert lancer.main(["purger", "--oui"]) == 1
    assert lancer.main(["purger", "--oui", "--forcer"]) == 0


def test_executer_ferme_stdin(env, monkeypatch):
    vus = {}
    def run(argv, **kwargs):
        vus.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
    monkeypatch.setattr(lancer.subprocess, "run", run)
    lancer.executer(["true"])
    assert vus["stdin"] is subprocess.DEVNULL


def test_purger_sans_confirmation_annule(env, faux, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert lancer.main(["purger"]) == 1
    assert not any("rm -rf" in " ".join(x) for x in faux.appels)


def test_version_torch_epinglee():
    assert lancer.version_torch() == "2.14.1"


def test_arguments_inconnus_hors_entrainer(env, faux):
    with pytest.raises(SystemExit):
        lancer.main(["verifier", "--n-importe-quoi"])
