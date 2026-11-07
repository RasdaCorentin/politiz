# DESIGN.md — contrat de design du dashboard

> Instance du contrat de design du gabarit `template-monitoring-viewpage` (`DESIGN.md`, partie A :
> méthode générale ; partie B : instance pour la page React, état présent). Ce fichier se lit avant toute
> modification de l'interface. Une décision visuelle nouvelle s'y ajoute dans le même commit que
> le code. Chaque règle a sa raison : sans la raison, pas de règle.

## 1. Méthode appliquée (partie A)

1. **Tâche d'abord, pixels ensuite.** Tout élément visible sert la tâche du lecteur (voir « Tâche du lecteur »). Le reste
   disparaît.
2. **Deux passes.** Ce plan est écrit et commité avant le code. Le rendu est ensuite regardé
   (capture, relecture, correction), pas seulement le code.
3. **Jetons.** Toute valeur visuelle est une variable CSS de `style.css`. Le thème sombre redéfinit
   les jetons, jamais les règles. Il est dessiné, pas inversé : surfaces bleutées, teintes
   revalidées sur la surface sombre.
4. **Texte.** Hiérarchie par la taille et la graisse (400 contre 650). Typographie française :
   espace insécable avant `:`, `%` et dans `« »`, espace fine insécable pour les milliers, virgule
   décimale, vrai signe moins (U+2212). Un terme par concept dans toute l'interface.
5. **Contenu tiers = texte.** Tout libellé issu de ClickHouse ou de `entites.yaml` passe par
   `html.escape` avant d'entrer dans le HTML. Aucun contenu tiers n'est injecté tel quel.
6. **Forme avant couleur.** Ordre : forme, rôle de couleur, validation par le calcul, marques,
   interaction, accessibilité, rendu regardé. Une valeur seule s'affiche en tuile, pas en graphique.
   Une courbe exige au moins 7 points. Le jeu de données reste lisible sans survol (valeurs
   écrites ; un tableau accompagne chaque graphique).
7. **États.** Chargement, vide, peu de données, erreur et données périmées sont dessinés.
8. **Mouvement.** À l'arrivée sur une page, les données entrent une fois : les bulles grossissent
   depuis leur centre dans l'ordre des rangs (650 ms, 70 ms d'écart), leurs libellés suivent, les barres
   partent de zéro (600 ms). L'œil suit l'ordre de lecture voulu, du plus grand au plus petit. Au
   rafraîchissement, une valeur qui change passe à sa nouvelle position en transition courte (environ
   400 ms, ease-out). Aucun mouvement continu : une bulle qui flotte ne dit rien et gêne la lecture des
   valeurs. `prefers-reduced-motion` coupe tout.
9. **Accessibilité.** Clavier complet, focus visible (double anneau), texte >= 4,5:1, marques
   >= 3:1 (sinon libellé visible et tableau), cibles >= 24 px (44 px sur mobile), lecture à 390 px.
10. **L'URL porte l'état** : `vue` (`contraste`, `popularite`, `top3`, `evenement` ; défaut `contraste`),
    `periode` (`24h|7j|30j|tout` ; défaut `7j`) ou `debut` et `fin` (`AAAA-MM-JJ`, pour une plage),
    `seuil=N` (plage et seuil : URL seulement, aucun contrôle à l'écran), `cible` (`candidats`, défaut, ou `partis`). La page événement ajoute `ev_id`
    (fait du catalogue), `ev_libelle`, `ev_date` (jour J) et `ev_heure` (facultative). Ces paramètres
    n'existent que sur la page événement.

## 2. Tâche du lecteur

Voir en cinq secondes comment évolue la discussion sur la présidentielle 2027 (ton, émotions, cote
des candidats, équilibre gauche/droite) et jusqu'où ces chiffres sont fiables.

## 3. Direction esthétique : l'instrument gradué

**Source :** le sujet mesure l'opinion. Son vocabulaire est celui de l'instrument : baromètre,
cote, indice, curseur, échelle, marge d'erreur. Un instrument affiche toujours son échelle, son
unité et sa précision. Chaque indicateur de la page porte donc trois choses : sa valeur sur une
échelle lisible, le nombre de posts évalués derrière elle, et la couverture du scoreur.

**Signature visuelle.**

- La barre d'opinion est une règle graduée avec un curseur, une marge d'erreur et un curseur
  fantôme (période précédente).
- Une zone hors mesure est **hachurée** : l'instrument se tait quand les posts évalués manquent.
- **La couleur est réservée à la donnée.** L'interface est faite d'un papier froid, d'une encre
  bleu nuit et de gris teintés. Le rouge, le gris et le bleu désignent le **camp**. La sarcelle et
  l'ocre désignent le **ton** (positif, négatif). Aucune teinte d'accent n'existe dans le
  chrome : le bouton actif est en encre pleine, le focus est un double anneau d'encre.
- Police : IBM Plex Sans (chiffres soignés, licence OFL), graisses 400 et 650.

**Écarté.**

| Piste | Raison |
|---|---|
| Habillage « soirée électorale » (tricolore plein cadre, hémicycle, camemberts) | Évoque une projection de résultats ou un sondage (risque R5 du Livrable 1). |
| Console de supervision sombre à néons | Registre de l'exploitation, étranger au sujet. |
| Infographie de presse (serif, filets, colonnes) | Signatures IA 1 et 3 ; rien n'y mesure l'incertitude. |
| Jauge circulaire pour la barre | Une échelle droite se lit mieux et porte la marge d'erreur. |
| Accent bleu dans l'interface | Le bleu désigne la droite : il ne peut pas servir au chrome. |

**Les cinq signatures « IA » évitées.**

1. *Fond crème, titres serif, accent terracotta* : fond gris-bleu froid, une seule famille sans
   empattement, aucune teinte chaude de fond.
2. *Fond sombre et vert acide* : le thème sombre est bleuté ; la sarcelle est désaturée et validée.
3. *Mise en page de journal à filets* : aucun filet entre sections. L'espace et la taille des
   titres séparent. Les seuls traits sont des graduations de donnée.
4. *Kit de cartes SaaS uniformes* : trois formes distinctes. La barre est le seul panneau surélevé
   (l'instrument) ; le classement est une liste ouverte ; les tuiles de la page contraste sont des
   blocs typographiques sans cadre.
5. *Chrome de gabarit* (petites capitales espacées, points médians, chiffres en monospace) :
   libellés en casse normale, séparateurs rares, chiffres proportionnels (tabulaires seulement
   dans les colonnes alignées), aucune police à chasse fixe.

## 4. Jetons

Définis dans `style.css`. Surfaces et encres :

| Rôle | Clair | Sombre |
|---|---|---|
| `--bg` / `--surface` / `--surface-2` | `#f2f4f8` / `#ffffff` / `#e8ecf2` | `#0f131a` / `#171c26` / `#1f2531` |
| `--text` / `--text-2` / `--muted` | `#121a2b` / `#39445a` / `#586378` | `#e8ecf4` / `#c2c9d6` / `#98a2b4` |
| `--border` / `--grid` / `--axis` | `#d5dbe5` / `#e3e7ee` / `#b9c1ce` | `#2a3140` / `#232a37` / `#3a4354` |
| `--data` / `--data-soft` (données sans identité) | `#44506a` / `#aab4c6` | `#9fb0cc` / `#475269` |

Statuts de fraîcheur (échelle fixe, identique dans les deux thèmes, toujours avec icône et
libellé) : `ok #0ca30c`, `warn #fab219`, `critical #d03b3b`, `unknown #8a93a3`. La couleur teinte
le point et l'icône, jamais le texte. Le rouge « critique » ressemble au rouge du camp
`gauche` : les deux ne se touchent jamais (l'un est dans l'en-tête, l'autre dans les graphiques)
et le statut porte toujours son icône et son libellé.

## 5. Couleurs des données (validées par le calcul)

Commande : `python3 src/dashboard/web/outils/valider_palette.py` (lit `web/src/style.css`, clair et sombre).
Méthode du skill `dataviz` : contraste WCAG, bande de clarté OKLCH, plancher de chroma,
séparation en vision normale (ΔE OKLab x 100 >= 15) et sous daltonisme (Machado 2009,
sévérité 1,0, protanopie et deutéranopie, ΔE >= 8 cible, >= 6 plancher). Le script reproduit les
chiffres du validateur JS du skill (`validate_palette.js`) sur la palette de référence et sur
chaque paire ci-dessous.

| Jeton | Rôle | Clair | Contraste | Sombre | Contraste |
|---|---|---|---|---|---|
| `--camp-gauche` | camp gauche (rouge) | `#c8323c` | 5,28:1 | `#e15a62` | 4,75:1 |
| `--camp-centre` | camp centre (gris) | `#858d9c` | 3,34:1 | `#aab3c2` | 8,07:1 |
| `--camp-droite` | camp droite (bleu) | `#2f63c4` | 5,67:1 | `#5a8de6` | 5,19:1 |
| `--ton-positif` | ton positif (sarcelle) | `#0e8c7c` | 4,15:1 | `#25a692` | 5,65:1 |
| `--ton-negatif` | ton négatif (ocre) | `#b8680a` | 4,18:1 | `#d6791a` | 5,37:1 |
| `--ton-neutre` | ton neutre (gris) | `#b4bbc8` | 1,93:1 | `#606a7e` | 3,14:1 |

| Paire (voisines à l'écran) | ΔE normal clair / sombre | ΔE daltonisme clair / sombre |
|---|---|---|
| gauche et droite | 30,5 / 27,0 | 21,5 / 19,9 |
| gauche et centre | 21,8 / 21,8 | 13,2 / 14,2 |
| centre et droite | 18,5 / 16,7 | 16,8 / 14,9 |
| positif et négatif | 20,8 / 22,8 | 12,0 / 13,8 |
| positif et neutre | 23,8 / 17,2 | 18,7 / 13,4 |
| négatif et neutre | 24,9 / 23,1 | 23,2 / 17,7 |

Résultat : 0 échec. Une alerte subsiste : `--ton-neutre` en clair (1,93:1, sous 3:1). Elle est
couverte par la règle de relève : chaque segment neutre porte un libellé visible et le tableau
accompagne le graphique.

**Libellé du neutre** (à valider). Dans les légendes : « Neutre ». Pour la barre séparée de la
page contraste : « Neutre (ni positif ni négatif) », qui dit ce que le mot seul ne dit pas.

Les teintes rouge/bleu (camp) et sarcelle/ocre (ton) ne se touchent jamais : le ton n'apparaît
que dans la page contraste, le camp que dans la barre et le classement. Les croisements (information)
sont les moins bons de la page : gauche contre ocre, 12,3 de ΔE normal et 5,5 sous daltonisme en
clair. Ils justifient cette séparation. Le gris neutre du ton est plus clair que le gris du camp,
car il touche deux teintes à la fois.

**Règle de couleur.** La couleur suit l'entité : un candidat porte la couleur de son camp partout
(classement, courbes). Un candidat non classé porte l'encre `--data` et un motif haché, jamais un
gris de camp. Le camp et le ton ne se mélangent dans aucun objet.

## 6. Graphiques : une question, une forme

| Lecture | Question | Forme | Pourquoi |
|---|---|---|---|
| Barre d'opinion | Les avis sur les candidats de droite sont-ils meilleurs ou moins bons que ceux de gauche, et de combien ? | Règle graduée, curseur, marge d'erreur, curseur fantôme | Une position sur une échelle commune est le canal le plus exact ; la marge montre l'instabilité ; le fantôme montre le déplacement. |
| Classement | Qui est le mieux jugé ? | Barres divergentes autour de zéro, triées, couleur du camp, valeur au bout | Comparaison de grandeurs signées ; le sens de la barre porte le signe, pas la couleur seule. |
| Courbes par candidat | Comment l'indice de chacun a-t-il évolué ? | Petits multiples, échelle commune de −1 à +1, courbe cumulée | Un candidat par courbe : pas de huit teintes à distinguer, et pas de conflit avec le rouge et le bleu des camps. |
| Ton | Quel est le ton dominant ? | Jauge positif contre négatif sur les posts polarisés ; neutre dans une barre à part | Le neutre n'est ni positif ni négatif : une jauge à deux pôles le sortirait de la comparaison. |
| Ton dans le temps | Le ton se dégrade-t-il ? Quand sont les pics ? | Colonnes empilées par tranche jusqu'à 60 tranches ; au-delà, surface empilée de même donnée | La hauteur porte le volume, les segments la composition. Les colonnes deviennent illisibles sous un pixel par tranche. |
| Émotions | Quelle émotion domine ? | Barres horizontales triées, une seule couleur, valeur au bout | Catégories nominales : une teinte, la longueur porte la valeur. |
| Thèmes | De quoi parle-t-on ? | Barres horizontales triées | Idem. Un post compte dans chacun de ses thèmes. |
| Thèmes du top 3 | De quoi parle chaque entité du top 3 ? | Bulles : surface proportionnelle aux posts (rayon en √posts), au plus 9 bulles, « autre » en dernier, libellé et valeur écrits à côté | Demande explicite de la page. L'aire se lit moins bien que la position : les valeurs sont écrites, et le tableau donne tous les thèmes. |
| Volume | Le flux est-il normal ? | Tuile avec petite courbe de volume | Une valeur, son contexte. |
| Fraîcheur, latence | Les chiffres sont-ils à jour ? | Tuiles avec icône et libellé | Un état, pas une série. |

Les émotions du top 3 se lisent en occurrences (barres triées), avec un tableau par entité. Au
rafraîchissement, une bulle change de taille ou de place en 400 ms (ease-out) ; `prefers-reduced-motion`
coupe la transition.

**Écartés.**

- *Camembert ou anneau du ton* : les valeurs proches se comparent mal.
- *Huit courbes superposées* : huit teintes catégorielles, dont le rouge et le bleu pris par les
  camps ; des croisements illisibles.
- *Double axe* (volume et indice) : l'alignement des échelles est arbitraire.
- *Nuage de mots des thèmes* : taille illisible, pas de valeur lue.
- *Carte de chaleur émotion x heure* : trop peu de posts par case.
- *Courbe de ton avec moins de 7 points* : le pas s'adapte à la période (voir « Périodes, pas et libellés ») ; une série compte
  de 24 à 400 tranches.
- *Fenêtres de 5 min brutes pour les courbes de candidat* : quelques posts évalués par fenêtre ;
  la courbe est cumulée depuis le début de la période, et son dernier point égale l'indice du
  classement.
- *Vue par post, texte, identifiant* : interdits (mesure M5).

## 7. La barre d'opinion : formule de position

**Entrées.** Les lignes de `cibles_fenetre` de la période dont l'entité est un **candidat** (type
`candidat`) rattaché à un camp (`gauche`, `centre`, `droite`). Les partis et les candidats non
classés n'entrent pas.

Pour chaque camp `c` :

```
P_c = somme des posts de stance « pour »      sur les candidats du camp c
C_c = somme des posts de stance « contre »    sur les candidats du camp c
E_c = P_c + C_c                               évaluations du camp
N_c = (P_c − C_c) / E_c                       indice net du camp, entre −1 et +1

position p = (N_droite − N_gauche) / 2        entre −1 (gauche) et +1 (droite)
```

**Seuil.** La barre s'affiche si `E_gauche >= seuil` et `E_droite >= seuil`. Le seuil est réglable
(par défaut 20 ; paramètre d'URL `seuil`). Sinon l'état « pas assez de posts évalués » remplace
le curseur et dit quel camp manque. Les nombres restent affichés.

**Marge d'erreur indicative (95 %).** Pour chaque camp, `π = (P + 1) / (E + 2)` et
`var(N) = 4π(1 − π) / (E + 2)`. Puis `se(p) = ½ √(var(N_gauche) + var(N_droite))` et
l'intervalle `p ± 1,96 se(p)`, borné à [−1, 1]. Elle suppose des posts indépendants : les reprises
et les fils la sous-estiment. À 20 évaluations par camp elle vaut environ ± 0,3 ; à 100, ± 0,14.

**Pourquoi cette formule.**

1. *Une différence de deux rapports.* Le volume ne déplace pas le curseur : un camp plus cité
   n'attire pas la barre. Elle répond à « les avis sont-ils meilleurs d'un côté ? », pas à « de
   quel côté parle-t-on le plus ? ».
2. *Centrée sur zéro quand les deux camps sont traités pareil*, même si tous sont rejetés : une
   négativité générale ne déplace pas la barre.
3. *Recalculable à la main* : les six nombres `P`, `C` de chaque camp sont affichés sous la barre,
   avec le calcul chiffré.
4. *Le centre est affiché mais exclu de `p`* : l'axe est à une dimension, et un avis sur un
   candidat du centre ne dit ni gauche ni droite.
5. *Seule `cibles_fenetre`* : pas de dépendance à une autre table, pas de texte, pas d'identifiant.

**Limites déclarées.** Elles sont listées dans [`AGENTS.md`](AGENTS.md), section « Limites
déclarées ».

## 8. Composition de la page

Un shell fixe et quatre pages, choisies par `vue`. L'écran d'ordinateur passe d'abord : la colonne de
contenu fait 1680 px au plus, à droite de la barre latérale ; les paragraphes restent à 70 caractères. Sous 900 px, la barre latérale passe au-dessus du contenu.
La page par défaut est celle du ton et des émotions, question centrale du sujet (slide 7).

- **Barre latérale** (240 px, fixe) : titre de l'application, point de fraîcheur avec libellé, navigation
  entre les quatre pages, mention M10 en pied (« Mesure non représentative, ce n'est pas un sondage. »).
- **Période** : quatre boutons radio compacts (« 24 h », « 7 j », « 30 j », « Tout ») à droite du titre de
  la page, absents de la page événement qui a sa propre fenêtre. Pas de barre fixe en haut : seule la
  période change souvent ; le seuil et la plage de dates restent des paramètres d'URL, sans contrôle,
  parce qu'ils encombraient chaque page pour un usage rare.
- **En-tête de page** : titre et phrase d'introduction, heure de lecture de la base (heure de Paris),
  fenêtre en dates et durée, avertissements de l'API, bandeau renvoyé par l'API quand il existe.
- **Contraste** (`vue=contraste`) : trois tuiles (posts scorés, dernière donnée, délai moyen de traitement),
  ton (positif contre négatif, neutre à part), ton dans le temps, émotions, thèmes.
- **Popularité** (`vue=popularite`) : barre d'opinion (instrument, mention M10, formule chiffrée), puis cote
  des candidats ou des partis (`cible`), courbes par candidat.
- **Top 3** (`vue=top3`) : les trois premiers candidats côte à côte, puis les trois premiers partis : bulles
  de thèmes, bulles d'adjectifs (posts favorables, puis défavorables), barres d'émotions, tableaux des thèmes,
  des adjectifs et des occurrences. Un adjectif s'écrit dans sa bulle : on lit le mot avant le nombre. Le
  rayon suit la racine du nombre de posts, avec un minimum pour que le mot tienne ; le nombre est écrit.
  Teinte de ton (vert pour, orange contre) : l'adjectif qualifie un avis, pas un camp. Côte à côte, les trois profils se
  comparent sans défilement ; sous 1100 px de contenu, ils passent en colonne.
- **Événement** (`vue=evenement`) : relier un fait daté à la réaction des discussions.
  - *Choix du fait* : catalogue (`api/evenements`) avec recherche par texte et filtres de catégorie
    (manifestation, loi, prix, bourse, grève), ou saisie à la main (libellé, jour J, heure facultative).
  - *Chronologie* de J−3 à J+3, une réponse `tableau` : petits multiples alignés sur le même axe du temps,
    posts scorés puis un camp par ligne, évaluations « pour » au-dessus de l'axe et « contre » en dessous.
    Une seule échelle pour les trois camps : la question est « quel camp réagit », donc les hauteurs se
    comparent d'une ligne à l'autre. Couleur du camp (contre plein, pour éclairci) : la direction dit la
    stance, la couleur l'identité. Le fait est un trait à son heure, ou une bande sur son jour sans heure.
    Fond gris avant le jour J. Graduations en jours relatifs (J−3 … J+3) et en dates.
  - *Avant / après* : trois jours de chaque côté (J−3 à J−1, J à J+2), deux réponses, valeurs reçues côte à
    côte (posts, évaluations pour et contre, indice net par camp). Durées égales : les nombres se comparent.
  - *Mise en garde* : un écart ne prouve pas une cause (autres faits la même semaine, biais Bluesky).
- **Portraits** : un candidat dont la photo est libre apparaît en portrait rond (40 px dans la cote, 64 px
  au top 3), bordé de la couleur de son camp. Le visage identifie plus vite qu'un nom dans une liste. Le
  camp reste dit par l'étiquette (forme et libellé) : la bordure seule ne porte jamais l'information.
  Sans photo libre, et pour tous les partis : initiales dans la forme du camp. Pied de page : crédits des
  photos.

## 9. États

| État | Rendu |
|---|---|
| Chargement (premier affichage) | Blocs gris de la taille finale, sans animation ; `aria-busy`. |
| Rafraîchissement | L'affichage précédent reste ; aucun squelette. |
| Vide (aucune ligne sur la période) | Texte qui dit quoi faire : démarrer le flux, élargir la période. |
| Peu de données (sous le seuil) | Barre hachurée « pas assez de posts évalués » avec les manques chiffrés ; indices remplacés par les décomptes. |
| Aucun candidat classé | La barre dit que le rattachement manque ; les décomptes restent. |
| Erreur de base | Message qui nomme le service à vérifier. Si un affichage précédent existe, il reste, marqué périmé. |
| Données périmées (flux arrêté) | Point d'état « retard » ou « arrêté » avec libellé et durée ; les chiffres restent. |
| Aucun fait choisi (événement) | Texte qui dit quoi faire : choisir dans le catalogue ou saisir le jour J ; aucun appel `tableau`. |
| Catalogue indisponible (événement) | La collecte des faits n'est pas installée : la page le dit et laisse la saisie à la main. |
| Semaine sans données (événement) | La page dit où commence la base ; « avant » ou « après » incomplet (début de la base, aujourd'hui, dernier micro-lot) : une note demande de comparer les indices, pas les nombres. |

Fraîcheur : `ok` jusqu'à 5 min sans mise à jour, `warn` jusqu'à 30 min, `critical` au-delà
(variables `FRAICHEUR_OK_MIN`, `FRAICHEUR_ALERTE_MIN`). Une nuit calme ressemble à un flux
arrêté : le libellé dit « aucun nouveau post depuis… », sans accuser le pipeline.

## 10. Non vérifié

- [x] Palette de données validée par le script dans les deux thèmes : 0 échec, 1 alerte connue.
- [x] Aucune valeur de couleur littérale dans `web/src` : toute couleur passe par `style.css`.
- [x] `prefers-reduced-motion` coupe animations et transitions (règle globale de `style.css`, lue dans le code).
- [x] Contrôle statique du code sans build (délimiteurs, imports, motifs interdits) : aucune anomalie.
- [ ] La tâche du lecteur est servie sur le premier écran (titre, fraîcheur, tuiles, ton) : à regarder à l'écran.
- [ ] Tableau à côté de chaque graphique : présent pour le ton dans le temps, la barre d'opinion, le top 3
  et la page événement ; absent pour les émotions et les thèmes du contraste, et pour la cote. À trancher.
- [x] Build Docker de `web/` : réussi (branche d'intégration `integ/dashboard-v3`).
- [x] Rendu regardé en clair à 1600 et 1920 px (Chromium headless) : contraste, popularité, top 3, avec
  photos et bulles. Les captures restent hors dépôt : elles montrent des données réelles.
- [ ] Rendu en sombre, à 390 px, et page événement : non regardés. Les captures de `web/captures/` datent de
  l'ancienne version.
- [ ] Clavier : Tab sur la navigation et le sélecteur de période, focus visible : non vérifié dans un navigateur.
- [ ] À faire par l'utilisateur : lecteur d'écran (y compris les états d'erreur et périmé), pile officielle.

## 11. Périodes, pas et libellés

Les périodes et leur pas sont fixés par le contrat de l'API (section du JSON `tableau` de
`docs/technique/contrats-poc.md`). La page se rafraîchit toutes les 60 s sur `24h`, toutes les
5 min sur les autres périodes.

- Un libellé d'axe suit le pas : heure seule au même jour (pas de 1 h), date et heure au
  changement de jour, date seule (pas de 1 jour), « sem. du … » (pas de 1 semaine).
- Les graduations sont espacées selon la largeur mesurée : un libellé ne touche pas le suivant.
- Le repère de la période précédente ne s'affiche que si l'API le fournit. Son libellé dit la
  période comparée : « 7 jours précédents », « 24 h précédentes ».
- Une série de plus de 60 tranches passe en surface empilée (même donnée, mêmes tons).
- La barre d'opinion n'a pas de repère pour « depuis le début » : l'API renvoie `precedente: null`.

**Choix de réalisation.** Application React : `web/src/App.jsx` (routage par `vue`, états généraux), `web/src/pages/` (une page par
fichier), `web/src/components/` (coquille, graphiques, états). Les graphiques
sont écrits à la main : courbes et icônes en SVG, barres, pile de ton et colonnes en HTML et CSS.
Aucune bibliothèque de graphiques. Les jetons vivent dans `web/src/style.css` ; le validateur de
palette lit ce fichier. Les formes des camps (carré, rond, losange) doublent la couleur : une
icône et un libellé accompagnent chaque camp.
