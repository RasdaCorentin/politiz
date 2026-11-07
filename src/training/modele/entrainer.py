"""Entraînement de CamemBERT sur le silver : une tâche par run (forme du run : contrat du modèle).

    python -m modele.entrainer --tache stance|emotion --corpus <dossier> --sortie <dossier des runs>

Écrit `<sortie>/<tache>-<AAAAMMJJ-HHMM>/` (model/, modele.json, metriques.json,
config_entrainement.json). Progression sur stderr, sans texte de post. La dernière ligne de
stdout est le chemin absolu du run. Code de retour non nul en cas d'échec.

Choix d'entraînement (valeurs par défaut de la CLI, sauf mention) :
- AdamW, décroissance 0,01 ; préchauffage linéaire sur 10 % des pas, puis décroissance linéaire ;
- perte pondérée par classe, poids (n / (K n_c)) ** 0,5 (voir donnees.poids_classes) ;
- écrêtage de la norme du gradient à 1,0 ;
- précision mixte sur CUDA : bf16 si la carte la supporte, sinon fp16 avec GradScaler ;
- validation à chaque époque (12 % du silver, découpe par post) ; l'époque qui maximise le F1
  macro est gardée, et ses poids sont ceux du run.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import random
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from . import donnees, evaluation

BASE_DEFAUT = "almanach/camembert-base"
EPOQUES_DEFAUT = 3
LOT_DEFAUT = 16
LR_DEFAUT = 2e-5
LONGUEUR_DEFAUT = 256
GRAINE_DEFAUT = 2027
PART_VALIDATION = 0.12
DECROISSANCE = 0.01
ECHAUFFEMENT = 0.1
ECRETAGE = 1.0
ALPHA_POIDS = 0.5
CRITERES = ("f1_macro", "rappel_macro")   # choix de la meilleure époque sur la validation
NORMALISER = True           # même normalisation que le job Spark (étape de nettoyage)
NETTOYER = True             # retire les marqueurs des lots, puis nettoie comme le job Spark (donnees.preparer_texte)
PAS_JOURNAL = 20
SOURCE = "silver"
SOURCES_AVEC_GOLD = ("silver", "gold")
MENTION_AVEC_GOLD = ("silver et gold mêlés : la validation a choisi l'époque ; "
                     "mesurer sur un gold tenu hors de l'entraînement")


def log(message: str) -> None:
    print(f"[entrainement] {message}", file=sys.stderr, flush=True)


def analyser_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m modele.entrainer", description=__doc__.split("\n")[0])
    p.add_argument("--tache", required=True, choices=donnees.TACHES)
    p.add_argument("--corpus", required=True, help="dossier contenant annotation/train_silver.jsonl et eval_fige.json")
    p.add_argument("--sortie", required=True, help="dossier des runs")
    p.add_argument("--base", default=BASE_DEFAUT)
    p.add_argument("--epoques", type=int, default=EPOQUES_DEFAUT)
    p.add_argument("--lot", type=int, default=LOT_DEFAUT)
    p.add_argument("--lr", type=float, default=LR_DEFAUT)
    p.add_argument("--longueur-max", type=int, default=LONGUEUR_DEFAUT)
    p.add_argument("--plafond", type=int, default=None,
                   help="exemples max par classe et par époque (tirage neuf à chaque époque)")
    p.add_argument("--critere", choices=CRITERES, default="f1_macro",
                   help="métrique de validation qui choisit l'époque gardée")
    p.add_argument("--alpha-poids", type=float, default=ALPHA_POIDS,
                   help="poids de classe (n / (K n_c)) ** alpha : 0 aucun, 1 inverse de la fréquence")
    p.add_argument("--avec-gold", action="store_true",
                   help="accepte des lignes `source: gold` dans train_silver.jsonl (gold tenu hors du test)")
    p.add_argument("--appareil", choices=("auto", "cpu", "cuda"), default="auto")
    p.add_argument("--graine", type=int, default=GRAINE_DEFAUT)
    p.add_argument("--stance-regroupe-neutre", action="store_true",
                   help="stance seulement : fusionne mention dans neutre (projection ; le modèle a 4 classes)")
    p.add_argument("--emotion-3-classes", action="store_true",
                   help="emotion seulement : projette en joie / colere / neutre (projection ; le modèle a 3 classes)")
    args = p.parse_args(argv)
    if args.epoques < 1 or args.lot < 1 or args.longueur_max < 8:
        p.error("--epoques et --lot doivent être >= 1, --longueur-max >= 8")
    if args.plafond is not None and args.plafond < 1:
        p.error("--plafond doit être >= 1")
    if not 0 <= args.alpha_poids <= 2:
        p.error("--alpha-poids doit être entre 0 et 2")
    if args.stance_regroupe_neutre and args.tache != "stance":
        p.error("--stance-regroupe-neutre ne s'applique qu'à --tache stance")
    if args.emotion_3_classes and args.tache != "emotion":
        p.error("--emotion-3-classes ne s'applique qu'à --tache emotion")
    return args


def choisir_appareil(demande: str) -> str:
    import torch

    if demande == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if demande == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA demandé, mais aucune carte n'est disponible")
    return demande


def choisir_precision(appareil: str) -> tuple[str, object | None]:
    """(mode, GradScaler ou None). bf16 si la carte le permet, sinon fp16 avec mise à l'échelle."""
    import torch

    if appareil != "cuda":
        return "fp32", None
    if torch.cuda.is_bf16_supported():
        return "bf16", None
    return "fp16", torch.amp.GradScaler("cuda")


def contexte_precision(mode: str, appareil: str):
    import torch

    if mode == "fp32":
        return contextlib.nullcontext()
    dtype = torch.bfloat16 if mode == "bf16" else torch.float16
    return torch.autocast(device_type=appareil, dtype=dtype)


def preparer_donnees(corpus: Path, tache: str, graine: int, regroupe: bool = False,
                     emotion_reduite: bool = False, avec_gold: bool = False):
    """(exemples d'entraînement, exemples de validation). Refuse tout post du pilote ou de l'évaluation.
    `avec_gold` accepte des lignes gold à côté du silver ; sinon, toute ligne non silver est refusée."""
    lignes = donnees.charger_lignes(corpus / "annotation" / "train_silver.jsonl",
                                    SOURCES_AVEC_GOLD if avec_gold else SOURCE)
    donnees.verifier_garde_fou(lignes, corpus)
    exemples = donnees.construire_exemples(lignes, tache, regroupe=regroupe, emotion_reduite=emotion_reduite)
    if not exemples:
        raise ValueError(f"aucun exemple utilisable pour la tâche {tache}")
    return donnees.decouper(exemples, PART_VALIDATION, graine)


def collate(ids: list[list[int]], pad_id: int, appareil: str):
    import torch

    largeur = max(len(x) for x in ids)
    entree = torch.full((len(ids), largeur), pad_id, dtype=torch.long)
    masque = torch.zeros((len(ids), largeur), dtype=torch.long)
    for r, x in enumerate(ids):
        entree[r, :len(x)] = torch.tensor(x, dtype=torch.long)
        masque[r, :len(x)] = 1
    return entree.to(appareil), masque.to(appareil)


def evaluer(modele, ids, y, lot, pad_id, appareil, contexte, critere) -> tuple[list[int], float]:
    """Prédictions (indices de classe) et perte moyenne sur un jeu, sans gradient."""
    import torch

    modele.eval()
    predits: list[int] = []
    perte = 0.0
    with torch.no_grad():
        for debut in range(0, len(ids), lot):
            entree, masque = collate(ids[debut:debut + lot], pad_id, appareil)
            cible = torch.tensor(y[debut:debut + lot], dtype=torch.long, device=appareil)
            with contexte:
                logits = modele(input_ids=entree, attention_mask=masque).logits.float()
            perte += critere(logits, cible).item() * len(cible)
            predits.extend(logits.argmax(dim=-1).tolist())
    return predits, perte / len(ids)


def entrainer_epoque(modele, optimiseur, ordonnanceur, scaler, critere, ids, y, args, pad_id,
                     appareil, mode, rng, epoque):
    """Une passe d'entraînement sur l'échantillon de l'époque. Retourne la perte moyenne."""
    import torch

    modele.train()
    ordre = list(range(len(ids)))
    rng.shuffle(ordre)
    n_lots = math.ceil(len(ordre) / args.lot)
    perte_tot = 0.0
    for num, debut in enumerate(range(0, len(ordre), args.lot), 1):
        idx = ordre[debut:debut + args.lot]
        entree, masque = collate([ids[i] for i in idx], pad_id, appareil)
        cible = torch.tensor([y[i] for i in idx], dtype=torch.long, device=appareil)
        with contexte_precision(mode, appareil):
            logits = modele(input_ids=entree, attention_mask=masque).logits.float()
        perte = critere(logits, cible)
        if scaler is not None:
            scaler.scale(perte).backward()
            scaler.unscale_(optimiseur)
        else:
            perte.backward()
        torch.nn.utils.clip_grad_norm_(modele.parameters(), ECRETAGE)
        if scaler is not None:
            scaler.step(optimiseur)
            scaler.update()
        else:
            optimiseur.step()
        ordonnanceur.step()
        optimiseur.zero_grad(set_to_none=True)
        perte_tot += perte.item() * len(idx)
        if num % PAS_JOURNAL == 0 and num != n_lots:
            log(f"époque {epoque}/{args.epoques}, lot {num}/{n_lots}, perte {perte.item():.4f}")
    return perte_tot / len(ordre)


def ecrire_run(run: Path, modele, tokenizer, meta: dict, metriques: dict, config: dict) -> None:
    (run / "model").mkdir()
    modele.save_pretrained(run / "model")
    tokenizer.save_pretrained(run / "model")
    for nom, contenu in (("modele.json", meta), ("metriques.json", metriques),
                         ("config_entrainement.json", config)):
        (run / nom).write_text(json.dumps(contenu, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def executer(args: argparse.Namespace) -> Path:
    import torch
    import transformers
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

    debut = time.monotonic()
    corpus = Path(args.corpus).expanduser()
    regroupe = args.stance_regroupe_neutre
    emotion_reduite = args.emotion_3_classes
    etiquettes = donnees.etiquettes(args.tache, regroupe=regroupe, emotion_reduite=emotion_reduite)
    idx_classe = {e: i for i, e in enumerate(etiquettes)}
    K = len(etiquettes)

    train, val = preparer_donnees(corpus, args.tache, args.graine, regroupe, emotion_reduite, args.avec_gold)
    noms = donnees.noms_cibles() if args.tache == "stance" else {}
    appareil = choisir_appareil(args.appareil)
    mode, scaler = choisir_precision(appareil)
    transformers.set_seed(args.graine)
    rng = random.Random(args.graine)

    maintenant = datetime.now()
    sortie = Path(args.sortie).expanduser()
    sortie.mkdir(parents=True, exist_ok=True)
    run = sortie / f"{args.tache}-{maintenant:%Y%m%d-%H%M}"
    run.mkdir()                                  # échoue si le run existe déjà : jamais d'écrasement
    try:
        log(f"tâche {args.tache} : {len(train)} exemples d'entraînement, {len(val)} de validation, "
            f"appareil {appareil} ({mode})")
        tokenizer = AutoTokenizer.from_pretrained(args.base)
        modele = AutoModelForSequenceClassification.from_pretrained(
            args.base, num_labels=K, id2label=dict(enumerate(etiquettes)), label2id=idx_classe,
            ignore_mismatched_sizes=True).to(appareil)

        def encoder(ex):
            cibles = [e.cible for e in ex] if args.tache == "stance" else None
            return donnees.jetons(tokenizer, [e.texte for e in ex], cibles, args.tache, noms,
                                  args.longueur_max, NORMALISER)

        ids_val = encoder(val)
        y_val = [idx_classe[e.etiquette] for e in val]
        y_train_tous = [idx_classe[e.etiquette] for e in train]
        poids = torch.tensor(donnees.poids_classes(y_train_tous, K, args.alpha_poids), dtype=torch.float32,
                             device=appareil)
        critere = torch.nn.CrossEntropyLoss(weight=poids)

        taille_epoque = len(donnees.echantillon_epoque(train, args.plafond, random.Random(0)))
        total_pas = args.epoques * math.ceil(taille_epoque / args.lot)
        optimiseur = torch.optim.AdamW(modele.parameters(), lr=args.lr, weight_decay=DECROISSANCE)
        ordonnanceur = get_linear_schedule_with_warmup(optimiseur, int(ECHAUFFEMENT * total_pas), total_pas)

        historique = []
        meilleur_score, meilleure_epoque, meilleur_etat = -1.0, 0, None
        vrais_val = [etiquettes[i] for i in y_val]
        for epoque in range(1, args.epoques + 1):
            debut_epoque = time.monotonic()
            echantillon = donnees.echantillon_epoque(train, args.plafond, rng)
            ids_train = encoder(echantillon)
            y_epoque = [idx_classe[e.etiquette] for e in echantillon]
            perte_train = entrainer_epoque(modele, optimiseur, ordonnanceur, scaler, critere, ids_train,
                                           y_epoque, args, tokenizer.pad_token_id, appareil, mode, rng, epoque)
            predits, perte_val = evaluer(modele, ids_val, y_val, args.lot, tokenizer.pad_token_id, appareil,
                                         contexte_precision(mode, appareil), critere)
            resume = evaluation.resume(vrais_val, [etiquettes[i] for i in predits], etiquettes)
            ligne = {"epoque": epoque, "perte_entrainement": round(perte_train, 4),
                     "perte_validation": round(perte_val, 4), "accuracy": resume["accuracy"],
                     "f1_macro": resume["f1_macro"], "rappel_macro": resume["rappel_macro"], "duree_s": round(time.monotonic() - debut_epoque, 1)}
            historique.append(ligne)
            log(f"époque {epoque}/{args.epoques} : perte entraînement {perte_train:.4f}, "
                f"perte validation {perte_val:.4f}, accuracy {resume['accuracy']:.3f}, "
                f"F1 macro {resume['f1_macro']:.3f}, rappel macro {resume['rappel_macro']:.3f}")
            if resume[args.critere] > meilleur_score:
                meilleur_score, meilleure_epoque = resume[args.critere], epoque
                meilleur_etat = {k: v.detach().to("cpu", copy=True) for k, v in modele.state_dict().items()}

        modele.load_state_dict(meilleur_etat)
        predits, _ = evaluer(modele, ids_val, y_val, args.lot, tokenizer.pad_token_id, appareil,
                             contexte_precision(mode, appareil), critere)
        resume = evaluation.resume(vrais_val, [etiquettes[i] for i in predits], etiquettes)
        log(f"époque retenue : {meilleure_epoque} ({args.critere} validation {meilleur_score:.3f})")

        meta = {"tache": args.tache, "etiquettes": etiquettes, "base": args.base,
                "entree": {"longueur_max": args.longueur_max, "normaliser": NORMALISER, "nettoyer": NETTOYER},
                "noms_cibles": noms}
        metriques = {**resume, "effectifs": {"entrainement": donnees.effectifs(train),
                                             "validation": donnees.effectifs(val)},
                     "epoque_retenue": meilleure_epoque, "critere": args.critere, "historique": historique,
                     "source": "+".join(SOURCES_AVEC_GOLD) if args.avec_gold else SOURCE,
                     "mention": MENTION_AVEC_GOLD if args.avec_gold else donnees.MENTION_SILVER,
                     "duree_s": round(time.monotonic() - debut, 1),
                     "materiel": {"appareil": appareil, "precision": mode,
                                  "gpu": torch.cuda.get_device_name(0) if appareil == "cuda" else None}}
        config = {"tache": args.tache, "base": args.base, "epoques": args.epoques, "lot": args.lot,
                  "lr": args.lr, "longueur_max": args.longueur_max, "plafond": args.plafond,
                  "appareil_demande": args.appareil, "graine": args.graine,
                  "part_validation": PART_VALIDATION, "decroissance": DECROISSANCE,
                  "echauffement": ECHAUFFEMENT, "ecretage": ECRETAGE, "alpha_poids": args.alpha_poids,
                  "critere": args.critere, "stance_regroupe_neutre": regroupe, "avec_gold": args.avec_gold,
                  "normaliser": NORMALISER, "emotion_3_classes": emotion_reduite,
                  "versions": {"torch": torch.__version__, "transformers": transformers.__version__}}
        ecrire_run(run, modele.to("cpu"), tokenizer, meta, metriques, config)
    except BaseException:
        shutil.rmtree(run, ignore_errors=True)   # pas de run partiel, qu'on pourrait prendre pour bon
        raise
    return run.resolve()


def main(argv: list[str] | None = None) -> int:
    args = analyser_arguments(argv)
    try:
        run = executer(args)
    except Exception as e:  # message seulement : jamais de trace, qui peut contenir des valeurs
        log(f"échec : {type(e).__name__} : {e}")
        return 1
    print(run, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
