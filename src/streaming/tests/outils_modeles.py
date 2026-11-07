"""Outils de test : run factice (forme fixée par le contrat du modèle) avec un petit CamemBERT aléatoire. Tout est inventé, sans réseau.

Reprend la méthode de `src/training/modele/tests/outils.py` sans l'importer. Les textes sont des
assemblages de mots inventés.
"""
from __future__ import annotations

import json
from pathlib import Path

ETIQUETTES = {
    "stance": ["pour", "contre", "neutre", "mention", "ambigu"],
    "emotion": ["joie", "colere", "peur", "tristesse", "surprise", "degout", "neutre"],
}
NOMS = {"alpha": "Alpha Inventé", "bravo": "Bravo Fictif", "lfi": "LFI"}
TEXTES_INVENTES = [
    "zib zob alpha soutien bravo", "zob zib bravo honte demission", "mais equilibre alpha lfi",
    "meeting sondage bravo", "bof mystere lfi zib", "youpi zob joie", "rage zib colere alpha",
    "inquiet zob peur", "triste zib tristesse", "tiens zob surprise", "beurk zib degout",
    "factuel zob neutre lfi", "alpha bravo lundi zib", "lfi zob mardi",
]


def creer_run(dossier: Path, tache: str, longueur_max: int = 64, normaliser: bool = True,
              etiquettes: list[str] | None = None, entree_extra: dict | None = None) -> Path:
    """Crée `dossier/` avec `model/` (poids aléatoires, tokenizer) et `modele.json`.

    `etiquettes` remplace les étiquettes par défaut de la tâche (run à 3 classes, par exemple) ;
    `entree_extra` est fusionné dans `modele.json["entree"]`.
    """
    from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors, trainers
    from transformers import CamembertConfig, CamembertForSequenceClassification, PreTrainedTokenizerFast

    tk = Tokenizer(models.WordPiece(unk_token="<unk>"))
    tk.normalizer = normalizers.Lowercase()
    tk.pre_tokenizer = pre_tokenizers.Whitespace()
    tk.train_from_iterator(TEXTES_INVENTES + list(NOMS.values()), trainers.WordPieceTrainer(
        vocab_size=300, special_tokens=["<s>", "<pad>", "</s>", "<unk>", "<mask>"]))
    tk.post_processor = processors.TemplateProcessing(
        single="<s> $A </s>", pair="<s> $A </s> </s> $B </s>",
        special_tokens=[("<s>", tk.token_to_id("<s>")), ("</s>", tk.token_to_id("</s>"))])
    rapide = PreTrainedTokenizerFast(
        tokenizer_object=tk, bos_token="<s>", eos_token="</s>", unk_token="<unk>", sep_token="</s>",
        cls_token="<s>", pad_token="<pad>", mask_token="<mask>")
    etiquettes = etiquettes if etiquettes is not None else ETIQUETTES[tache]
    config = CamembertConfig(
        vocab_size=len(rapide), hidden_size=32, num_hidden_layers=2, num_attention_heads=2,
        intermediate_size=64, max_position_embeddings=130, type_vocab_size=1,
        pad_token_id=1, bos_token_id=0, eos_token_id=2, num_labels=len(etiquettes))
    dossier.mkdir(parents=True, exist_ok=True)
    CamembertForSequenceClassification(config).save_pretrained(dossier / "model")
    rapide.save_pretrained(dossier / "model")
    meta = {"tache": tache, "etiquettes": etiquettes, "base": "inventee",
            "entree": {"longueur_max": longueur_max, "normaliser": normaliser, **(entree_extra or {})},
            "noms_cibles": NOMS if tache == "stance" else {}}
    (dossier / "modele.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return dossier
