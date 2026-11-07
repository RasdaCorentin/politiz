#!/usr/bin/env python3
"""Publie un dossier de run du modèle dans MinIO (bucket `modeles`), d'où la CD le télécharge.

  SAE_SSH_2='ssh -J saut koda@vm2' python3 scripts/publier_modele.py CHEMIN/stance-20261101-1457 [--machine 2]

Le run part en archive tar par ssh vers une machine du cluster, qui l'écrit dans son nœud MinIO
(`mc pipe`) avec le compte administrateur lu dans son propre infra/distribue/.env : aucun secret ne
transite par ce poste. L'empreinte SHA-256 de l'archive est calculée ici pendant l'envoi, puis
écrite à côté (`<run>.tar.sha256`) ; infra/deploiement/tirer.py la vérifie au téléchargement.
Un dossier de run ne contient aucun texte de post (src/training/modele/AGENTS.md, « Dossier d'un run »).
Branche ensuite le run en modifiant infra/distribue/modeles.env (un commit, une MR).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DEPOT_DISTANT = "/opt/sae-data"


class Envoi:
    """Flux d'écriture vers ssh qui calcule l'empreinte SHA-256 de ce qui passe."""

    def __init__(self, flux):
        self.flux, self.h, self.octets = flux, hashlib.sha256(), 0

    def write(self, bloc: bytes) -> int:
        self.h.update(bloc)
        self.octets += len(bloc)
        return self.flux.write(bloc)


def commande_distante(objet: str, image: str, sudo: str, creer_bucket: bool) -> str:
    """Script shell lancé sur la machine : lit le compte racine de MinIO dans son .env, puis `mc pipe`."""
    env = f"{DEPOT_DISTANT}/infra/distribue/.env"
    # Seul `mc pipe` lit l'entrée standard (-i) : toute autre commande la viderait avant lui.
    mc = f"{sudo + ' ' if sudo else ''}docker run --rm --network host --env-file \"$f\" {image}"
    mc_pipe = mc.replace("docker run ", "docker run -i ", 1)
    etapes = [
        "set -eu",
        "f=$(mktemp)",
        "trap 'rm -f \"$f\"' EXIT",
        "chmod 600 \"$f\"",
        f"u=$(sed -n 's/^MINIO_ROOT_USER=//p' {env})",
        f"p=$(sed -n 's/^MINIO_ROOT_PASSWORD=//p' {env})",
        "printf 'MC_HOST_sae=http://%s:%s@127.0.0.1:29000\\n' \"$u\" \"$p\" > \"$f\"",
    ]
    if creer_bucket:
        etapes.append(f"{mc} mb --ignore-existing sae/{objet.split('/')[0]} </dev/null >/dev/null")
    etapes.append(f"{mc_pipe} pipe sae/{objet}")
    return "; ".join(etapes)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("run", type=Path, help="dossier du run (ex. …/modeles/stance-20261101-1457)")
    p.add_argument("--machine", default="2", help="machine du cluster qui reçoit l'envoi : 1, 2 ou c")
    a = p.parse_args(argv)

    run = a.run.resolve()
    if not (run / "model").is_dir() or not (run / "modele.json").is_file():
        print(f"{run} n'est pas un dossier de run (model/ et modele.json attendus)", file=sys.stderr)
        return 2
    m = a.machine.upper()
    ssh = os.environ.get(f"SAE_SSH_{m}")
    if not ssh:
        print(f"SAE_SSH_{m} non définie (commande ssh de la machine {a.machine})", file=sys.stderr)
        return 2
    sudo = os.environ.get(f"SAE_SUDO_{m}", "")
    reglages = tomllib.loads((RACINE / "infra/deploiement/machines.toml").read_text())["modeles"]
    objet = f"{reglages['bucket']}/{run.name}.tar"

    print(f"envoi de {run.name} vers MinIO (machine {a.machine})", flush=True)
    distant = commande_distante(objet, reglages["image_mc"], sudo, creer_bucket=True)
    proc = subprocess.Popen([*shlex.split(ssh), distant], stdin=subprocess.PIPE)
    envoi = Envoi(proc.stdin)
    with tarfile.open(fileobj=envoi, mode="w|") as t:
        t.add(run, arcname=run.name)
    proc.stdin.close()
    if proc.wait() != 0:
        print("échec de l'envoi de l'archive", file=sys.stderr)
        return 1
    empreinte = envoi.h.hexdigest()
    distant = commande_distante(objet + ".sha256", reglages["image_mc"], sudo, creer_bucket=False)
    r = subprocess.run([*shlex.split(ssh), distant], input=f"{empreinte}  {run.name}.tar\n".encode())
    if r.returncode != 0:
        print("échec de l'envoi de l'empreinte", file=sys.stderr)
        return 1
    print(f"publié : {objet} ({envoi.octets / 1e6:.0f} Mo, sha256 {empreinte[:12]}…)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
