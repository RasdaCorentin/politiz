"""Outils de test : corpus factice et petit modèle aléatoire. Tout est inventé.

Aucun texte de post réel ici. Les textes sont des assemblages de mots-marqueurs, assez réguliers
pour qu'un modèle minuscule les apprenne en quelques pas. Les ids d'entité viennent du lexique,
les noms de personnes n'apparaissent que comme noms de cible.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

STANCES = ["pour", "contre", "neutre", "mention", "ambigu"]
MARQUEURS = {
    "pour": "bravo soutien", "contre": "honte demission", "neutre": "mais equilibre",
    "mention": "meeting sondage", "ambigu": "bof mystere",
}
EMOTIONS = {"joie": "youpi", "colere": "rage", "peur": "inquiet", "tristesse": "triste",
            "surprise": "tiens", "degout": "beurk", "neutre": "factuel"}
ENTITES = ["melenchon", "glucksmann", "lfi", "le pen", "gouvernement", "autre", "groupe-politique"]
NOMS = {"melenchon": "Melenchon", "glucksmann": "Glucksmann", "lfi": "LFI", "le pen": "Le Pen",
        "gouvernement": "Gouvernement", "autre": "Autre", "groupe-politique": "Groupe politique"}
# Mot qui ne doit jamais apparaître dans un journal ou une sortie : sentinelle de non-fuite.
SENTINELLE = "zorglub"


def lignes_factices(n: int = 96, prefixe: str = "p", source: str = "silver") -> list[dict]:
    """n posts inventés au format de train_silver.jsonl. Chaque 20e est `non`, chaque 25e `doute`."""
    lignes = []
    emotions = list(EMOTIONS)
    for i in range(n):
        pid = f"{prefixe}{i:03d}"
        base = {"post_id": pid, "created_at": "2026-10-12T10:00:00+00:00", "source": source,
                "themes": [], "ironie": "non", "regle_suffit": "non", "indice": ""}
        if i % 20 == 19:
            lignes.append({**base, "text": f"hors sujet {SENTINELLE} {i}", "pertinent": "non", "cibles": [],
                           "emotion": None})
            continue
        n_cibles = 2 if i % 3 == 0 else 1
        cibles, morceaux = [], []
        for j in range(n_cibles):
            entite = ENTITES[(i + 2 * j) % len(ENTITES)]
            if any(c["entite"] == entite for c in cibles):
                continue
            stance = STANCES[(i + j) % len(STANCES)]
            cibles.append({"entite": entite, "stance": stance})
            morceaux.append(f"{MARQUEURS[stance].split()[i % 2]} {NOMS[entite]}")
        emotion = emotions[i % len(emotions)]
        texte = f"{' puis '.join(morceaux)} {EMOTIONS[emotion]} {SENTINELLE} lundi {i}"
        pertinent = "doute" if i % 25 == 24 else "oui"
        lignes.append({**base, "text": texte, "pertinent": pertinent, "cibles": cibles, "emotion": emotion})
    return lignes


def ecrire_jsonl(chemin: Path, lignes: list[dict]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in lignes), encoding="utf-8")


def creer_corpus(racine: Path, n_train: int = 96, n_pilote: int = 8, n_eval: int = 10) -> Path:
    """Dossier de corpus factice : train_silver.jsonl, lots pilote et évaluation, eval_fige.json."""
    adir = racine / "annotation"
    ecrire_jsonl(adir / "train_silver.jsonl", lignes_factices(n_train, "p"))
    pilote = [{"post_id": f"pil{i}", "text": f"pilote {i}", "created_at": "2026-10-12T09:00:00+00:00"}
              for i in range(n_pilote)]
    evaluation = [{"post_id": f"ev{i}", "text": f"evaluation {i}", "created_at": "2026-10-12T09:00:00+00:00"}
                  for i in range(n_eval)]
    ecrire_jsonl(adir / "lots" / "lot_00_pilote.jsonl", pilote)
    ecrire_jsonl(adir / "lots" / "lot_eval.jsonl", evaluation)
    ids = sorted(r["post_id"] for r in evaluation)
    sha = hashlib.sha256("\n".join(ids).encode()).hexdigest()
    (adir / "eval_fige.json").write_text(json.dumps({"lot": "lot_eval", "n": len(ids), "sha256": sha, "ids": ids}),
                                         encoding="utf-8")
    return racine


def creer_modele_minuscule(dossier: Path) -> Path:
    """Petit CamemBERT aléatoire (2 couches, 32 dimensions) et son tokenizer, construits sans réseau."""
    from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors, trainers
    from transformers import CamembertConfig, CamembertForSequenceClassification, PreTrainedTokenizerFast

    textes = [l["text"] for l in lignes_factices(96)] + list(NOMS.values()) + list(EMOTIONS.values())
    tk = Tokenizer(models.WordPiece(unk_token="<unk>"))
    tk.normalizer = normalizers.Lowercase()
    tk.pre_tokenizer = pre_tokenizers.Whitespace()
    tk.train_from_iterator(textes, trainers.WordPieceTrainer(
        vocab_size=400, special_tokens=["<s>", "<pad>", "</s>", "<unk>", "<mask>"]))
    tk.post_processor = processors.TemplateProcessing(
        single="<s> $A </s>", pair="<s> $A </s> </s> $B </s>",
        special_tokens=[("<s>", tk.token_to_id("<s>")), ("</s>", tk.token_to_id("</s>"))])
    rapide = PreTrainedTokenizerFast(
        tokenizer_object=tk, bos_token="<s>", eos_token="</s>", unk_token="<unk>", sep_token="</s>",
        cls_token="<s>", pad_token="<pad>", mask_token="<mask>")
    config = CamembertConfig(
        vocab_size=len(rapide), hidden_size=32, num_hidden_layers=2, num_attention_heads=2,
        intermediate_size=64, max_position_embeddings=130, type_vocab_size=1,
        pad_token_id=1, bos_token_id=0, eos_token_id=2)
    CamembertForSequenceClassification(config).save_pretrained(dossier)
    rapide.save_pretrained(dossier)
    return dossier
