"""Option --emotion-3-classes de comparer_gold_silver.py, lancé comme en production (python3 -I).

Corpus inventé dans un dossier temporaire ; aucun texte réel. Le script n'imprime aucun texte : le
test vérifie aussi que les textes inventés n'apparaissent pas dans la sortie.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "comparer_gold_silver.py"
TEXTE = "youpi inventé sentinelle-zeta"


def _ecrire(chemin: Path, lignes: list[dict]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lignes), encoding="utf-8")


def _corpus(racine: Path) -> tuple[Path, Path]:
    ann = racine / "annotation"
    # gold : p1 joie, p2 degout, p3 surprise (exclu), p4 colere, p5 neutre (silver vide, exclu)
    gold = {"p1": "joie", "p2": "degout", "p3": "surprise", "p4": "colere", "p5": "neutre"}
    _ecrire(ann / "annotations" / "annotateur_a.jsonl",
            [{"post_id": p, "annotateur": "a", "pertinent": "oui", "emotion": e, "cibles": []}
             for p, e in gold.items()])
    silver = {"p1": "joie", "p2": "peur", "p3": "joie", "p4": "neutre", "p5": None}
    _ecrire(ann / "silver" / "final" / "silver_v1.jsonl",
            [{"post_id": p, "pertinent": "oui", "emotion": e, "cibles": []} for p, e in silver.items()])
    _ecrire(ann / "train_silver.jsonl", [{"post_id": "t1", "text": TEXTE, "source": "silver",
                                          "pertinent": "oui", "emotion": "joie"}])
    _ecrire(ann / "lots" / "lot_eval.jsonl", [{"post_id": p, "text": TEXTE} for p in silver])
    (ann / "eval_fige.json").write_text(json.dumps({"n": 5, "ids": sorted(silver)}), encoding="utf-8")
    lexique = racine / "emotions.yaml"
    lexique.write_text("- emotion: joie\n  marqueurs: [{motif: \"youpi\", confiance: haute}]\n"
                       "- emotion: colere\n  marqueurs: [{motif: \"rage\", confiance: haute}]\n", encoding="utf-8")
    return racine, lexique


def _lancer(corpus: Path, lexique: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(SCRIPT), "--corpus", str(corpus),
                           "--lexique", str(lexique), *extra],
                          capture_output=True, text=True, timeout=120, cwd=corpus)


def test_trois_classes_projette_avant_l_accord_et_compte_les_exclus(tmp_path):
    corpus, lexique = _corpus(tmp_path / "corpus")
    res = _lancer(corpus, lexique, "--emotion-3-classes")
    assert res.returncode == 0, res.stderr
    sortie = res.stdout
    assert "posts gold avec émotion : 5 ; retenus : 3 ; exclus : 2 (dont surprise côté gold : 1)" in sortie
    assert "accord exact (3 classes) : 2/3" in sortie            # degout->colere = peur->colere ; colere != neutre
    assert "effectifs gold (3 classes) : colere=2 joie=1" in sortie
    assert "paires gold -> silver (3 classes) : colere->colere=1, colere->neutre=1, joie->joie=1" in sortie
    assert TEXTE not in sortie and TEXTE not in res.stderr


def test_sans_option_l_accord_reste_sur_les_sept_classes(tmp_path):
    corpus, lexique = _corpus(tmp_path / "corpus")
    res = _lancer(corpus, lexique)
    assert res.returncode == 0, res.stderr
    assert "accord exact : " in res.stdout
    assert "3 classes" not in res.stdout
