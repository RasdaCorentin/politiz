"""Lecture/écriture des lots et des annotations (un fichier JSONL par annotateur)."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

CHAMPS_VIDES_SI_NON = {"cibles": [], "themes": [], "emotion": None, "ironie": None,
                       "regle_suffit": None, "indice": ""}


def slug(nom: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", nom.strip().lower()).strip("-")
    if not s:
        raise ValueError("nom d'annotateur vide")
    return s


def read_jsonl(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if ligne:
                try:
                    out.append(json.loads(ligne))
                except json.JSONDecodeError:
                    pass  # ligne tronquée par un arrêt brutal : ignorée
    return out


def annotations_path(adir: Path, annotateur: str) -> Path:
    d = Path(adir) / "annotations"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{slug(annotateur)}.jsonl"


def load_annotations(path: Path) -> dict[str, dict]:
    """post_id -> dernière annotation enregistrée (le fichier est en ajout seul)."""
    return {r["post_id"]: r for r in read_jsonl(path)}


def validate(rec: dict, schema: dict, entites: list[str]) -> list[str]:
    """Liste d'erreurs (vide = valide)."""
    err = []
    pert = rec.get("pertinent")
    if pert not in schema["pertinent"]["valeurs"]:
        return ["pertinent manquant"]
    if pert == "non":
        for k, vide in CHAMPS_VIDES_SI_NON.items():
            if rec.get(k) not in (vide, None, "", []):
                err.append(f"{k} doit être vide quand pertinent=non")
        return err
    # pertinent=doute : les autres champs sont facultatifs (mais valides s'ils sont remplis).
    for k in ("emotion", "ironie", "regle_suffit"):
        v = rec.get(k)
        if v in (None, ""):                     # "" = non rempli (sortie JSON, champ vidé)
            if pert == "oui":
                err.append(f"{k} manquant")
        elif v not in schema[k]["valeurs"]:
            err.append(f"{k} invalide : {v}")
    for t in rec.get("themes") or []:
        if t not in schema["themes"]["valeurs"]:
            err.append(f"thème invalide : {t}")
    vus = set()
    for c in rec.get("cibles") or []:
        if c.get("entite") not in entites:
            err.append(f"entité inconnue : {c.get('entite')}")
        st = c.get("stance")
        if st is None and pert == "doute":
            pass
        elif st not in schema["cibles"]["stance"]:
            err.append(f"stance manquante ou invalide pour {c.get('entite')}")
        if c.get("entite") in vus:
            err.append(f"entité en double : {c.get('entite')}")
        vus.add(c.get("entite"))
    return err


def clean(rec: dict) -> dict:
    """Vide les champs dépendants quand pertinent=non."""
    rec = dict(rec)
    if rec.get("pertinent") == "non":
        rec.update({k: (list(v) if isinstance(v, list) else v) for k, v in CHAMPS_VIDES_SI_NON.items()})
    return rec


def save_annotation(path: Path, rec: dict, schema: dict, entites: list[str]) -> None:
    """Valide puis ajoute une ligne et force l'écriture disque (sauvegarde à chaque post)."""
    rec = clean(rec)
    err = validate(rec, schema, entites)
    if err:
        raise ValueError("; ".join(err))
    rec["horodatage"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def list_lots(adir: Path) -> list[Path]:
    return sorted(p for p in (Path(adir) / "lots").glob("lot_*.jsonl"))


def first_unannotated(posts: list[dict], annots: dict[str, dict]) -> int:
    """Indice du premier post sans annotation (len(posts) si le lot est fini)."""
    for i, p in enumerate(posts):
        if p["post_id"] not in annots:
            return i
    return len(posts)
