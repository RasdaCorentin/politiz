# Guide d'annotation

Public : les annotateurs (étudiants, sans expérience en machine learning). Tous les exemples sont inventés. Le schéma de référence est dans [`schema.yaml`](../../src/training/annotation/schema.yaml).

## 1. Pourquoi annoter

Un modèle de sentiment donne une réponse sans dire si elle est juste. Nous annotons à la main pour trois raisons.

1. **Évaluer** les modèles pré-entraînés (sentiment, émotion, zero-shot) : on compare leur réponse à la tienne.
2. **Entraîner** plus tard un classifieur sur nos posts.
3. **Repérer les cas qui n'ont pas besoin de modèle** : si une expression suffit (champ `regle_suffit`), une règle simple fera le travail, plus vite et sans erreur surprenante.

Tu ne cherches pas « la bonne réponse du modèle ». Tu dis ce que le post exprime, pour un lecteur francophone attentif.

Un modèle de classification ne « comprend » pas la stance politique. Il apprend une correspondance entre des textes et des étiquettes : ses étiquettes fixent sa définition de la tâche. Si l'on mélange « critique » et « simple mention », il les mélangera aussi. Annoter, c'est **définir la tâche**.

**Où ton temps compte le plus.** Le silver fournit déjà des données d'entraînement (section « Silver et gold »). Ton temps a plus de valeur sur l'**évaluation** : d'abord le pilote (comprendre le guide de la même façon), puis le jeu d'évaluation (la seule mesure fiable), puis seulement les lots d'entraînement.

## 2. Lancer l'outil

**Avant la première séance.** Le corpus vit hors Git, sur le poste qui l'a rapatrié. Pour annoter ailleurs, copie le dossier (droits 700) et note la copie : le Livrable 1 (M11) tient une liste de chaque copie. Tout s'efface **30 jours au plus** après la collecte. Il faut `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`). Lis les sections « Les champs » et « Cas difficiles » de ce guide (15 min).

Depuis `src/training`, en remplaçant les chemins et ton prénom (sans accent) :

```
uv run --with-requirements requirements.txt streamlit run annotation/app.py -- --lot <dossier du corpus>/annotation/lots_gold/lot_gold_01.jsonl --annotateur <prénom> --corpus-dir <dossier du corpus>
```

Le navigateur affiche l'adresse que Streamlit indique (par défaut `http://localhost:8501`).

Un lot compte 20 posts. Une validation enregistre le post et passe au suivant. Au lancement, l'outil reprend au premier post non annoté. Tu peux t'arrêter à tout moment : chaque post validé est déjà enregistré.

- **Entrée** : un fichier `lot_gold_NN.jsonl`, un post par ligne. Les mentions de comptes et les liens sont remplacés par `[mention]` et `[url]` : ne les cherche pas.
- **Sortie** : `<dossier du corpus>/annotation/annotations/<prénom>.jsonl`, une ligne par validation. Ne modifie jamais ce fichier à la main.
- **Correction** : reviens sur le post avec « Précédent », change le choix, valide. L'outil ajoute une ligne ; la dernière fait foi.
- **Valeurs de départ** : `pertinent` = oui, émotion = neutre, ironie = non, règle suffit = non. Change-les quand elles ne correspondent pas au post.
- **Raccourcis** : `Alt+Entrée` enregistre et passe au suivant, `Alt+←` revient au post précédent. Les choix se font aux boutons.

Règles de base :

- Annote seul, sans regarder les réponses des autres, jusqu'à la réunion de désaccords.
- Ne copie ni ne partage aucun texte de post hors de l'outil (pas de capture, pas de message).
- En cas de doute, choisis la réponse prudente (`doute`, `ambigu`) et écris un commentaire court.

## 3. Les champs

### 3.1 `pertinent`

Le post parle-t-il de la politique française ou de la présidentielle de 2027 ?

| Valeur | Quand |
| --- | --- |
| `oui` | Le post porte sur un candidat, un parti, le gouvernement, une mesure, une élection française. |
| `non` | Le sujet est autre : homonyme, sport, politique étrangère sans lien avec la France, hors sujet. |
| `doute` | Tu ne peux pas trancher sans contexte. |

Si tu réponds `non`, tous les autres champs restent vides. L'outil les efface.

Si tu réponds `doute`, les autres champs sont **facultatifs**. Remplis ce que tu peux, laisse le reste vide, et écris un commentaire. L'outil enregistre sans exiger de stance ni d'émotion.

Exemple `non` : « Mon voisin Bertrand a gagné au tournoi de pétanque. » (prénom, pas le politicien).

### 3.2 `cibles`

Chaque cible est une entité et une **stance**. Les entités viennent de [`ressources/lexique/entites.yaml`](../../ressources/lexique/entites.yaml) (candidats et partis), plus trois valeurs : `gouvernement`, `groupe-politique` et `autre`.

**Personne et parti sont distincts** : `le pen` n'est pas `rassemblement national`, `melenchon` n'est pas `lfi`. Choisis celui que le texte vise. S'il vise les deux, crée deux cibles.

Les cibles se choisissent dans la liste proposée par l'outil, sans saisie libre. L'outil ne détecte pas les entités à ta place : lis le post et choisis celles qui sont visées.

Stance, c'est la position **du texte** envers l'entité, pas la tienne :

| Valeur | Sens |
| --- | --- |
| `pour` | Soutien, éloge, appel à voter pour. |
| `contre` | Critique, moquerie, rejet. |
| `neutre` | **Jugement équilibré** : le texte pèse le pour et le contre, sans trancher. |
| `mention` | Cité **sans jugement** : un fait, un agenda, un résultat de sondage, un titre d'article. |
| `ambigu` | Impossible à trancher, ou ironie indécidable. |

`mention` et `neutre` sont différents. Une mention signale que la cible intéresse l'auteur : poids faible, mais information réelle. `neutre` est rare et demande un vrai jugement.

- `mention` : « Dupont sera à Lyon jeudi pour un meeting. » ; « Sondage : Martin à 12 %. » ; « Durand dépose sa candidature. »
- `neutre` : « Martin a de bonnes idées sur la santé, mais son budget ne tient pas. » (les deux côtés, pas de choix).

Un post sans entité politique précise (une mesure, une ambiance) peut avoir zéro cible. Un groupe sans nom propre (« la gauche », « la droite », « les macronistes », « l'extrême droite ») est la cible `groupe-politique`. Un parti nommé garde sa propre entité.

### 3.3 `themes` (0 à plusieurs)

`economie`, `social-retraites`, `immigration`, `securite`, `ecologie`, `europe-international`, `institutions`, `sante-education`, `campagne-sondages`, `autre`.

- Coche seulement les thèmes **abordés dans le texte**, pas ceux que tu devines.
- `campagne-sondages` : stratégie, candidatures, meetings, sondages, petites phrases.
- `autre` : sujet politique qui ne rentre dans aucune case. Ne l'ajoute pas par défaut.

### 3.4 `emotion` (une seule)

`joie`, `colere`, `peur`, `tristesse`, `surprise`, `degout`, `neutre`.

Choisis l'émotion **dominante** exprimée par l'auteur. Si le ton est factuel, mets `neutre`. Colère (contre quelqu'un, une injustice) et dégoût (rejet moral, écœurement) se confondent souvent : colère = « ça me révolte, il faut réagir » ; dégoût = « c'est répugnant ».

### 3.5 `ironie`

`oui` si le sens voulu est l'inverse du sens littéral (voir « Ironie » dans les cas difficiles). Sinon `non`.

### 3.6 `regle_suffit` et `indice`

`oui` si **une expression à elle seule** suffit pour décider la stance ou le thème, sans comprendre la phrase. Recopie cette expression dans `indice`.

Exemples inventés :

- « Dupont démission ! » : l'expression « démission » suffit → stance `contre`. `regle_suffit = oui`, indice « démission ».
- « Je vote Martin dès le premier tour » : « je vote Martin » suffit → `pour`. `oui`.
- « On dit que Durand n'est pas aussi mauvais que prévu » : il faut lire la phrase. `non`.

Si l'expression fonctionne aussi dans un contexte inverse (« pas de démission pour Dupont »), la règle ne suffit pas : `non`.

### 3.7 `commentaire`

Texte libre. Écris-y tout doute ou cas limite. Ces commentaires servent à améliorer ce guide.

## 4. Cas difficiles : règles de décision

### 4.1 Négation

La négation inverse la stance de la proposition niée. **Refuser son soutien = `contre`** : « Je ne voterai pas Dupont », « je ne soutiens pas Martin » → `contre`.
Repère les doubles négations : « Personne ne peut dire que Martin est incompétent » → `pour`.

### 4.2 Ironie

L'ironie dit le contraire de ce qu'elle pense. Indices : exagération, guillemets, « bravo », « quel génie », décalage avec le contexte.

- « Bravo Dupont, encore une réforme qui va tout régler ! » → `ironie = oui`, stance `contre`, émotion `colere` ou `degout`.
- Annote la stance **voulue**, pas la littérale.
- Si tu ne peux pas décider entre ironie et sincérité, mets `ironie = non`, stance `ambigu`, et commente.

### 4.3 Citation d'un adversaire

Quand l'auteur cite quelqu'un pour s'en moquer ou le contredire, la stance suit l'**auteur**.
« Martin dit "tout va bien", on voit bien le résultat » → `contre` Martin.
Si l'auteur se contente de rapporter sans commentaire (« Martin a déclaré qu'il se présenterait »), c'est `mention`.

### 4.4 Question rhétorique

Une question qui affirme. Lis-la comme une affirmation.
« Qui peut encore croire Durand ? » → `contre` Durand.
Une vraie question qui demande une information (« Quand est le débat avec Martin ? ») → `mention`.

### 4.5 Plusieurs cibles

Crée une cible par entité, avec sa propre stance. Les stances peuvent diverger.
« Martin vaut mieux que Dupont » → Martin `pour`, Dupont `contre`.
Pour les groupes (« la droite », « la gauche », « les macronistes ») sans nom de parti : entité `groupe-politique`. Un parti nommé (« le RN ») reçoit son entité propre. `autre` reste pour tout ce qui n'est ni un candidat, ni un parti, ni le gouvernement, ni un groupe.
Un candidat et son parti cités ensemble : deux cibles (personne et parti sont distincts), avec la même stance si le texte ne les sépare pas.

### 4.6 Autres pièges

- **Hashtag, émoji seul** : lis-les comme du texte (« #DupontDegage » est `contre`).
- **Lien sans commentaire** : `mention`, `emotion = neutre`.
- **Homonymes** : un prénom ou nom commun (« bertrand », « centre ») sans rapport avec la politique → `pertinent = non`.
- **Post incomplet ou coupé** : annote ce que tu lis. Si tu hésites, `doute`.
- **Langue** : si le post n'est pas en français, `non`, avec commentaire « langue ».

### 4.7 Point ouvert

« Je voterai X en serrant les dents » : `pour` (l'auteur annonce son vote) avec `commentaire: vote utile` ? À trancher avant le pilote.

## 5. Séquence d'annotation

| Étape | Qui | Contenu | Objectif | Temps par personne |
| --- | --- | --- | --- | --- |
| 1. Pilote | tous | `lot_00_pilote` (50 posts) | tout annoter, seul | 50 min |
| 2. Accord | un référent | script d'accord, liste des désaccords | voir « Objectifs chiffrés » | 15 min |
| 3. Révision | tous | réunion sur les désaccords, mise à jour de ce guide | une règle écrite par type de désaccord | 1 h |
| 4. Repilote (si seuils non atteints) | tous | `lot_01` (150 posts), seulement les 50 premiers | seuils atteints | 50 min |
| 5. Lots | répartis | `lot_01`, `lot_02`... (150 posts), un lot par personne | ≥ 600 posts annotés | 1 h par lot |
| 6. Jeu d'évaluation | 2 annotateurs | `lot_eval` (200 posts) | annoté deux fois, arbitré, figé | 1 h 40 + 1 h d'arbitrage en commun |
| 7. Export | un référent | `--freeze-eval` puis export | `train.jsonl` et `eval.jsonl` | 5 min |

Ordre conseillé : pilote, accord, révision, **puis** le jeu d'évaluation (annoté avec le guide révisé), puis les lots d'entraînement.

Total pour 3 annotateurs : environ 15 h de travail humain, soit 5 h chacun (pilote 3 × 50 min, révision 3 × 1 h, évaluation 2 × 100 min + 2 × 1 h d'arbitrage, 4 lots d'entraînement = 4 h). Compte 20 à 40 secondes par post une fois la main prise, 1 minute au début.

## 6. Objectifs chiffrés

Accord sur le pilote (kappa, voir « Pourquoi l'accord compte »). En dessous du seuil, on corrige le guide et on refait un pilote.

| Champ | Seuil de départ |
| --- | --- |
| `pertinent` | ≥ 0,70 |
| `cibles` (stance) | ≥ 0,60 |
| `emotion` | ≥ 0,50 |
| `themes` | ≥ 0,50 |
| `ironie` | ≥ 0,40 (l'ironie reste un sujet difficile, même pour des humains) |
| `regle_suffit` | ≥ 0,50 |

Autres objectifs :

- Jeu d'évaluation : 200 posts, deux annotations + arbitrage, jamais utilisé pour l'entraînement.
- Corpus d'entraînement : au moins 600 posts annotés, au moins 30 exemples par stance (`pour`, `contre`, `neutre`, `mention`). `neutre` sera rare : si tu atteins moins de 30, on le note dans le rapport, on ne force pas.
- Tu peux t'arrêter avant la fin d'un lot : les posts annotés restent utilisables.

## 7. Pourquoi l'accord compte (explication pour débutant)

Si deux personnes lisent le même post et donnent deux réponses, alors la « vérité » n'est pas claire. Un modèle ne peut pas apprendre une règle que ses humains ne suivent pas eux-mêmes. Mesurer l'accord, c'est mesurer la qualité du guide, pas la qualité des annotateurs.

**Accord brut** : part des cas où vous répondez pareil. Il trompe. Si 90 % des posts sont `mention`, deux personnes qui répondent au hasard `mention` ou `contre` s'accordent déjà souvent.

**Kappa** corrige cet effet : il retire l'accord dû au hasard.

- 1 : accord parfait.
- 0 : pas mieux que le hasard.
- Négatif : pire que le hasard.

Lecture usuelle : < 0,2 quasi nul, 0,2–0,4 faible, 0,4–0,6 moyen, 0,6–0,8 bon, > 0,8 très bon.

Deux variantes : **Cohen** pour deux annotateurs (ou une paire), **Fleiss** pour trois ou plus. Le script donne les deux. Un « n/a » signifie que tout le monde a toujours répondu la même chose : le kappa n'est pas défini.

Que faire d'un kappa bas ? Regarde la liste des désaccords, trouve ce qui revient (ironie ? négation ?), écris une règle dans « Cas difficiles », puis refais un pilote.

## 8. Pourquoi le jeu d'évaluation est figé

Imagine un élève qui s'entraîne sur les questions exactes de l'examen : il obtient 20/20 sans avoir compris. Un modèle fait pareil s'il voit les posts d'évaluation pendant l'entraînement. Son score est alors trop beau, et on ne sait plus ce qu'il vaut sur de nouveaux posts. C'est la **fuite de données**.

Nous séparons donc, une fois, un jeu d'évaluation (`lot_eval`) et nous le figeons : la liste des identifiants est enregistrée avec une empreinte. L'export refuse d'en faire sortir un post vers l'entraînement, et refuse de continuer si la liste a changé. On ne retouche pas ce jeu, même si une erreur d'annotation y apparaît ; on la note pour le rapport.

Le jeu est annoté par deux personnes puis arbitré, car il sert de « corrigé » : ses erreurs fausseraient toutes les mesures. Les choix arbitrés s'enregistrent sous le nom d'annotateur `consensus`. La liste est figée dans `eval_fige.json` : ne relance pas `annotation.prepare --force`, le jeu changerait.

Limite à connaître : le tirage donne autant de place à chaque entité, donc les petits candidats sont sur-représentés par rapport au flux réel. Les scores par entité sont fiables ; pour un taux global, il faudrait pondérer.

## 9. Silver et gold

| | Silver | Gold |
| --- | --- | --- |
| Qui | un LLM (12/10/2026) | un humain de l'équipe, avec l'outil |
| Où | `annotation/silver/final/` du dossier du corpus | `annotation/annotations/<prénom>.jsonl` |
| Volume | 2 978 posts, dont 2 725 utilisables pour l'entraînement | voir [`evaluation-modele.md`](evaluation-modele.md) |
| Valeur | bonne, mais pas vérité terrain | la référence |
| Usage | entraîner, pré-trier, repérer les cas durs | **évaluer**, arbitrer, corriger le guide |

Mesurer un modèle avec les étiquettes d'un LLM, c'est mesurer l'accord entre deux machines, pas la justesse. Seul le gold dit si le silver, le lexique ou un modèle se trompent.

Ce que le silver montre déjà (agrégats, corpus du 12/10) :

- 91 % des posts collectés sont pertinents ; la confiance du LLM est basse sur 19 %.
- Stances : 2 141 `contre`, 1 763 `mention`, 526 `pour`. Le RN, Le Pen et Bardella ne reçoivent presque aucun `pour` : Bluesky penche à gauche. La barre d'opinion hérite de ce biais (Livrable 1, R5).
- Ironie sur 22 % des posts pertinents ; une règle suffit sur 5 % seulement. Le modèle reste nécessaire ; le lexique sert à repérer cibles et thèmes.
- Points durs récurrents : réponses de fil sans contexte (« il », « elle »), ironie, hésitation `mention`/`contre` sur les titres d'articles.

Règles :

1. **Un résultat qui ne tient que sur du silver ne compte pas.** Toute mesure se fait sur du gold.
2. Le jeu d'évaluation figé est **100 % humain** (gold). Aucun silver dedans.
3. L'outil d'annotation **n'affiche jamais de silver** : le voir fausserait ton jugement (biais d'ancrage). Ne va pas le lire à côté, surtout pour `lot_00_pilote` et `lot_eval`.
4. Le silver sert à élargir l'entraînement. `export --silver` écrit un fichier séparé `train_silver.jsonl`, chaque ligne marquée `source: silver`, sans aucun post du pilote, de l'évaluation ni gold.

## 10. Confidentialité

Le corpus est stocké sans identifiant d'auteur et effacé à la fin de l'entraînement, **30 jours au plus** après la collecte de chaque post (régime « corpus de développement » du Livrable 1, mesure M11, confirmée en v1.3). Les lots et annotations restent dans le dossier du corpus, hors dépôt Git. Ce guide ne cite aucun post réel.
