# Faits datés : collecte RSS proposée

> Proposition. La table `evenements`, la route `GET /api/evenements` et la page « Événement » du
> dashboard existent. La collecte qui remplirait la table n'est pas installée. Les droits d'usage
> des flux restent à valider (section « Droits d'usage »).

## Objet

Relier un fait réel à la réaction des discussions. Le fait est une manifestation, une loi, une
hausse des prix, une chute de la bourse ou une grève. La page « Événement » isole la semaine du
fait (J−3 à J+3) et montre, camp par camp, les évaluations pour et contre. Il lui faut un
catalogue de faits datés, que l'on cherche par texte et par catégorie. Ce document propose de
remplir ce catalogue avec les flux RSS de la presse.

## Lien avec le Livrable 0

- **Slide 7.** Le sujet mesure « l'évolution des sentiments et émotions dans les discussions
  publiques ». Un fait daté sert de repère dans cette évolution.
- **Slide 7, questions éthiques.** L'analyse reste collective : le fait est public, la réaction
  est une somme d'évaluations par camp. Aucun post ni auteur n'est relié au fait.
- **Slide 3 : écart à justifier.** L'architecture commune n'a qu'une source. Le catalogue est
  une donnée de référence : il n'est ni scoré par le modèle ni désidentifié par Spark. Si la
  collecte est retenue, le README le dit (« Pourquoi ce choix ? Quelles limites ? », slide 18).
- **Slide 5.** Les titres de presse nomment des personnes, surtout des personnalités publiques.
  Le catalogue ne garde que des titres classés dans les cinq catégories, sans texte d'article
  (section « Données gardées »).

## Mesures du 2026-11-01

Une requête GET par flux, depuis le poste de développement. Les titres relevés restent hors du
dépôt. Ces chiffres sont **mesurés** sur un seul relevé : ils changent d'un jour à l'autre.

| Flux | Réponse | Articles | Période couverte | Texte |
|---|---|---|---|---|
| Le Monde : politique, économie, société | 200 | 20 par flux | 1,2 à 1,4 jour | chapô (≈ 230 caractères) |
| franceinfo : politique, économie, société | 200 | 20 par flux | 0,3 à 2,2 jours | chapô |
| Le Figaro : politique, économie | 200 | 20 par flux | 2 à 8,8 jours | chapô |
| Public Sénat | 200 | 60 | 6,3 jours | texte long dans `content:encoded` |
| INSEE, séries de la BDM | 200 | 39 | 24 jours | titres de séries, pas des articles |
| Libération, vie-publique.fr, Les Échos | 403 ou 404 (protection anti-robots) | — | — | — |

Classement des 245 titres uniques par mots-clés (manifestation, loi, prix, bourse, grève) :

| Classe | Titres | Faux positifs vus |
|---|---|---|
| manifestation | 35 | 4 manifestations à l'étranger |
| loi | 14, dont 8 en mot entier | « emploi », « falloir », « vouloir » (motif cherché dans le mot) |
| prix | 24 | prix Nobel, prix d'un jeune économiste ; titres de séries INSEE |
| bourse | 3 | aucun krach ; deux actualités boursières ordinaires |
| grève | 0 | 5 descriptions sur 259 citent une grève, aucun titre |

74 titres sur 245 entrent dans au moins une classe.

## Conséquences pour la conception

1. **Collecter en continu.** Un flux ne garde que ses 20 derniers articles, soit quelques heures
   à quelques jours. Une collecte toutes les heures ne perd rien ; une collecte ponctuelle ne
   rattrape pas le passé. Le rejeu du 12 au 26 octobre ne recevra donc aucun fait par RSS : ses
   faits se saisissent à la main dans la page.
2. **Classer sur des mots entiers.** Un motif cherché à l'intérieur des mots produit des faux
   positifs (« loi » dans « emploi »). Le classement lit le titre et le chapô en mémoire, sur des
   mots entiers, avec une liste d'exclusions (« prix Nobel », « prix littéraire »). Un titre sans
   classe n'entre pas au catalogue.
3. **Dédoublonner par lien.** 13 liens apparaissent dans deux flux ou plus. L'identifiant est une
   empreinte du lien ; la table `ReplacingMergeTree` garde une ligne par lien.
4. **Écrire directement dans ClickHouse.** Voir la section suivante.

## Architecture : deux options

| | A. Collecteur → ClickHouse | B. Collecteur → Kafka → Spark → ClickHouse |
|---|---|---|
| Principe | un petit service lit les flux chaque heure et insère dans `sae.evenements` | un topic `evenements`, un job Spark qui classe et écrit |
| Volume | une centaine d'articles par jour : un insert par heure suffit | même volume, porté par un cluster |
| Ce que Spark apporterait | rien : pas de modèle à appliquer, pas de donnée personnelle à retirer en flux | cohérence avec la slide 3 |
| Coût | un dossier `src/evenements/`, un service, un compte d'écriture | un topic, un job, un checkpoint, la même logique de classement |
| Limite | une deuxième voie d'écriture dans ClickHouse, à documenter | complexité sans bénéfice mesurable |

**Option retenue pour la proposition : A.** Le catalogue est une donnée de référence à faible
débit ; le faire passer par Spark paie la complexité d'un flux sans en utiliser les capacités.
Contrepartie : une exception à l'architecture commune, à justifier dans le README.

Brique proposée : `src/evenements/` (collecteur, classement, tests, `AGENTS.md`), compte
`pipeline` pour l'écriture, table créée par `infra/clickhouse/init.sql`. Les briques restent
séparées : le dashboard lit la table, il n'importe rien de `src/evenements/`.

## Données gardées

| Champ | Gardé | Raison |
|---|---|---|
| titre | oui | la recherche dans la page porte sur lui |
| date de publication | oui | position du fait dans le temps |
| catégorie | oui | filtre de la page |
| source, lien | oui | renvoi vers l'article, crédit de l'éditeur |
| chapô, texte, image, auteur de l'article | non | inutiles au repère ; texte protégé par le droit d'auteur |

Durée : 365 jours (TTL de la table), comme les agrégats. Les flux « société » mêlent faits
divers et personnes privées : seuls les titres classés dans les cinq catégories entrent.

## Droits d'usage (à faire valider)

Textes lus le 2026-11-01 :

- **Le Monde** (balise `copyright` des flux) : « L'utilisation des flux RSS du Monde.fr est
  réservée à un usage strictement personnel, non professionnel et non collectif. »
- **Le Figaro** (CGU) : la rediffusion et l'exploitation professionnelle « est strictement
  interdite sauf accord préalable du Figaro. Il en est de même des flux RSS ».
- **franceinfo** (CGU, § 13.1) : France Télévisions « s'oppose à toutes opérations de
  moissonnage et de fouille de textes et de données » (article L. 122-5-3 du code de la
  propriété intellectuelle).

Un projet de groupe présenté en soutenance n'est pas un usage « strictement personnel ».
Questions pour le référent juridique, comme pour le Livrable 1 :

1. L'exception de fouille de textes pour la recherche (article L. 122-5-3, II) couvre-t-elle un
   projet d'école d'ingénieurs ?
2. Garder le titre et le lien, sans le texte, sort-il du champ de ces restrictions ?

En attendant la réponse, deux voies sans risque :

- **Sources ouvertes** : textes publics sous licence ouverte (lois promulguées, Journal officiel,
  data.gouv.fr). Non vérifié : vie-publique.fr a bloqué le relevé automatique.
- **Saisie à la main** : quelques faits majeurs, titre reformulé, lien vers l'article. C'est ce
  que permet déjà la page.

## Ce que la page montre déjà

- **Catalogue** : recherche par texte et filtres de catégorie ; « catalogue indisponible » tant
  que la table n'existe pas (cas de la pile du POC).
- **Saisie à la main** : libellé, jour J, heure facultative.
- **Simulation** : `src/dashboard/api/outils/donnees_synthetiques.py --scenario evenement` crée un
  fait inventé il y a cinq jours à 18 h et un pic d'évaluations « contre » sur les candidats de
  droite. Les candidats sont fictifs : aucun chiffre inventé n'est attribué à une personne réelle.

## Limites

- **Causalité.** Un écart entre avant et après ne prouve pas que le fait en est la cause. D'autres
  faits ont pu arriver la même semaine ; la page le rappelle sous le tableau.
- **Fenêtre de trois jours.** Choix d'affichage : une réaction peut durer plus longtemps ou
  commencer avant la publication (annonce, fuite).
- **Heure de publication.** L'heure de l'article n'est pas l'heure du fait (une manifestation
  annoncée la veille, un article écrit le lendemain).
- **Représentativité.** Les posts Bluesky ne représentent pas l'électorat (Livrable 1).
- **Couverture des flux.** Les flux reflètent les choix éditoriaux de quelques titres ; trois
  éditeurs bloquent la lecture automatique.
