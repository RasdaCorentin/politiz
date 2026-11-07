"""Briques communes : normalisation, entités, schéma, chemins."""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "schema.yaml"
# Source unique des entités : ressources/lexique/entites.yaml, lu comme un fichier de données
# (chemin résolu depuis la racine du dépôt ; pas d'import de code entre dossiers).
ENTITES_PATH = HERE.parents[2] / "ressources" / "lexique" / "entites.yaml"

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
MENTION_RE = re.compile(r"(?<!\w)@[\w.\-]+")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize(text: str) -> str:
    """Minuscules, sans accents, sans URL ni @mention, ponctuation -> espaces."""
    t = URL_RE.sub(" ", text)
    t = MENTION_RE.sub(" ", t)
    t = strip_accents(t.lower())
    t = re.sub(r"[^\w\s]|_", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def corpus_dir(arg: str | None = None) -> Path:
    value = arg or os.environ.get("SAE_CORPUS_DIR")
    if not value:
        raise SystemExit("Dossier du corpus inconnu : définir SAE_CORPUS_DIR ou passer --corpus-dir.")
    return Path(value).expanduser()


def annotation_dir(arg: str | None = None) -> Path:
    d = corpus_dir(arg) / "annotation"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_schema(path: Path = SCHEMA_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_entites(path: Path = ENTITES_PATH) -> list[dict]:
    """Entités de entites.yaml : [{id, type, alias: [{forme, ambigu, ...}]}]."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["entites"]


def alias_map(entites: list[dict]) -> dict[str, tuple[str, bool]]:
    """alias normalisé -> (id de l'entité, ambigu). Personne et parti restent distincts.

    Le lexique est déjà normalisé ; on repasse par normalize() pour que l'alias soit comparé
    au texte tel qu'il sera vu (ponctuation -> espace). 'gouvernement' est ajouté (valeur spéciale).
    """
    m: dict[str, tuple[str, bool]] = {}
    for e in entites:
        for a in e["alias"]:
            forme = normalize(a["forme"])
            if forme and forme not in m:
                m[forme] = (e["id"], bool(a.get("ambigu")))
    m.setdefault("gouvernement", ("gouvernement", False))
    return m


def compile_aliases(amap: dict[str, tuple[str, bool]]) -> re.Pattern:
    alts = sorted(amap, key=len, reverse=True)
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(a) for a in alts) + r")(?!\w)")


def detect_entities(text: str, amap: dict[str, tuple[str, bool]],
                    pattern: re.Pattern | None = None) -> tuple[list[str], list[str]]:
    """(sûres, incertaines) : ids cités, dans l'ordre d'apparition, sans doublon.

    Une entité n'est « sûre » que si au moins un de ses alias cités est non ambigu ; sinon elle
    est « incertaine » (alias à autre sens courant : prénom, nom commun). Les @handles sont retirés
    par normalize() avant la détection. Proposition seulement.
    """
    pattern = pattern or compile_aliases(amap)
    surs: list[str] = []
    douteuses: list[str] = []
    for m in pattern.finditer(normalize(text)):
        ident, ambigu = amap[m.group(1)]
        if ambigu:
            if ident not in douteuses:
                douteuses.append(ident)
        elif ident not in surs:
            surs.append(ident)
    return surs, [e for e in douteuses if e not in surs]


def entity_choices(schema: dict, entites: list[dict]) -> list[str]:
    """Entités du schéma = ids de entites.yaml + valeurs spéciales (gouvernement, groupe-politique, autre)."""
    speciales = list(schema["cibles"]["entites_speciales"])
    return sorted({e["id"] for e in entites} - set(speciales)) + speciales
