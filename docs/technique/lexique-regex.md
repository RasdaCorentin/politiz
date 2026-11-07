# Lexique et regex : ce qu'une règle décide sans modèle

*Document technique, sujet 1 (suivi des sentiments, présidentielle 2027). Bibliothèque :
[`ressources/lexique/`](../../ressources/lexique/README.md). Analyse reproductible :
[`scripts/analyse_lexique.py`](../../scripts/analyse_lexique.py). Tests : `tests/test_analyse_lexique.py`.
Aucun post réel n'est cité ici (mesure M9 du Livrable 1) : les exemples sont inventés.*

## 1. En bref

- Une règle (regex) **reconnaît une forme**, pas une intention. Elle est sûre quand la forme est sans équivoque.
- Sur le corpus du 2026-10-12 (3151 posts), les règles de confiance haute décident la **stance** de **3 %** des posts
  (93 posts sur 3151). Elles repèrent un **thème** dans 41 % des posts, et une **entité** dans 88 %.
- La précision des règles de stance haute est d'environ **90 %** sur les hits relus (67 relus, 63 bons ; échantillon petit).
- Les règles servent donc à **trois choses** : repérer la cible, donner un thème, trancher les cas explicites.
  Tout le reste va au modèle.
- Les alias courts de `keywords.txt` posent un vrai problème de bruit (`lr`, `bertrand`, `modem`, `en marche`) : voir « Suggestions pour `keywords.txt` ».

## 2. Méthode

Le script `analyse_lexique.py` lit le corpus en lecture seule et n'écrit que des **agrégats** (termes, comptes, taux).

1. **Normalisation** : minuscules, accents retirés, comme `normalize()` de `ingestion.py`. Un test vérifie l'identité des deux fonctions.
2. **Nettoyage** : URLs retirées. `@handles` retirés avant de chercher une entité (voir « Couverture et faux positifs »).
3. **Comptage en nombre de posts** (pas en occurrences) : un mot répété dans un post compte une fois.
   Mots vides exclus ; un bigramme ou trigramme ne commence ni ne finit par un mot vide.
4. **Familles relevées** : unigrammes, bigrammes, trigrammes, hashtags, émojis, formes dérivées des noms propres
   (`macronie`, `melenchoniste`…), co-occurrences entité × terme (comptes et *lift*).
5. **Couverture des alias** de `#identites` : posts où l'alias apparaît, posts où il est le seul alias, posts où il n'apparaît que dans un `@handle`.
6. **Relecture manuelle** : pour les alias douteux, je lis un échantillon aléatoire avec le contexte du terme
   (sans le recopier) et je compte les faux positifs. Les nombres « lus » ci-dessous viennent de là.
7. **Évaluation des règles** : section `regles` du script (déclenchements, couverture, conflits).

Commande :

```bash
uv run --with pyyaml python scripts/analyse_lexique.py --db CHEMIN/bluesky_posts-20261012.db --json /tmp/agregats.json
uv run --with pyyaml python scripts/analyse_lexique.py --db CHEMIN/... --sections regles --dedoublonner
```

### Ce que le corpus est (et n'est pas)

- 3144 posts sur 3151 datent du **même jour** (2026-10-12), au lendemain d'une primaire de la gauche.
  Les fréquences reflètent cet événement, pas la campagne entière.
- Le corpus ne contient que les posts **gardés** par le filtre. Il ne dit rien des posts rejetés :
  on mesure les faux positifs des alias gardés, pas le rappel perdu.
- **Robots** : 11 gabarits répétés (au moins 5 posts identiques à 8 mots près) pèsent 113 posts (3,6 %) : tendances de mots,
  dépêches climat, sondages automatiques, annonces d'avions. Ils gonflent les n-grammes. L'option `--dedoublonner` les ramène à un exemplaire.
- Quelques posts sont rédigés en anglais ou en catalan malgré la langue déclarée `fr`.

## 3. Termes essentiels relevés

Fréquences en nombre de posts (sur 3151).

**Entités et variantes**

| Terme | Posts | Remarque |
| --- | --- | --- |
| `glucksmann` | 745 | + typos `glucksman` (42), `gluksmann` (10) absentes de `keywords.txt` |
| `lfi` | 683 | alias le plus sûr |
| `melenchon` | 541 | + `meluche` (32), `jlm` (161) |
| `rn` | 348 | + `le pen` (166), `mlp` (41) |
| `ps` | 235 | **absent de `keywords.txt`** |
| `raphael` | 218 | prénom seul, très lié à Glucksmann dans ce corpus |
| `macron` | 117 | non candidat, mais très cité |

**Formes dérivées** (nombre de posts)

- Macron : `macroniste` (39), `macronistes` (38), `macronie` (18), `macronisme` (11), `macronard` (1+).
- Mélenchon : `melenchoniste`, `melenchonzouze`, `merduchion` (3, hashtag).
- Glucksmann : `gluglu` (29 : surnom moqueur), `glucksy`, `glucksmanise`.
- Le Pen : `lepen` (21), `lepeniste` (1).
- Insultes de camp : `facho(s)` (18), `fasciste(s)` (32), `droitard(s)` (12), `collabo(s)` (8), `extreme centre` (7).

**Bigrammes et trigrammes utiles** : `second tour` (96), `premier tour` (57), `extreme droite` (45), `parti socialiste` (35),
`place publique` (29), `intentions de vote` (11), `face au rn` (11), `remporte la primaire` (12), `alliance avec lfi` (11), `rassembler la gauche` (10).

**Hashtags** : `#lfi` (33), `#glucksmann` (32), `#rn` (20), `#melenchon` (11), `#ps` (8). Les hashtags de **rejet** sont rares mais sûrs
(`#plusjamaisps`). Les hashtags de soutien (`#melenchon2027`, `#jlm2027`) existent mais sont peu fréquents (moins de 10).

**Émojis** : 501 posts contiennent au moins un émoji. Les plus fréquents sont décoratifs ou issus de robots (flèches, drapeaux).
Les utiles : `🤡` (21, moquerie), `😂🤣` (37, rire souvent sarcastique), `🤮` (8, dégoût), `🤬😡` (7, colère).

**Thèmes dominants** : campagne-sondages (primaire, tour, sondage : 782 posts avec un terme de confiance haute), europe-international
(Ukraine, Poutine, Trump : 244), ecologie (121), economie (102), institutions (91), sante-education (63).
`immigration` (9) et `social-retraites` (27) sont presque absents : le débat porte sur la stratégie de la gauche, pas sur les programmes.

**Co-occurrences** : `glucksmann` + `primaire`/`victoire` (171 / 98 posts) ; `melenchon` + `tour`/`second` ; `le pen` + `tour`/`face` ;
`rn` + `racisme`/`antisemitisme`. Les termes distinctifs de `glucksmann` sont pollués par un robot de tendances : lancer avec `--dedoublonner`.

### 15-20 termes les plus utiles pour du regex

1. alias d'entité non ambigus : `glucksmann`, `lfi`, `melenchon`, `rn`, `bardella`, `attal`, `retailleau`
2. `votez` / `je voterai` / `je vote` + entité (soutien)
3. `ne voterai pas` / `jamais voter` + entité (rejet)
4. `pas une voix pour` + entité
5. `degage(ons)` + entité
6. `gluglu` (rejet de Glucksmann)
7. `merduchion` (rejet de Mélenchon)
8. `macronard`, `macronie` (rejet de la macronie)
9. `droitard`, `facho`, `extreme centre` (insultes de camp)
10. `islamo-gauchiste`
11. `#plusjamais…`, `#stop…` (hashtags de rejet)
12. `(rn) 35 %` : format de sondage (stance mention)
13. `second tour`, `premier tour`, `sondage`, `primaire` (thème campagne)
14. `retraite(s)`, `budget`, `dette`, `49.3` (thèmes)
15. `ukraine`, `poutine` (thème international)
16. `🤮`, `🤬` (émotion)
17. `anti-` + entité (signal de polarisation, stance ambiguë)
18. `meluche` (signal de polarisation, stance ambiguë)

## 4. Ce que la bibliothèque contient

| Fichier | Contenu | Taille |
| --- | --- | --- |
| `entites.yaml` | 68 entités (candidats, partis), 107 alias dont les alias de `keywords.txt` et 28 alias ajoutés | `camp` et `nom` renseignés ([`camps-candidats.md`](camps-candidats.md)) |
| `stance.yaml` | 35 règles : soutien, rejet, surnoms, disqualifiants, sondages (mention) | 30 règles se déclenchent sur le corpus |
| `themes.yaml` | 9 thèmes, 2 ou 3 niveaux de confiance par thème | |
| `emotions.yaml` | 3 émotions, 7 marqueurs | volontairement court |

- **Identifiants** : le nom canonique d'une entité est le premier alias de `keywords.txt` (`melenchon`, `le pen`, `rassemblement national`),
  pour rester aligné sur l'outil d'annotation. Personne et parti restent distincts (`le pen` ≠ `rassemblement national`).
- **Camp** : rattachement de la personne publique d'après sa formation actuelle ; `null` faute de
  source solide. Règle, sources et cas litigieux : [`camps-candidats.md`](camps-candidats.md).
- **Émotions** : je n'ai gardé que des émojis et trois mots. Les mots d'émotion (« peur », « honte », « bravo ») servent presque toujours
  d'argument politique ou d'ironie, pas à exprimer ce que ressent l'auteur. Aucun marqueur fiable pour la peur, la tristesse, la surprise.
  `neutre` n'a pas de marqueur : l'absence d'émotion ne se prouve pas par une regex.
- **Stances** : `pour`, `contre`, `neutre`, `mention`, `ambigu`. `mention` = cité sans jugement (fait, agenda, sondage) ;
  `neutre` est réservé au jugement équilibré, qu'aucune regex ne prouve. Refuser son soutien (« je ne voterai pas X »,
  « je ne soutiens pas X ») est `contre` : règles `rejet-jamais-voter` et `rejet-ne-soutiens-pas`.
- **Cibles** : une entité de `entites.yaml`, `gouvernement`, `groupe-politique` (« la gauche », « les macronistes ») ou `autre`.
  Les règles de camp visent `groupe-politique`.
- **Thème `autre`** : résiduel, sans terme.

## 5. Ce que les règles peuvent décider seules, et ce qu'elles ne peuvent pas

### Elles décident seules

- **Qui est cité** : un alias non ambigu (`lfi`, `glucksmann`, `bardella`…) désigne l'entité. Fiable à plus de 95 % après retrait des `@handles`.
- **Le sujet** (thème) quand le terme est spécifique (`retraites`, `ukraine`, `second tour`). Précision lue : environ 75 à 85 % pour la confiance haute.
- **Le format** : un sondage publié automatiquement (`Nom (parti) : 35 %`) est une `mention` : cité sans jugement. 12 posts sur 12 lus.
- **Le slogan sans ambiguïté** : `#plusjamaisps`, `gluglu`, `droitard`, `je ne voterai pas X`, `dégageons X`.
- **L'émotion portée par un émoji net** : `🤮`, `🤬`.

### Elles ne peuvent pas décider

| Piège | Pourquoi la règle échoue | Exemple inventé |
| --- | --- | --- |
| **Négation** | le motif voit le verbe, pas le sens global | « je ne voterai jamais pas pour X, c'est faux de dire ça » |
| **Double négation** | idem | « il est faux que je ne voterai pas X » |
| **Ironie** | la forme est celle du soutien | « Votez Hollande, ça a si bien marché la dernière fois » |
| **Sarcasme** | `bravo` suivi d'une moquerie | « Bravo le PS, encore un chef-d'œuvre » |
| **Citation d'un adversaire** | l'auteur rapporte la phrase d'un autre | « Il répète que personne ne devrait voter X » |
| **Plusieurs cibles** | seul le premier nom est capturé | « Jamais je ne voterai A, B ou C » |
| **Surnom à double sens** | `meluche` est dit par les soutiens et par les adversaires | stance ambiguë dans la bibliothèque |
| **Étiquette retournée** | `facho` vise tantôt l'extrême droite, tantôt la gauche | « fachos rouges » |
| **Position de l'auteur** | `anti-X` décrit quelqu'un d'autre | « sa ligne anti-X lui a réussi » : l'auteur n'a pas pris position |
| **Condition** | « je voterai X si Y » est un pour conditionnel | stance `pour`, intensité faible |
| **Pour qui parle le post ?** | le corpus n'a pas d'auteur : on ne sait pas qui parle | |

Sur le corpus, la lecture donne les erreurs suivantes : un « je voterai X » rapporté entre guillemets (corrigé par une garde sur les guillemets),
une règle « tout sauf X » qui décrit la stratégie d'un tiers, un slogan « pas une voix pour X » cité, et `gauchiste` employé pour se qualifier soi-même.

**Une règle donne un indice, jamais l'attitude réelle de l'auteur.** C'est une règle de prudence : la confiance « haute » dit que la forme est
nette, pas que l'auteur le pense.

## 6. Couverture et faux positifs

Corpus : 3151 posts. Mesures sur la bibliothèque actuelle.

| Part des posts où... | Posts | % |
| --- | ---: | ---: |
| une entité est reconnue (tout alias, hors `@handles`) | 2762 | 87,7 |
| une entité non ambiguë est reconnue | 2673 | 84,8 |
| une règle de stance se déclenche (toute confiance) | 245 | 7,8 |
| **une règle de stance de confiance haute se déclenche** | **80** | **2,5** |
| **stance ou émotion de confiance haute** | **93** | **3,0** |
| un thème de confiance haute est reconnu | 1296 | 41,1 |
| au moins une règle haute (stance, thème ou émotion) | 1353 | 42,9 |
| stance haute **et** thème haut (décision riche) | 33 | 1,0 |

Après dédoublonnage des robots : la couverture de stance haute reste à 2,5 % (75 posts sur 3049). Les robots n'y changent rien.

Répartition des 80 posts de stance haute : 58 contre, 12 pour, 12 mention (sondages). Un conflit (pour et contre sur le même post) : 1 post.

**Lecture** : environ 3 % des posts sont décidés par une règle de confiance haute. Les 97 % restants demandent un modèle. Le gain d'un étage « règles »
n'est pas le débit : c'est la **précision sur le cas explicite** et la **cible** (qui est visé), que le modèle de sentiment seul ne donne pas.

### Faux positifs

- **Règles de stance haute** : 63 bons sur 67 hits relus (94 %). Intervalle plausible : 85 à 98 %. Les erreurs : surnom repris dans un robot de tendances,
  négation d'un surnom, guillemets.
- **Règles moyennes et basses** : `macronie` 8/12, `gourou` 7/10, `facho` 15/18, `fasciste` 6/12, `gauchiste` 2/5. Ne pas les laisser décider.
- **Hashtags 2027** : 4 sur 5 sont des soutiens. Les posts hostiles reprennent le hashtag adverse.

### Alias de `#identites` : faux positifs relus

Échantillon aléatoire, lecture du contexte. « Seul » = posts où l'alias est le seul alias d'identité (gardés grâce à lui).

| Alias | Posts | Seul | Lus | Faux positifs | Taux | Cause |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `rn` | 358 | 224 | 25 | 0 | 0 % | |
| `jlm` | 161 | 101 | 25 | 0 | 0 % | |
| `lfi` | 705 | 410 | 25 | 0 | 0 % | 16 posts via `@handle` seulement |
| `udr` | 12 | 2 | 12 | 0 | 0 % | |
| `npa` | 38 | 18 | 14 | 0 | 0 % | |
| `eelv` | 35 | 12 | 16 | 0 | 0 % | |
| `pcf` | 31 | 11 | 16 | 0 | 0 % (+ 6 via `@handle`) | |
| `roussel` | 21 | 12 | 14 | 0 | 0 % (+ 6 via `@handle`) | |
| `le pen` | 166 | 67 | 14 | 2 | 14 % | autre membre de la famille, ou sens culinaire |
| `attal` | 178 | 117 | 14 | 0 | 0 %, mais **43 % via `@handle`** (76 posts) | robots qui taguent le compte |
| `centre` (orientation) | 113 | n/a | 30 | 7 | 23 % | « centre de gravité », « centre-ville », « centré sur » |
| `hidalgo` | 19 | 13 | 19 | 4 | 21 % | homonymes espagnols et mexicains |
| `valls` | 16 | 9 | 16 | 3 | 19 % | ville catalane |
| `lr` | 34 | 12 | 25 | 8 | **32 %** | code d'avion, calibre, domaine `.lr`, université |
| `modem` | 7 | 5 | 7 | 3 | **43 %** | modem Wi-Fi |
| `en marche` | 7 | 6 | 7 | 3 | **43 %** | expression courante |
| `bertrand` | 7 | 7 | 7 | 6 | **86 %** | prénom ou nom d'autres personnes |
| `maurel` | 2 | 1 | 2 | 1 | 50 % | patronyme |

Hors `keywords.txt`, lu sur 16 posts : `ps` (243 posts) n'a eu aucun faux positif. Ce chiffre est **biaisé à la baisse** : le corpus est déjà filtré par le contexte
politique. Dans le flux brut, `ps` signifiera aussi « post-scriptum » ou PlayStation.

Les nombres de posts « lus » sont petits : lire les taux comme des ordres de grandeur, pas comme des mesures précises.

**Alias jamais vus** (18 sur 80) : `bruno le maire`, `braun-pivet`, `dupont aignan`, `thouy`, `lassalle`, `aliot`, `knafo`, `pradie`, `brossat`, `tibo inshape`,
`france insoumise`, `parti communiste`, `debout la france`, `nouvelle energie`, `nous france`, `mouvement democrate`, `nouveau parti anticapitaliste`, `lutte ouvriere`.
Le corpus n'a qu'un jour : ne rien retirer sur ce seul critère (sauf bruit, voir « Suggestions pour `keywords.txt` »).

## 7. Suggestions pour `keywords.txt`

*Je ne modifie pas `src/ingestion/`.* Les chiffres viennent du corpus du 2026-10-12.

### À ajouter

| Alias | Posts | Dont sans autre alias d'identité | Raison |
| --- | ---: | ---: | --- |
| `ps` | 243 | 32 | premier parti cité après LFI/RN, absent. **Risque de bruit** : post-scriptum, PlayStation. Le mettre en `#identites` demande un essai sur le flux brut ; à défaut, le mettre en `#orientations` (exige du jargon) |
| `mlp` | 41 | 2 | sigle courant de Marine Le Pen |
| `glucksman` | 42 | 5 | faute fréquente |
| `gluksmann` | 10 | 0 | faute |
| `macroniste`, `macronie` | 39 / 18 | 7 / 2 | camp très cité (non candidat) : à placer en `#jargon` ou `#orientations`, pas en `#identites` |
| `nfp`, `nupes` | 24 / 10 | 5 / 1 | coalitions citées |
| `primaire` | 233 | 14 | `#jargon` : mot central de ce corpus (la primaire ne garde pas seule) |
| `insoumis`, `insoumise` | 15 / 18 | 0 | déjà couverts par `lfi` dans la plupart des posts |

Un alias sans autre alias d'identité est un post qui n'est gardé que par orientation + jargon. Ce chiffre est une **borne basse** du rappel gagné :
les posts rejetés n'apparaissent pas dans le corpus.

### À retirer ou à restreindre

| Alias | Faux positifs lus | Posts concernés | Proposition |
| --- | ---: | ---: | --- |
| `bertrand` | 6 sur 7 | 7 | remplacer par `xavier bertrand` |
| `lr` | 8 sur 25 | 34 (12 seuls) | garder `les republicains` ; `lr` seul : le passer en `#orientations` (jargon requis) |
| `modem` | 3 sur 7 | 7 | passer en `#orientations` ou le garder avec `mouvement democrate` seul |
| `en marche` | 3 sur 7 | 7 | garder `lrem` et `renaissance` (à ajouter), retirer `en marche` seul |
| `nouvelle energie`, `nous france` | non observés | 0 | termes courants (énergie renouvelable) : à retirer, risque de bruit élevé |
| `hidalgo`, `valls` | 4/19, 3/16 | 35 | garder : les vrais usages l'emportent (environ 80 %) ; sinon exiger le prénom |
| `centre` | 7 sur 30 | 113 | déjà en `#orientations` : correct, car le jargon est exigé |

### Filtre : retirer les `@handles` avant de chercher les mots-clés

Dans le corpus, **102 posts** (3,6 % des gardés) ne contiennent un alias que dans un `@handle`, surtout des robots :
76 posts avec `attal`, 16 avec `lfi`, 6 avec `pcf`, 6 avec `roussel`. L'ingestion les garde à tort.
Proposition : appliquer `re.sub(r"@[\w.\-]+", " ", norm)` avant `KeywordFilter.test`. Le script le fait déjà pour l'évaluation (`strip_mentions`).

### Autres propositions

- Ajouter une **liste de gabarits de robots** à rejeter (tendances de mots, dépêches climat, sondages automatiques) : 3,6 % du corpus, sans valeur d'opinion.
- Garder l'ordre des 3 classes : le test de l'ingestion n'a pas besoin d'autre changement.

## 8. Articulation règles → modèle (cible)

Cette cascade est une cible. Le job actuel applique une version plus simple : les règles fixent
les cibles, les thèmes et le filtre fin ; les modèles CamemBERT, s'ils sont activés, décident seuls
de la stance et de l'émotion ([`contrats-poc.md`](contrats-poc.md), scoreurs provisoire et à modèles du contrat). L'arbitrage et la
relecture humaine (étape 4) ne sont pas implémentés.

```
post normalisé
  │
  ├─ 0. nettoyage : retrait des @handles, détection des gabarits de robots → rejet ou étiquette « bot »
  │
  ├─ 1. ENTITES : alias non ambigus → cibles candidates
  │      alias ambigu seul (lr, bertrand, modem…) → pas de cible, on passe la main
  │
  ├─ 2. REGLES haute confiance
  │      ├─ stance explicite + cible résolue + aucun piège repéré → la règle DÉCIDE (étiquette + « source = règle »)
  │      ├─ sondage / format automatique → mention, la règle DÉCIDE
  │      └─ sinon → passe la main, avec les indices ci-dessous
  │
  ├─ 3. MODELE (sentiment, émotions, thèmes, stance sur les cibles proposées)
  │      reçoit : cibles candidates, thèmes de règles, marqueurs trouvés (confiance moyenne/basse)
  │
  └─ 4. ARBITRAGE : la règle de confiance haute l'emporte seulement si le modèle ne la contredit pas
         fortement ; sinon le post part en relecture humaine
```

**Quand la règle décide** : forme sans équivoque (hashtag de rejet, surnom péjoratif, « je ne voterai pas X »), cible nommée, aucun
signe de citation, d'ironie ou de pluriel. Environ 3 % des posts.

**Quand elle passe la main** (le cas courant) :
- confiance moyenne ou basse (`macronie`, `facho`, `anti-X`, `meluche`) : l'indice est transmis au modèle comme variable d'entrée ;
- alias ambigu ou plusieurs entités avec règle de stance ;
- conflit entre règles (pour et contre) ;
- guillemets, point d'interrogation, mot d'ironie (« évidemment », « sûrement ») dans la phrase.

**Ce qu'on garde des règles même quand le modèle décide** : les **cibles** et les **thèmes** (couverture 88 % et 41 %) servent de pré-remplissage
de l'annotation, et de filtre du flux (un post sans entité n'entre pas dans les agrégats par candidat).

**Évolution à prévoir** : mesurer sur un jeu annoté à la main la précision réelle de chaque règle de confiance haute ; retirer les règles sous 90 %.
Le champ `precision_lue` n'est qu'une première estimation sur 5 à 30 posts par règle.

## 9. Limites de l'étude

- Un seul jour, un seul événement : les fréquences de thèmes et de surnoms ne se transposent pas aux autres semaines.
- Échantillons de relecture petits (quelques dizaines de posts par règle) : les taux sont des ordres de grandeur.
- La précision est relative au sens que j'ai donné à chaque hit : l'attitude réelle de l'auteur n'est pas connue, d'autant que le corpus n'a pas d'auteur.
- Le rappel des règles n'est pas mesuré : il faut un jeu annoté (outil d'annotation) pour le faire.
