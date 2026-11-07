"""Pilotage de la machine GPU distante : vérification, envoi, entraînement, rapatriement, purge.

Bibliothèque standard seulement. Depuis `src/training/` :

    python3 -m distant.lancer verifier
    python3 -m distant.lancer installer
    python3 -m distant.lancer envoyer-code
    python3 -m distant.lancer envoyer-corpus [--oui]
    python3 -m distant.lancer entrainer --tache stance|emotion [--module M] [options de modele.entrainer]
    python3 -m distant.lancer suivre [--journal NOM] [--lignes N]
    python3 -m distant.lancer rapatrier (--run NOM | --dernier) [--destination DOSSIER]
    python3 -m distant.lancer purger [--oui] [--code]

Variables d'environnement :
- `SAE_GPU_HOTE` : `utilisateur@hôte` de la machine GPU (obligatoire, jamais dans le dépôt) ;
- `SAE_GPU_SSH_OPTIONS` : options ssh, par exemple une `UserKnownHostsFile` dédiée ;
- `SAE_GPU_DOSSIER` : dossier de travail distant (défaut `~/sae-data`) ;
- `SAE_CORPUS_DIR` : corpus local (`envoyer-corpus`, et `rapatrier` par défaut).

Ce module ne lit aucun texte de post : il n'affiche que des tailles, des états et des journaux
d'entraînement (qui ne contiennent pas de texte, contrat du modèle dans contrats-poc.md).
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TRAINING_DIR = Path(__file__).resolve().parents[1]
DEPOT = Path(__file__).resolve().parents[3]
LEXIQUE_LOCAL = DEPOT / "ressources" / "lexique"
REQUIREMENTS = TRAINING_DIR / "requirements-train.txt"

TACHES = ("stance", "emotion")
MODULE_PAR_DEFAUT = "modele.entrainer"
PYTHON_VERSION = "3.12"
INDEX_CUDA = "https://download.pytorch.org/whl/cu130"
NVIDIA_SMI = "/usr/lib/wsl/lib/nvidia-smi"
EXCLUS_CODE = ("__pycache__", ".pytest_cache", "*.pyc", "modeles", "runs")
# Seuls ces fichiers quittent le poste (M11) : pas de lot pilote, pas de lot d'évaluation brut.
FICHIERS_CORPUS = ("annotation/train_silver.jsonl", "annotation/eval_fige.json")
OPTIONS_RESERVEES = ("--tache", "--corpus", "--sortie")
RE_RUN = re.compile(r"^(stance|emotion)-\d{8}-\d{4}$")
RE_JOURNAL = re.compile(r"^(stance|emotion)-\d{8}-\d{4}\.log$")
TORCH_CONTROLE = (
    "import sys, torch; ok = torch.cuda.is_available(); "
    "print('torch', torch.__version__, 'cuda', ok, torch.cuda.get_device_name(0) if ok else '-'); "
    "sys.exit(0 if ok else 1)"
)


class ErreurDistant(Exception):
    """Erreur destinée à l'utilisateur : affichée sans trace."""


@dataclass(frozen=True)
class Config:
    hote: str
    options_ssh: tuple[str, ...]
    dossier: str
    corpus: Path | None


def charger_config(env=os.environ) -> Config:
    hote = env.get("SAE_GPU_HOTE", "").strip()
    if not hote:
        raise ErreurDistant("SAE_GPU_HOTE est vide : définir utilisateur@hôte de la machine GPU.")
    options = tuple(shlex.split(env.get("SAE_GPU_SSH_OPTIONS", "")))
    dossier = env.get("SAE_GPU_DOSSIER", "").strip() or "~/sae-data"
    corpus = env.get("SAE_CORPUS_DIR", "").strip()
    return Config(hote, options, dossier, Path(corpus).expanduser() if corpus else None)


def corpus_local(config: Config) -> Path:
    if config.corpus is None:
        raise ErreurDistant("SAE_CORPUS_DIR n'est pas défini.")
    return config.corpus


# --------------------------------------------------------------------------- chemins
def racine_shell(config: Config) -> str:
    """Dossier distant, écrit pour le shell distant : `~` est développé par ce shell."""
    d = config.dossier
    if d == "~":
        return '"$HOME"'
    if d.startswith("~/"):
        return '"$HOME"/' + shlex.quote(d[2:])
    return shlex.quote(d)


def chemin_shell(*rel: str) -> str:
    """Chemin distant sous `$D` (variable définie en tête de chaque script distant)."""
    return '"$D"' + "".join("/" + shlex.quote(r) for r in rel)


def chemin_rsync(config: Config, *rel: str) -> str:
    """Chemin relatif au dossier de travail, pour rsync (relatif au répertoire personnel distant)."""
    d = config.dossier
    base = "" if d == "~" else d[2:] if d.startswith("~/") else d
    return "/".join(p for p in (base.rstrip("/"), *rel) if p)


# --------------------------------------------------------------------------- exécution
def script(config: Config, corps: str) -> str:
    return f"D={racine_shell(config)}\nexport D\n{corps}"


def ssh_argv(config: Config, texte: str) -> list[str]:
    # Le shell de connexion distant peut être autre que sh : on lui passe `sh -c` quoté.
    return ["ssh", *config.options_ssh, config.hote, "sh -c " + shlex.quote(texte)]


def executer(argv: list[str], *, capturer: bool = False) -> subprocess.CompletedProcess:
    try:
        # stdin fermé : ssh et rsync n'héritent jamais du terminal (une commande passée en
        # arrière-plan coupait sinon le transfert : « Broken pipe »).
        return subprocess.run(argv, text=True, capture_output=capturer, check=False,
                              stdin=subprocess.DEVNULL)
    except FileNotFoundError as e:
        raise ErreurDistant(f"commande absente sur ce poste : {argv[0]}") from e


def distant(config: Config, corps: str, *, capturer: bool = False, verifie: bool = True):
    cp = executer(ssh_argv(config, script(config, corps)), capturer=capturer)
    if verifie and cp.returncode != 0:
        raise ErreurDistant(f"commande distante en échec (code {cp.returncode})")
    return cp


def rsync(config: Config, sources: list[str], destination: str, *, delete: bool = False,
          excludes: tuple[str, ...] = (), chmod: str | None = None) -> None:
    # --partial : un transfert coupé reprend où il s'est arrêté (poids de ~440 Mo).
    argv = ["rsync", "-a", "-s", "--partial", "-e", shlex.join(["ssh", *config.options_ssh])]
    if delete:
        argv.append("--delete")
    for motif in excludes:
        argv += ["--exclude", motif]
    if chmod:
        argv.append(f"--chmod={chmod}")
    argv += [*sources, destination]
    cp = executer(argv)
    if cp.returncode != 0:
        raise ErreurDistant(f"rsync en échec (code {cp.returncode})")


def cible_rsync(config: Config, *rel: str) -> str:
    """Destination distante pour rsync : `hote:chemin/`."""
    return f"{config.hote}:{chemin_rsync(config, *rel)}/"


def version_torch() -> str:
    """Version de torch épinglée dans requirements-train.txt (source unique)."""
    m = re.search(r"^torch==([0-9][^\s#]*)", REQUIREMENTS.read_text(encoding="utf-8"), re.M)
    if not m:
        raise ErreurDistant(f"torch n'est pas épinglé dans {REQUIREMENTS.name}")
    return m.group(1)


# --------------------------------------------------------------------------- commandes
def cmd_verifier(config: Config) -> int:
    corps = "\n".join([
        "FAIL=0",
        f"SMI={NVIDIA_SMI}; [ -x \"$SMI\" ] || SMI=nvidia-smi",
        'echo "== carte"',
        '"$SMI" --query-gpu=name,memory.total,memory.used,driver_version --format=csv,noheader'
        ' || { echo "nvidia-smi : échec"; FAIL=1; }',
        'echo "== torch"',
        'if [ -x "$D/venv/bin/python" ]; then',
        f'  "$D/venv/bin/python" -c {shlex.quote(TORCH_CONTROLE)} || {{ echo "CUDA indisponible"; FAIL=1; }}',
        "else",
        '  echo "venv absent : lancer installer"; FAIL=1',
        "fi",
        'echo "== disque"',
        'df -Ph "$HOME" | tail -n 1',
        "exit $FAIL",
    ])
    distant(config, corps)
    print("verification : ok")
    return 0


def cmd_installer(config: Config) -> int:
    torch = version_torch()
    distant(config, 'mkdir -p "$D/outils" "$D/cache/uv" "$D/cache/hf" "$D/installation"')
    rsync(config, [str(REQUIREMENTS)], cible_rsync(config, "installation"))
    corps = "\n".join([
        "set -e",
        'UV="$D/outils/uv"',
        '[ -x "$UV" ] || { echo "uv absent de $UV" >&2; exit 1; }',
        'export UV_CACHE_DIR="$D/cache/uv" UV_PYTHON_INSTALL_DIR="$D/outils/python" HF_HOME="$D/cache/hf"'
        ' UV_PYTHON_BIN_DIR="$D/outils/bin"',
        f'"$UV" python install {PYTHON_VERSION}',
        f'[ -x "$D/venv/bin/python" ] || "$UV" venv --python {PYTHON_VERSION} "$D/venv"',
        f'"$UV" pip install --python "$D/venv/bin/python" --index-url {INDEX_CUDA} torch=={torch}',
        '"$UV" pip install --python "$D/venv/bin/python" -r "$D/installation/requirements-train.txt"',
        f'"$D/venv/bin/python" -c {shlex.quote(TORCH_CONTROLE)} || true',
    ])
    distant(config, corps)
    print("installation : ok")
    return 0


def cmd_envoyer_code(config: Config) -> int:
    distant(config, "mkdir -p " + chemin_shell("code", "src", "training") + " "
            + chemin_shell("code", "ressources", "lexique"))
    rsync(config, [f"{TRAINING_DIR}/"], cible_rsync(config, "code/src/training"),
          delete=True, excludes=EXCLUS_CODE)
    rsync(config, [f"{LEXIQUE_LOCAL}/"], cible_rsync(config, "code/ressources/lexique"), delete=True)
    print("code envoyé : src/training et ressources/lexique")
    return 0


def cmd_envoyer_corpus(config: Config, oui: bool) -> int:
    racine = corpus_local(config)
    fichiers = []
    for rel in FICHIERS_CORPUS:
        chemin = racine / rel
        if not chemin.is_file():
            raise ErreurDistant(f"fichier absent du corpus : {rel}")
        fichiers.append(chemin)
    print("Fichiers à envoyer (tailles seulement) :")
    for rel, chemin in zip(FICHIERS_CORPUS, fichiers):
        print(f"  {rel} : {chemin.stat().st_size} octets")
    if not oui:
        reponse = input("Envoyer ces fichiers vers la machine GPU ? [o/N] ").strip().lower()
        if reponse not in ("o", "oui"):
            print("Annulé.")
            return 1
    distant(config, "\n".join([
        "umask 077",
        'mkdir -p "$D/corpus/annotation"',
        'chmod 700 "$D/corpus" "$D/corpus/annotation"',
    ]))
    rsync(config, [str(f) for f in fichiers], cible_rsync(config, "corpus/annotation"),
          chmod="F600,D700")
    distant_tailles = distant(config, "\n".join(
        f'wc -c < {chemin_shell("corpus", *rel.split("/"))}' for rel in FICHIERS_CORPUS
    ), capturer=True).stdout.split()
    locales = [str(f.stat().st_size) for f in fichiers]
    if distant_tailles != locales:
        raise ErreurDistant("contrôle des tailles après envoi : différence")
    print("corpus envoyé : contrôle des tailles ok")
    return 0


def cmd_entrainer(config: Config, tache: str, module: str, options: list[str]) -> int:
    for opt in options:
        if any(opt == r or opt.startswith(r + "=") for r in OPTIONS_RESERVEES):
            raise ErreurDistant(f"{opt} est géré par distant/ : ne pas le passer")
    garde = distant(config, "\n".join([
        'for p in "$D"/journaux/*.pid; do [ -f "$p" ] || continue; '
        'kill -0 "$(cat "$p")" 2>/dev/null && echo "$p"; done; exit 0',
    ]), capturer=True).stdout.strip()
    if garde:
        raise ErreurDistant("un entraînement tourne déjà (pid) :\n" + garde)
    interne = (
        'env PYTHONUNBUFFERED=1 HF_HOME="$D/cache/hf" "$D/venv/bin/python" -m '
        f"{shlex.quote(module)} --tache {tache} --corpus \"$D/corpus\" --sortie \"$D/runs\" "
        + " ".join(shlex.quote(o) for o in options)
        + ' ; echo $? > "$J.code"'
    )
    distant(config, "\n".join([
        "set -e",
        'mkdir -p "$D/journaux" "$D/runs"',
        # Horodatage de la machine GPU : le run et son journal portent la même heure.
        f'J="$D"/journaux/{tache}-$(date +%Y%m%d-%H%M).log',
        "export J",
        'cd "$D/code/src/training"',
        f"setsid sh -c {shlex.quote(interne)} > \"$J\" 2>&1 < /dev/null &",
        'echo $! > "$J.pid"',
        "sleep 3",
        'echo "lancé : $J"',
        'tail -n 3 "$J"',
    ]))
    return 0


def cmd_suivre(config: Config, journal: str | None, lignes: int) -> int:
    if journal is None:
        journal = Path(distant(config, 'ls -1t "$D"/journaux/*.log 2>/dev/null | head -n 1',
                               capturer=True).stdout.strip()).name
        if not journal:
            raise ErreurDistant("aucun journal sur la machine GPU")
    if not RE_JOURNAL.match(journal):
        raise ErreurDistant(f"nom de journal invalide : {journal}")
    cp = distant(config, "\n".join([
        f'J="$D"/journaux/{journal}',
        'SMI=' + NVIDIA_SMI + '; [ -x "$SMI" ] || SMI=nvidia-smi',
        'if [ ! -f "$J" ]; then echo "journal absent : ' + journal + '"; exit 2; fi',
        "ETAT=termine",
        'if [ -f "$J.pid" ] && kill -0 "$(cat "$J.pid")" 2>/dev/null; then ETAT=en_cours; fi',
        'echo "etat : $ETAT"',
        'echo "gpu :"',
        '"$SMI" --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu'
        ' --format=csv,noheader 2>/dev/null || echo "  nvidia-smi indisponible"',
        'echo "fin du journal :"',
        f'tail -n {int(lignes)} "$J"',
        'if [ "$ETAT" = termine ]; then',
        '  CODE=$(cat "$J.code" 2>/dev/null || echo inconnu)',
        '  DERNIER=$(tail -n 1 "$J")',
        '  if [ "$CODE" = 0 ] && [ -d "$DERNIER" ]; then echo "resultat : ok, run $DERNIER"; '
        'else echo "resultat : echec (code $CODE)"; exit 1; fi',
        "fi",
    ]), verifie=False)
    return cp.returncode


def cmd_rapatrier(config: Config, run: str | None, dernier: bool, destination: str | None) -> int:
    if dernier:
        run = distant(config, 'ls -1t "$D"/runs 2>/dev/null | head -n 1', capturer=True).stdout.strip()
        if not run:
            raise ErreurDistant("aucun run sur la machine GPU")
    if not RE_RUN.match(run or ""):
        raise ErreurDistant(f"nom de run invalide : {run}")
    fichiers = ("modele.json", "metriques.json", "config_entrainement.json", "model")
    distant(config, f'for f in {" ".join(fichiers)}; do test -e "$D/runs/{run}/$f" || '
            '{ echo "absent : $f"; exit 1; }; done')
    base = Path(destination).expanduser() if destination else corpus_local(config) / "modeles"
    cible = base / run
    if cible.exists():
        raise ErreurDistant(f"le run existe déjà en local : {cible}")
    cible.mkdir(parents=True)
    rsync(config, [cible_rsync(config, "runs", run)], f"{cible}/")
    print(f"rapatrié : {cible}")
    print("Vérifier le run, puis purger la machine GPU : python3 -m distant.lancer purger --oui")
    return 0


def runs_non_rapatries(config: Config, base: Path) -> list[str]:
    """Runs distants dont la copie locale manque ou diffère (fichier absent ou taille différente)."""
    sortie = distant(config, 'cd "$D/runs" 2>/dev/null && find . -type f -printf "%P\\t%s\\n" || true',
                     capturer=True).stdout
    manquants: set[str] = set()
    for ligne in sortie.splitlines():
        if "\t" not in ligne:
            continue
        rel, taille = ligne.rsplit("\t", 1)
        local = base / rel
        if not local.is_file() or str(local.stat().st_size) != taille.strip():
            manquants.add(rel.split("/", 1)[0])
    return sorted(manquants)


def cmd_purger(config: Config, oui: bool, code: bool, forcer: bool = False,
               destination: str | None = None) -> int:
    base = Path(destination).expanduser() if destination else corpus_local(config) / "modeles"
    manquants = runs_non_rapatries(config, base)
    if manquants and not forcer:
        raise ErreurDistant("run(s) pas encore rapatrié(s) en entier dans " f"{base} : "
                            + ", ".join(manquants) + " (rapatrier d'abord, ou --forcer)")
    cibles = ["corpus", "runs", "journaux"] + (["code"] if code else [])
    print("A effacer sur la machine GPU : " + ", ".join(c + "/" for c in cibles)
          + " (venv, outils, cache conservés)")
    if not oui:
        reponse = input("Confirmer la purge ? [o/N] ").strip().lower()
        if reponse not in ("o", "oui"):
            print("Annulé.")
            return 1
    corps = "\n".join(
        ["FAIL=0"]
        + [f'rm -rf -- {chemin_shell(c)}' for c in cibles]
        + [f'if [ -e {chemin_shell(c)} ]; then echo "present : {c}"; FAIL=1; else echo "absent : {c}"; fi'
           for c in cibles]
        + ['echo "restant :"', 'ls -A "$D"', "exit $FAIL"]
    )
    distant(config, corps)
    print("purge : ok")
    return 0


# --------------------------------------------------------------------------- CLI
def construire_parseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python3 -m distant.lancer", description=__doc__.split("\n")[0])
    sp = p.add_subparsers(dest="commande", required=True)
    sp.add_parser("verifier", help="SSH, carte, torch CUDA, disque")
    sp.add_parser("installer", help="uv, Python 3.12, venv, torch cu130, dépendances (idempotent)")
    sp.add_parser("envoyer-code", help="rsync de src/training et ressources/lexique")
    ec = sp.add_parser("envoyer-corpus", help="silver et eval_fige seulement")
    ec.add_argument("--oui", action="store_true", help="sans confirmation")
    en = sp.add_parser("entrainer", help="lance modele.entrainer en détaché ; options en plus",
                       allow_abbrev=False)
    en.add_argument("--tache", required=True, choices=TACHES)
    en.add_argument("--module", default=MODULE_PAR_DEFAUT, help="module Python lancé (essais)")
    su = sp.add_parser("suivre", help="fin du journal, GPU, fin de run")
    su.add_argument("--journal", help="nom du journal (défaut : le plus récent)")
    su.add_argument("--lignes", type=int, default=20)
    ra = sp.add_parser("rapatrier", help="copie un run en local")
    gr = ra.add_mutually_exclusive_group(required=True)
    gr.add_argument("--run", help="nom du run")
    gr.add_argument("--dernier", action="store_true")
    ra.add_argument("--destination", help="défaut : $SAE_CORPUS_DIR/modeles/")
    pu = sp.add_parser("purger", help="efface corpus, runs, journaux")
    pu.add_argument("--oui", action="store_true", help="sans confirmation")
    pu.add_argument("--code", action="store_true", help="efface aussi code/")
    pu.add_argument("--forcer", action="store_true", help="purge même si un run n'est pas rapatrié")
    pu.add_argument("--destination", help="où chercher les runs rapatriés (défaut : $SAE_CORPUS_DIR/modeles/)")
    return p


def main(argv: list[str] | None = None) -> int:
    parseur = construire_parseur()
    args, reste = parseur.parse_known_args(argv)
    if reste and args.commande != "entrainer":
        parseur.error("arguments inconnus : " + " ".join(reste))
    try:
        config = charger_config()
        if args.commande == "verifier":
            return cmd_verifier(config)
        if args.commande == "installer":
            return cmd_installer(config)
        if args.commande == "envoyer-code":
            return cmd_envoyer_code(config)
        if args.commande == "envoyer-corpus":
            return cmd_envoyer_corpus(config, args.oui)
        if args.commande == "entrainer":
            return cmd_entrainer(config, args.tache, args.module, reste)
        if args.commande == "suivre":
            return cmd_suivre(config, args.journal, args.lignes)
        if args.commande == "rapatrier":
            return cmd_rapatrier(config, args.run, args.dernier, args.destination)
        if args.commande == "purger":
            return cmd_purger(config, args.oui, args.code, args.forcer, args.destination)
    except ErreurDistant as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
