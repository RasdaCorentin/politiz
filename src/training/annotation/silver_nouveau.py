"""Silver du nouveau corpus : conversion au format lu par l'export.

    python -m annotation.silver_nouveau [--corpus-dir DOSSIER]

Entrées (hors dépôt, dans <annotation>/silver/nouveau/) :
- final-contexte.jsonl : étiquettes du LLM, `post_id` = `d<id_source>` ;
- echantillon-800.json : liste de paires [id_source, texte], le texte donné au LLM.

Sorties :
- <annotation>/silver/final/nouveau-contexte.jsonl : étiquettes, `post_id` = `nouveau:<id_source>`
  (même identifiant que les lots gold : le garde-fou gold de l'export s'applique) ;
- <annotation>/lots/textes_nouveau.jsonl : `post_id`, `text`, à passer à l'export par `--textes`.

Le LLM a étiqueté ces posts en voyant le post parent ; le modèle ne voit que le post. Le texte
écrit est celui du post seul. Un fichier de sortie existant n'est pas écrasé.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .common import annotation_dir
from .storage import read_jsonl

PREFIXE_LLM = "d"
SOURCE = "nouveau"


def identifiant(post_id_llm: str) -> str:
    """`d123` -> `nouveau:123`. Refuse toute autre forme."""
    if not (post_id_llm.startswith(PREFIXE_LLM) and post_id_llm[1:].isdigit()):
        raise ValueError(f"identifiant silver inattendu : {post_id_llm!r}")
    return f"{SOURCE}:{int(post_id_llm[1:])}"


def convertir(etiquettes: list[dict], echantillon: list[list]) -> tuple[list[dict], list[dict], dict]:
    """Étiquettes et textes au format de l'export. Un post sans texte est écarté."""
    textes = {int(i): t for i, t in echantillon}
    labels, posts, stats = [], [], {"etiquettes": len(etiquettes), "sans_texte": 0}
    for r in etiquettes:
        pid = identifiant(str(r["post_id"]))
        texte = textes.get(int(pid.split(":")[1]))
        if not texte:
            stats["sans_texte"] += 1
            continue
        labels.append({**r, "post_id": pid})
        posts.append({"post_id": pid, "text": texte})
    stats["ecrits"] = len(labels)
    return labels, posts, stats


def ecrire(chemin: Path, lignes: list[dict]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "x", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in lignes)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-dir")
    a = ap.parse_args(argv)
    adir = annotation_dir(a.corpus_dir)
    src = adir / "silver" / "nouveau"
    for f in ("final-contexte.jsonl", "echantillon-800.json"):
        if not (src / f).is_file():
            raise SystemExit(f"{src / f} introuvable.")
    labels, posts, stats = convertir(read_jsonl(src / "final-contexte.jsonl"),
                                     json.loads((src / "echantillon-800.json").read_text(encoding="utf-8")))
    sorties = (adir / "silver" / "final" / "nouveau-contexte.jsonl", adir / "lots" / "textes_nouveau.jsonl")
    deja = [str(p) for p in sorties if p.exists()]
    if deja:
        raise SystemExit(f"existe déjà, rien n'est écrit : {', '.join(deja)}")
    ecrire(sorties[0], labels)
    ecrire(sorties[1], posts)
    print(f"silver nouveau : {stats}")


if __name__ == "__main__":
    main()
