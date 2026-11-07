# Évaluation du modèle

Ce document rassemble les mesures du modèle de stance et d'émotion : CamemBERT et le scoreur à
règles comparés sur le silver, puis le silver comparé au gold. Il ne contient aucun texte de post,
handle, DID ni identifiant de post.

Statuts :
- **mesuré** : compté directement dans un fichier de données ou de métriques.
- **calculé** : dérivé par une formule (pourcentages, intervalles de Wilson).
- **supposé** : interprétation ou hypothèse, à vérifier.

Il n'existe pas encore d'évaluation du modèle sur le gold. Pourquoi un résultat silver seul ne
compte pas : section « Silver et gold » du [guide d'annotation](guide-annotation.md).

## 1. Scoreur à règles et CamemBERT, contre le silver

Mesuré sur le poste de développement (CPU, 2026-10-19). Les runs viennent de la machine GPU ;
leur lecture se fait ici.

### Méthode

- **Mêmes exemples.** Les deux scoreurs reçoivent exactement les exemples de validation du run,
  soit la découpe de l'entraînement (graine et part de validation lues dans
  `config_entrainement.json`). Le script refuse un run dont les effectifs ne correspondent pas à
  `metriques.json`.
- **Tâches.** `stance` : un exemple par couple (post, cible). `emotion` : un exemple par post.
- **Entrée.** Les deux scoreurs reçoivent le texte nettoyé comme le job Spark (minuscules, sans
  accents, URL, `@handles` et `did:` masqués).
- **Scoreur à règles.** `lexique-v1`, `scoring.scorer`. Stance : la stance prédite pour la cible
  si le scoreur la détecte, sinon `non_evalue`. Émotion : l'émotion prédite, ou `non_evalue`.
- **CamemBERT.** `Predicteur`, CPU, 4 threads au plus.
- **Abstention.** `non_evalue` compte comme erreur sur la classe vraie. La couverture est la part
  des exemples où le scoreur tranche. « F1 couvert » ne porte que sur ces exemples.
- **Regex seul sur tout le silver.** Le regex n'a pas d'entraînement : on peut le mesurer sur
  l'ensemble du silver sans fuite. Ce bloc n'est pas comparable au CamemBERT, qui n'a pas vu
  les mêmes posts.

### Résultats

Validation des runs : `stance-20261019-1636` (516 exemples), `emotion-20261019-1700` (313).

| Tâche | Scoreur | Accuracy | F1 macro | Couverture | F1 macro couvert |
|---|---|---|---|---|---|
| stance | règles | 0,010 | 0,008 | 0,016 (8 / 516) | 0,278 (n = 8) |
| stance | CamemBERT | 0,657 | 0,369 | 1,000 | 0,369 |
| emotion | règles | 0,010 | 0,032 | 0,010 (3 / 313) | 1,000 (n = 3) |
| emotion | CamemBERT | 0,626 | 0,194 | 1,000 | 0,194 |

Silver complet (regex seul, sans entraînement) : stance 4 125 couples, accuracy 0,023, couverture
0,030 ; emotion 2 504 posts, accuracy 0,005, couverture 0,008.

F1 par classe sur la validation (support entre parenthèses) :

| Classe | Stance règles | Stance CamemBERT | Emotion règles | Emotion CamemBERT |
|---|---|---|---|---|
| pour / joie | 0,000 (60) | 0,234 (60) | 0,105 (18) | 0,000 (18) |
| contre / colere | 0,041 (236) | 0,715 (236) | 0,000 (86) | 0,602 (86) |
| neutre | 0,000 (18) | 0,000 (18) | 0,000 (156) | 0,759 (156) |
| mention / degout | 0,000 (191) | 0,751 (191) | 0,118 (32) | 0,000 (32) |
| ambigu | 0,000 (11) | 0,143 (11) | — | — |
| peur | — | — | 0,000 (10) | 0,000 (10) |
| tristesse | — | — | 0,000 (7) | 0,000 (7) |
| surprise | — | — | 0,000 (4) | 0,000 (4) |

Un tiret (`—`) signale une classe absente du schéma de la tâche.

Matrices de confusion et F1 du silver complet : dans le JSON d'agrégats (voir Reproduction).

### Lecture

- **Le scoreur à règles ne répond presque jamais.** Il tranche sur 1,6 % des couples de stance et
  sur 1 % des posts d'émotion. Sur ces rares cas, sa qualité ne se juge pas : 8 et 3 exemples.
- **28 cibles de la validation n'existent pas dans le lexique.** Pour elles, le regex ne peut pas
  répondre, quelle que soit la règle. Cela est mesuré (`cible_hors_lexique`).
- **CamemBERT dépasse la classe majoritaire sur les deux tâches** : 0,657 contre 0,457 (`contre`,
  236 / 516) en stance ; 0,626 contre 0,498 (`neutre`, 156 / 313) en émotion. L'écart ne vaut que
  sur ces validations. Il ne dit rien de la qualité sur des posts réels.
- **Silver = étiquettes d'un LLM.** On mesure l'accord avec ce LLM, pas la vérité. `metriques.json` l'écrit lui-même : « silver : test de fumée, pas une mesure du modèle ».
- **La validation a aussi servi à choisir l'époque.** Les scores publiés sont donc légèrement
  optimistes. Il n'y a pas de jeu de test séparé.
- **Déséquilibre des classes.** En émotion, `neutre` (156) et `colere` (86) dominent ; `surprise`
  n'a que 4 exemples. Le F1 macro masque cette différence : il reste proche de 0,2 pour CamemBERT.
- **Petits effectifs.** La validation a 313 à 516 exemples. Une classe de 4 à 10 exemples ne
  donne qu'une estimation grossière.
- **Entrée du modèle.** Le run a été entraîné sur le texte normalisé sans masquage des URL et des
  `@handles`. Ici, le texte est masqué comme dans le job. 35 couples de stance et 24 posts
  d'émotion changent. L'accuracy recalculée est identique à celle de `metriques.json` (0,657 et
  0,626). Cela ne dit pas que le masquage ne change rien aux prédictions.

### Reproduction

Depuis la racine du dépôt. Le corpus réel reste hors dépôt ; `$SAE_CORPUS_DIR` pointe dessus.

```bash
uv run -q --python 3.12 --no-project \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  --with-requirements src/training/requirements-train.txt --with pandas \
  python scripts/comparer_regex_modele.py \
  --corpus "$SAE_CORPUS_DIR" \
  --run-stance stance-20261019-1636 --run-emotion emotion-20261019-1700 \
  --sortie "$SAE_CORPUS_DIR/comparaisons/regex-vs-camembert-2026-10-19.json"
```

Durée mesurée : 167 s. Tests : `tests/test_comparer_regex_modele.py` (10 tests, 27 s, données
inventées).

## 2. Silver contre gold

Reproduction (depuis la racine du dépôt, corpus hors dépôt ; le script imprime des agrégats
seulement) :

```
python3 -I src/training/comparer_gold_silver.py --corpus <dossier du corpus>
```

### Périmètre

| Jeu | Taille | Statut | Source |
|---|---|---|---|
| Gold (annotation humaine) | 30 posts, 1 annotateur, 45 lignes de cibles | mesuré | `annotation/annotations/corentin.jsonl` |
| Posts gold avec émotion | 26 (24 pertinents « oui », 2 « doute ») ; 4 « non » exclus | mesuré | idem |
| Silver (LLM) | 2 978 posts ; les 30 posts gold y figurent | mesuré | `annotation/silver/final/silver_v1.jsonl` |
| Train silver | 2 725 posts | mesuré | `annotation/train_silver.jsonl` |
| Lot figé d'évaluation | 200 posts, ids identiques à `eval_fige.json` | mesuré | `annotation/lots/lot_eval.jsonl`, `annotation/eval_fige.json` |

### Accord

Accord exact : même étiquette pour le même post (ou la même entité). IC95 : intervalle de
Wilson à 95 %.

| Champ | Accord | Pourcentage | IC95 | Statut | Source |
|---|---|---|---|---|---|
| Pertinence (30 posts) | 21/30 | 70,0 % | [52,1 ; 83,3] % | mesuré, calculé | script |
| Entité citée aussi par silver (45 lignes) | 41/45 | 91,1 % | [79,3 ; 96,5] % | mesuré, calculé | script |
| Entité et stance identiques (45 lignes) | 13/45 | 28,9 % | [17,7 ; 43,4] % | mesuré, calculé | script |
| Émotion (26 posts) | 13/26 | 50,0 % | [32,1 ; 67,9] % | mesuré, calculé | script |

Lecture :
- **Pertinence.** Sur les 4 posts gold « non », silver en donne 3 « oui » et 1 « doute ».
  Silver classe aussi 3 posts gold « oui » en « doute ».
- **Cibles.** Le désaccord se concentre sur une paire. Gold donne `neutre` à 18 lignes ;
  silver donne `mention` à 15 des 17 lignes `neutre` qu'il cite. Silver emploie `mention`
  23 fois sur les 41 lignes communes, gold 2 fois sur 45 (mesuré).
  Hypothèse (supposé) : les définitions de `neutre` et de `mention` ne coïncident pas entre
  le gold et le silver. À vérifier avant de conclure sur la qualité du silver.
- **Émotion.** Silver donne `neutre` à 12 posts, gold à 7. Silver ne donne ni `peur` ni
  `tristesse` sur ces 26 posts (mesuré). Le gold en porte 1 et 3.

Limite : 30 posts, un seul annotateur. Les intervalles sont larges. Un écart de quelques
posts change fortement le pourcentage.

### Couverture du lexique d'émotion

Source : `ressources/lexique/emotions.yaml`. Le scoreur `lexique-v1` ne retient qu'un marqueur
de confiance `haute` ou `moyenne`.

Marqueurs par classe (mesuré par le script) :

| Classe | Marqueurs | Utiles (haute ou moyenne) |
|---|---|---|
| `degout` | 3 | 2 |
| `colere` | 2 | 2 |
| `joie` | 2 | 1 |
| `peur`, `tristesse`, `surprise` | 0 | 0 |
| `neutre` | 0 (absence d'émotion, par conception) | 0 |

Déclenchements (mesuré par le script, approché : voir la limite ci-dessous) :

| Jeu | Posts | Au moins un marqueur utile | Classes déclenchées |
|---|---|---|---|
| Gold, 26 posts avec émotion | 26 | 0 | aucune |
| Train silver | 2 725 | 21 (0,8 %) | `colere` 8, `degout` 9, `joie` 5 (un post peut en déclencher deux) |

Limite : le script reproduit la règle du scoreur (minuscules, sans accents, URL et handles
retirés), sur le texte brut du corpus. Le texte réellement passé au scoreur (job Spark) peut
différer. Ce comptage n'est donc pas la sortie du scoreur.

Couverture des règles de stance (0 ligne sur 45, calcul approché antérieur) : **non vérifié
ici**.

Règle de décision future (non appliquée) : retirer une classe du lexique, ou ne pas la
publier comme sortie du scoreur, si sa couverture sur le **nouveau** corpus reste insuffisante.
Le seuil sera fixé plus tard, sur ce nouveau corpus, avant le premier entraînement.

### Fuite entre gold et train silver

- L'export `--silver` exclut tous les posts annotés à la main de `annotation/train_silver.jsonl`,
  sans option. Un garde-fou arrête l'export si un post gold figure dans sa sortie.
- Le `train_silver.jsonl` du corpus local contient encore **20 posts gold** (mesuré). Il ne suit
  pas cette règle : il faut le régénérer avant tout entraînement.
- Toute évaluation sur le gold, faite avec un modèle entraîné sur ce fichier, est biaisée.
- Le lot figé ne fuit pas : 0 post du lot figé dans `train_silver` (mesuré), 0 post du gold dans
  le lot figé (mesuré).

### Jeu de test gold conservé

Les 30 posts gold servent de jeu de test (décision de l'utilisateur). L'export ne les écrit pas
dans `train_silver.jsonl` (voir « Fuite entre gold et train silver »), et aucun entraînement n'en lit d'autre.

- `train.jsonl` et `eval.jsonl` du corpus local sont vides (mesuré) : aucun post gold n'y figure.
- Le code de l'export place les posts gold hors lot figé dans `train.jsonl`. Aucun entraînement ne
  lit ce fichier à ce jour (`src/training/modele/donnees.py` lit `train_silver.jsonl`). Il ne sert donc pas
  d'entrée d'entraînement sans nouvelle décision.

### Lot figé d'évaluation

- Les 200 ids de `lot_eval.jsonl` sont identiques à ceux de `eval_fige.json` (mesuré).
- Aucun de ces posts n'a d'annotation humaine (mesuré : 0).
- Les 200 posts portent une étiquette silver (mesuré : 200).
- Conséquence : ce lot n'est pas une référence humaine. Il doit être annoté à la main avant
  tout usage comme gold.

## 3. Regroupement `mention` et `neutre` (option, non mesuré)

Constat (mesuré, voir « Silver contre gold ») : 15 lignes sur 45 ont `neutre` côté gold et `mention` côté silver.
Le F1 de la classe `neutre` vaut 0 contre le silver (tableau par classe ci-dessus).

L'option `--stance-regroupe-neutre` fusionne `mention` dans `neutre` :

- `annotation.export` : la fusion s'applique à `train.jsonl`, `eval.jsonl` et `train_silver.jsonl`.
- `modele.entrainer` : les classes de stance deviennent `pour`, `contre`, `neutre`, `ambigu`. La
  fusion s'applique aussi à un `train_silver.jsonl` exporté sans l'option (elle est idempotente).
- C'est une projection (`src/training/projection_stance.py`). Le schéma `annotation/schema.yaml`
  garde ses cinq valeurs, et les étiquettes d'origine ne changent jamais.
- Sans l'option, rien ne change.

Statut : **non mesuré**. Aucun entraînement n'a été lancé avec l'option. On ne sait pas si le F1
de `neutre` monte, ni ce que devient le F1 macro. Un run avec l'option ne se compare pas à un run
sans elle (quatre classes au lieu de cinq).

Limites :

- La fusion repose sur une hypothèse (supposé, voir « Silver contre gold ») : les définitions de `neutre` et de
  `mention` ne coïncident pas. Si elle est fausse, la fusion masque une distinction réelle.
- `comparer_gold_silver.py` n'a pas l'option : l'accord gold/silver reste calculé sur cinq classes.

## 4. Limites

- 30 posts gold, un annotateur : les intervalles sont larges.
- Les classes rares sont absentes ou quasi absentes du gold : `peur` 1, `tristesse` 3, aucune
  `surprise`.
- Les métriques des runs sont lues dans les fichiers de la passe du 19 octobre ; ce document ne
  les recalcule pas.
