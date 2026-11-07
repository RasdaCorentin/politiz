# Contrats du POC — interfaces entre briques

*Livrable 2 (slide 13) : SOURCE ➔ KAFKA ➔ SPARK ➔ traitement ➔ restitution. Ce fichier est la
source de vérité des interfaces. Une brique ne dépend d'une autre que par ces contrats
(`AGENTS.md` racine, « Dépendances entre briques »). Un changement d'interface modifie ce
fichier d'abord, dans le même commit que le code.*

## 1. Pile et réseau

Projet Compose `sae-poc`, fichier `infra/docker-compose.yml`. Tous les ports hôte sont liés à
`127.0.0.1`. Les ports hôte 8080, 8081 et 5050 sont pris par d'autres projets du poste.

| Service | Image visée (à vérifier par `docker pull`, puis épingler) | Interne | Hôte |
|---|---|---|---|
| `kafka` | `apache/kafka` 3.9.x, KRaft, 1 nœud | 9092 | 29092 |
| `minio` | MinIO, image épinglée (voir « Limites déclarées ») | 9000 (API), 9001 (console) | 19000, 19001 |
| `clickhouse` | `clickhouse/clickhouse-server` 25.8 (LTS) | 8123 (HTTP) | 18123 |
| `spark-master` | image `sae-spark` (Spark 3.5.x, Java 17, Python 3) | 7077, 8080 | 18080 |
| `spark-worker-1`, `spark-worker-2` | `sae-spark` | 18081, 18082 | 18081, 18082 |
| `streaming` | `sae-spark` ; `spark-submit` en mode client | 14040 | 14040 |
| `producer` | `python:3.13-slim` | — | — |
| `dashboard-api` | `python:3.12-slim` + Gunicorn (build `src/dashboard/api/`) | 8000 | — |
| `dashboard` | `nginxinc/nginx-unprivileged` (build `src/dashboard/web/`) | 8080 | 8501 |

- **Profils Compose.** Sans profil : `kafka`, `minio`, `clickhouse`, `spark-master`,
  `spark-worker-1/2` et leurs conteneurs d'initialisation. Profil `pipeline` : `producer`,
  `streaming`, `dashboard-api`, `dashboard`.
- **Budget.** Environ 12,6 Gio de RAM au total (somme des limites par conteneur, calculée dans
  `infra/AGENTS.md`), démarrable sur un poste de 16 Gio. Réglable par `infra/.env` (`WORKER_CORES`, `WORKER_MEMORY`, …).
- **Cluster Spark.** 1 master et 2 workers (slide 4), 2 cœurs par worker. Le job demande
  `spark.executor.cores=2` et `spark.cores.max=4` : un executor par worker.
- **Heure.** Tout est stocké en UTC. Le dashboard affiche l'heure de Paris.
- **Versions.** Épinglées (jamais `latest`). Un jar ou une image changé = une ligne dans
  `infra/AGENTS.md`.

## 2. Contrat Kafka : topic `raw-posts`

Le producteur ([`src/ingestion/`](../../src/ingestion/AGENTS.md)) écrit, le job Spark lit.

| Propriété | Valeur |
|---|---|
| Partitions / réplication | 4 / 1 |
| Clé | **aucune** (jamais un identifiant d'auteur) |
| Valeur | événement Jetstream `app.bsky.feed.post`, JSON UTF-8, **relayé tel que reçu** |
| `retention.ms` | `3600000` (1 h) |
| `segment.ms` | `600000` (10 min) : Kafka ne purge que les segments fermés |
| `retention.bytes` | `1073741824` (1 Gio) |
| `cleanup.policy` | `delete` |
| Vérification de la rétention | `log.retention.check.interval.ms=60000` |

**Pourquoi 1 h.** Le topic contient des données brutes (`did`, texte). Il sert de tampon entre
la source et Spark, pas de stockage : un post brut y reste de 1 h à 1 h 10. Une panne de
Spark de plus d'une heure perd des posts (`failOnDataLoss=false`) ; ces posts publics ne sont
pas rejoués.

**Pré-filtre du producteur.** Il garde : `operation=create`, collection `app.bsky.feed.post`,
langue déclarée `fr`, règle de mots-clés de `src/ingestion/keywords.txt` (3 classes). Seuls les
posts qui parlent de politique entrent dans le pipeline (minimisation à la source, slide 5).
Spark filtre à nouveau (contrat Spark).

Exemple de valeur (identifiants inventés) :

```json
{"did":"did:plc:synthetic0001","time_us":1791400000000000,"kind":"commit",
 "commit":{"rev":"3exemplerev22","operation":"create","collection":"app.bsky.feed.post",
  "rkey":"3exemplerkey2","cid":"bafyreiexample",
  "record":{"$type":"app.bsky.feed.post","createdAt":"2026-10-08T04:42:16.721Z",
   "langs":["fr"],"text":"Texte inventé qui cite Glucksmann."}}}
```

**Sources du producteur.** `jetstream` (flux réel) et `synthetic` (posts inventés à partir des
exemples de `ressources/lexique/stance.yaml`, `did` fictifs, débit réglable). Le mode
`synthetic` sert aux tests et aux essais de charge.

## 3. Contrat Spark : `src/streaming/job.py`

Point d'entrée : `spark-submit --master spark://spark-master:7077 /opt/streaming/job.py`.
`src/streaming/` est monté en lecture seule sur `/opt/streaming` dans tous les conteneurs Spark ;
`ressources/lexique/` sur `/opt/lexique`.

| Réglage | Valeur |
|---|---|
| Lecture | Kafka, `startingOffsets=earliest` (checkpoint neuf seulement), `maxOffsetsPerTrigger=20000`, `failOnDataLoss=false`, `minPartitions=4` |
| Déclencheur | `processingTime = 30 seconds` |
| Fenêtre | 5 minutes, tumbling, UTC. Temps d'événement = `time_us` (heure de réception Jetstream), jamais `createdAt` (fixé par le client) |
| Filigrane (watermark) | 10 minutes |
| Checkpoint | `s3a://checkpoints/streaming/` |
| Écritures | `foreachBatch` : un micro-lot écrit MinIO puis ClickHouse |
| Fuseau | `spark.sql.session.timeZone=UTC` |
| Journaux | niveau WARN ; le code n'écrit que des compteurs, jamais un texte ni un identifiant |

**Étapes, dans l'ordre :**

1. **Projection par liste blanche.** Un schéma explicite ne garde que `time_us`,
   `commit.operation`, `commit.collection`, `commit.record.text`, `commit.record.langs`,
   `commit.record.facets` (hashtags). Tout autre champ disparaît : `did`, `rkey`, `cid`, `rev`,
   `reply.*`, `embed`, `createdAt`, mentions (M1).
2. **Nettoyage.** `create` seulement, langue `fr`, texte non vide. Masquage des URL et des
   `@handles` du texte, normalisation (minuscules, sans accents).
3. **Dédoublonnage.** `dropDuplicatesWithinWatermark` sur le hash SHA-256 du texte nettoyé : un
   texte identique dans la fenêtre compte une fois (robots, copier-coller). L'état est dans le
   checkpoint.
4. **Scoreur provisoire** `lexique-v1` (scoring par lexique), exécuté par un `pandas_udf`. Le lexique se charge
   une fois par executor.
5. **Filtre fin.** Un post sans cible, sans thème et sans émotion reconnus compte dans
   `pipeline_fenetre` seulement.
6. **Désidentification de l'horodatage.** `fenetre_debut` remplace l'heure précise dès que la
   latence est calculée. Le texte n'est écrit ni dans MinIO, ni dans ClickHouse, ni dans le
   checkpoint (voir « Où disparaît chaque donnée »). Les fichiers shuffle des workers en gardent une copie nettoyée (voir « Limites déclarées »).
7. **Écritures.** MinIO (buckets et objets) puis ClickHouse (tables `sae`).

## 4. Contrat MinIO

| Bucket | Contenu | Cycle de vie |
|---|---|---|
| `scores` | lignes Parquet de scores, sans texte ni identifiant | expiration à **30 jours** (M3) |
| `checkpoints` | checkpoint du job | expiration à **1 jour** sur le préfixe `streaming/state/` (M6) |

- Chemin des scores : `s3a://scores/posts/dt=AAAA-MM-JJ/`, Parquet, mode `append`.
- **Une ligne par post et par cible citée** (une ligne avec `entite` nul si le post ne cite
  personne).
- Les préfixes `metadata`, `offsets` et `commits` du checkpoint ne portent que des offsets
  Kafka : ils ne sont pas purgés. L'état de dédoublonnage (`state/`, hash de texte) l'est.
- **Reprise après expiration.** Si `state/` a disparu, le job efface le checkpoint entier, journalise
  une ligne sans donnée, puis quitte avec le code 3. Docker (`restart: on-failure`) le relance sur un
  checkpoint neuf, lu depuis le plus ancien message que Kafka retient (1 h). Toute autre erreur est
  relancée sans rien effacer.
- Comptes : `root` pour l'administration ; un compte de service `pipeline` limité à ces deux
  buckets pour Spark (M4).

| Colonne | Type | Valeurs |
|---|---|---|
| `fenetre_debut` | timestamp (UTC) | début de la fenêtre de 5 min |
| `langue` | string | `fr` |
| `entite` | string, nullable | id de `entites.yaml` |
| `stance` | string | `pour` `contre` `neutre` `mention` `ambigu` `non_evalue` |
| `sentiment` | string | `positif` `negatif` `neutre` `non_evalue` |
| `emotion` | string | `joie` `colere` `peur` `tristesse` `surprise` `degout` `neutre` `non_evalue` |
| `themes` | array\<string\> | thèmes de `themes.yaml` (+ `autre`) |
| `confiance` | string | `haute` `moyenne` `aucune` |
| `scoreur` | string | `lexique-v1` |

## 5. Contrat ClickHouse : base `sae`

Cinq tables d'agrégats, une par grain. Elles se **somment** : le job insère des incréments par
micro-lot, ClickHouse fusionne. Les lectures utilisent `sum(...)` et `GROUP BY`, jamais la
valeur brute d'une ligne. Un lot rejoué compte deux fois (at-least-once, voir « Limites déclarées »).

```sql
CREATE DATABASE IF NOT EXISTS sae;

CREATE TABLE IF NOT EXISTS sae.cibles_fenetre      -- popularité : par candidat ou parti
(
    fenetre_debut DateTime('UTC'),
    entite        LowCardinality(String),
    stance        LowCardinality(String),
    nb_posts      UInt64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(fenetre_debut)
ORDER BY (fenetre_debut, entite, stance)
TTL fenetre_debut + INTERVAL 365 DAY;

CREATE TABLE IF NOT EXISTS sae.posts_fenetre       -- baromètre : ton et émotions, tous posts
(
    fenetre_debut DateTime('UTC'),
    sentiment     LowCardinality(String),
    emotion       LowCardinality(String),
    nb_posts      UInt64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(fenetre_debut)
ORDER BY (fenetre_debut, sentiment, emotion)
TTL fenetre_debut + INTERVAL 365 DAY;

CREATE TABLE IF NOT EXISTS sae.themes_fenetre      -- un post compte dans chacun de ses thèmes
(
    fenetre_debut DateTime('UTC'),
    theme         LowCardinality(String),
    nb_posts      UInt64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(fenetre_debut)
ORDER BY (fenetre_debut, theme)
TTL fenetre_debut + INTERVAL 365 DAY;

CREATE TABLE IF NOT EXISTS sae.pipeline_fenetre    -- volume, latence, fraîcheur
(
    fenetre_debut    DateTime('UTC'),
    derniere_maj     DateTime('UTC'),
    nb_posts         UInt64,
    somme_latence_ms UInt64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(fenetre_debut)
ORDER BY (fenetre_debut, derniere_maj)
TTL fenetre_debut + INTERVAL 365 DAY;

CREATE TABLE IF NOT EXISTS sae.croisements_fenetre -- historique long : toutes les dimensions croisées
(
    fenetre_debut DateTime('UTC'),
    entite        LowCardinality(String),   -- '' : post sans cible
    stance        LowCardinality(String),
    sentiment     LowCardinality(String),
    emotion       LowCardinality(String),
    theme         LowCardinality(String),
    scoreur       LowCardinality(String),   -- ex. lexique-v1 ; change quand le modèle remplace les règles
    nb_posts      UInt64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(fenetre_debut)
ORDER BY (fenetre_debut, entite, stance, sentiment, emotion, theme, scoreur)
TTL fenetre_debut + INTERVAL 365 DAY;

CREATE TABLE IF NOT EXISTS sae.adjectifs_fenetre   -- adjectifs d'un lexique fermé, par cible et stance
(
    fenetre_debut DateTime('UTC'),
    entite        LowCardinality(String),
    stance        LowCardinality(String),
    adjectif      LowCardinality(String),   -- forme affichée de ressources/lexique/adjectifs.yaml, jamais un mot libre du post
    scoreur       LowCardinality(String),
    nb_posts      UInt64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(fenetre_debut)
ORDER BY (fenetre_debut, entite, stance, adjectif, scoreur)
TTL fenetre_debut + INTERVAL 365 DAY;

-- Table facultative : catalogue des faits datés (collecte RSS proposée, non installée).
CREATE TABLE IF NOT EXISTS sae.evenements          -- titre et lien publics, aucun texte d'article
(
    id               String,                  -- empreinte du lien (ou du titre sans lien)
    date_publication DateTime('UTC'),
    titre            String,
    categorie        LowCardinality(String),  -- manifestation, loi, prix, bourse, greve, autre
    source           LowCardinality(String),
    lien             String
)
ENGINE = ReplacingMergeTree
ORDER BY id
TTL date_publication + INTERVAL 365 DAY;
```

- `cibles_fenetre` : une ligne par (post, cible citée). Un post qui cite deux candidats compte
  dans les deux lignes : ne jamais additionner les entités pour obtenir un nombre de posts.
  Pour un nombre de posts, lire `posts_fenetre`.
- `croisements_fenetre` : une ligne par (post retenu, cible ou `''`, thème), avec toutes les
  dimensions du post. C'est la seule table qui garde, au-delà des 30 jours de MinIO, les
  croisements candidat × émotion, candidat × thème, candidat × sentiment et la version du
  scoreur : elle sert à croiser l'opinion avec des événements datés. Ses comptes sont des
  occurrences (un post à deux cibles et deux thèmes compte quatre fois) : un nombre de posts se
  lit dans `posts_fenetre`. Un changement de `scoreur` est une rupture de série, pas un événement.
  Le dashboard lit cette table pour la section `croisements` (« JSON `tableau`, version 4 ») : sommes par (entité, thème) et par (entité, émotion), pour le seul scoreur de la fenêtre la plus récente.
- `adjectifs_fenetre` : une ligne par (post retenu, cible évaluée `pour` ou `contre`, adjectif).
  Un post compte une fois par (cible, adjectif) : la somme donne des posts. Le job Spark
  l'alimente. L'adjectif vient du **lexique fermé**
  [`ressources/lexique/adjectifs.yaml`](../../ressources/lexique/adjectifs.yaml) (200 entrées) :
  un mot absent du lexique n'est jamais écrit, donc aucun mot libre d'un post n'atteint ClickHouse
  ni l'écran. L'adjectif est rattaché à chaque cible évaluée du post, sans lien grammatical.
  Une fenêtre scorée par un job qui ne les comptait pas n'a pas d'adjectifs : le texte n'est pas
  gardé, on ne les recalcule pas.
- `evenements` (facultative) : une ligne par fait daté (article de presse, loi promulguée). Elle
  ne contient ni texte d'article ni donnée de post : titre, date, catégorie, source et lien.
  `ReplacingMergeTree` : un même lien collecté deux fois garde une ligne. Collecte RSS proposée
  dans [`evenements-rss.md`](evenements-rss.md), non installée : seul `outils/donnees_synthetiques.py`
  du dashboard la remplit, avec des faits inventés. Sans la table, l'API sert un catalogue vide.
- `pipeline_fenetre.nb_posts` : posts scorés dans la fenêtre. Latence moyenne =
  `sum(somme_latence_ms) / sum(nb_posts)`. `derniere_maj` (dans la clé de tri : une ligne par micro-lot et par fenêtre) : heure du micro-lot ;
  lire `max(derniere_maj)`. Le connecteur Spark ne gère pas `SimpleAggregateFunction`.
- **Comptes (M4).** `pipeline` : `INSERT` et `SELECT` sur `sae.*`. `dashboard` : `SELECT` sur
  `sae.*`, profil `readonly`. L'utilisateur `default` n'est pas joignable depuis le réseau.
  Les mots de passe viennent de `infra/.env`.
- **Durée (M3).** TTL de 365 jours : plafond technique, la durée du projet étant plus courte.

## 6. Contrat du scoreur provisoire `lexique-v1`

Le modèle arrive au Livrable 3 ; le POC utilise les règles de `ressources/lexique/`, lues comme
des données (aucun import de code entre dossiers de `src/`). Méthode et limites :
[`lexique-regex.md`](lexique-regex.md).

- **Entrée :** texte nettoyé (étape de nettoyage du texte dans le contrat Spark). **Sorties :** `cibles` (liste de `entite`,
  `stance`, `confiance`), `sentiment`, `emotion`, `themes`.
- **Règles de décision.** Cible, stance, émotion, thèmes et sentiment suivent les règles de
  `ressources/lexique/` (confiance `haute` et `moyenne`). Le détail de chaque règle est dans la
  section « Scoreur `lexique-v1` » de [`src/streaming/AGENTS.md`](../../src/streaming/AGENTS.md).
  Quand aucune règle ne tranche, la valeur est `non_evalue` (et non `mention`).
- **Couverture.** Les règles de confiance haute tranchent la stance d'environ 3 % des posts
  (`lexique-regex.md`). Le dashboard affiche cette couverture à côté de chaque indicateur.
- **Interface remplaçable.** Le modèle du Livrable 3 reprend la même signature (texte ➔
  `cibles`, `sentiment`, `emotion`, `themes`) sans changer MinIO, ClickHouse ni le dashboard.

### 6.1 Scoreur à modèles : CamemBERT dans les executors

Les deux runs de « Contrat du modèle » remplacent les règles pour la **stance** et l'**émotion**. Les cibles, les
thèmes et le filtre fin (étape 5 du contrat Spark) restent ceux du lexique ; le sentiment reste dérivé par la
règle ci-dessus, appliquée aux sorties des modèles.

- **Activation.** `infra/.env` : `MODELES_DIR` (dossier hôte des runs, hors dépôt, ex.
  `$SAE_CORPUS_DIR/modeles`), `MODELE_STANCE` et `MODELE_EMOTION` (noms de runs). Le dossier est
  monté en lecture seule sur `/opt/modeles` dans les workers et le job ; les executors reçoivent
  `MODELE_STANCE_DIR` et `MODELE_EMOTION_DIR` (`/opt/modeles/<run>`) par `spark.executorEnv`.
  Une variable vide : la tâche garde les règles. Un run illisible : le job s'arrête au démarrage
  avec un message clair (pas de repli silencieux).
- **Entrée.** Identique à l'entraînement : `modele.json` (`entree.longueur_max`, `normaliser`,
  `noms_cibles`) ; stance = paire (nom de la cible, texte), émotion = texte. Le texte reçu est le
  texte nettoyé de l'étape 2.
- **Sortie.** Étiquette = probabilité maximale. `confiance` : `haute` (≥ 0,8), `moyenne`
  (≥ 0,5), sinon `aucune`. Aucun texte, aucune probabilité par post n'est journalisé.
- **Valeur de `scoreur`.** `lexique-v1` sans modèle ; sinon `camembert:` suivi des runs actifs,
  par exemple `camembert:stance-20261019-1636+emotion-20261019-1700`. C'est une rupture de série
  dans `croisements_fenetre` (tables ClickHouse).
- **Exécution et mémoire.** Chargement, lots, threads et mesures de mémoire : section « Scoreur à
  modèles » de [`src/streaming/AGENTS.md`](../../src/streaming/AGENTS.md). Les workers disposent de
  4 Gio (`WORKER_MEM_LIMIT`).
- **Permissions.** Les fichiers des runs doivent être lisibles par l'utilisateur `spark` du
  conteneur (`chmod -R o+rX` sur les runs ; le dossier du corpus reste en 700 sur l'hôte).

## 7. Contrat du dashboard : `src/dashboard/`

Deux services. `dashboard-api` lit ClickHouse (compte `dashboard`) et applique les formules ;
`dashboard` (nginx) sert la page compilée et relaie `/api/` vers `dashboard-api:8000`. Le
navigateur ne parle qu'à nginx ; l'API n'a pas de port hôte.

- L'API lit les cinq tables d'indicateurs du contrat ClickHouse, les tables facultatives `adjectifs_fenetre` et `evenements` quand elles existent (`system.tables`), et `ressources/lexique/entites.yaml` (monté sur `/app/lexique`,
  en lecture seule) pour le nom (`nom`, facultatif : sinon l'id en majuscules initiales), le type et le **camp** de chaque entité.
- **Camp.** `entites.yaml: camp` vaut `gauche`, `centre`, `droite` ou `null`. La barre
  d'opinion (rouge à gauche, gris au centre, bleu à droite) ne combine que les entités de
  `type: candidat` dont le camp n'est pas `null` ; les partis restent dans les classements.
  Le rattachement est documenté dans [`camps-candidats.md`](camps-candidats.md).
- **Trois lectures :** baromètre (ton et émotions de la discussion), cote de popularité par
  candidat (`pour` contre `contre`, volume, part des posts évalués), barre d'opinion
  gauche/droite avec courbes par candidat.
- **Obligations :** la mention « mesure non représentative, ce n'est pas un sondage » (M10) ; le
  nombre de posts évalués à côté de chaque indicateur ; un état « pas assez de posts » sous un
  seuil réglable ; aucune vue par post, aucun texte, aucun identifiant (M5).
- **Design :** [`src/dashboard/DESIGN.md`](../../src/dashboard/DESIGN.md), instance du contrat
  de `~/3A/projets/template/template-monitoring-viewpage/DESIGN.md`.

### 7.1 Routes de `dashboard-api`

| Route | Réponse |
|---|---|
| `GET /api/tableau?periode=24h\|7j\|30j\|tout&seuil=N` | `200` JSON `tableau` v4 (« JSON `tableau`, version 4 ») ; `periode` absente : `7j` ; `seuil` absent : `DASHBOARD_SEUIL_DEFAUT` |
| `GET /api/tableau?debut=AAAA-MM-JJ&fin=AAAA-MM-JJ&seuil=N` | même JSON sur une plage de dates choisie (jours de Paris, `fin` incluse, `debut` ≤ `fin`) ; `periode` vaut alors `perso` |
| `GET /api/evenements` | `200` catalogue `evenements` v1 (« JSON `evenements`, version 1 ») : faits datés, du plus récent au plus ancien |
| `GET /api/sante` | `200 {"status": "ok"}` si ClickHouse répond à `SELECT 1` |

- Paramètre invalide : `400 {"erreur": "…"}`. ClickHouse injoignable : `503 {"erreur": "base injoignable"}`
  (le détail va dans les journaux, jamais au navigateur). Autre méthode que `GET`/`HEAD` : `405`.
- En-têtes : `Cache-Control: no-store`, `ETag` calculé sur le corps **sans** `generated_at`,
  `X-Generated-At`. `If-None-Match` égal à l'`ETag` : `304` vide (avec les deux en-têtes).
- Lecture seule : l'API n'écrit nulle part. Elle ne renvoie que des agrégats par fenêtre et par
  entité : aucun texte, aucun identifiant d'auteur.

### 7.2 JSON `tableau`, version 4

Les périodes servent à lire l'opinion **dans la durée** (jours, semaines, campagne), pour la
croiser plus tard avec des événements. Le pas des séries suit la longueur de la période :

| `periode` | Étendue | `pas_min` |
|---|---|---|
| `24h` | 24 dernières heures | 60 |
| `7j` | 7 derniers jours | 360 |
| `30j` | 30 derniers jours | 1440 |
| `tout` | depuis la première fenêtre en base | 1440 ; 10080 au-delà de 180 jours |
| `perso` | `debut` à `fin` | 60 jusqu'à 2 jours, 360 jusqu'à 14, 1440 jusqu'à 180, 10080 au-delà |

Toutes les tranches sont alignées sur l'heure de Paris : 60 et 360 minutes sur l'heure pleine
(0 h, 6 h, 12 h, 18 h pour 360), 1440 sur minuit, 10080 sur le lundi à minuit. `debut` est le
début de la première tranche, `fin` la fin de la dernière ; la dernière tranche contient la
fenêtre en cours. Les exemples de `contrat/` ne montrent que la forme (leurs heures ne sont pas alignées).
L'API agrège dans ClickHouse par tranche (`toStartOfInterval`, `toStartOfDay`, `toMonday` avec le
fuseau `Europe/Paris`) : la réponse garde moins de 400 tranches quelle que soit la période.

Exemples complets, données inventées : `src/dashboard/contrat/tableau-v4.normal.json` (7 jours)
et `tableau-v4.vide.json`. Toutes les heures sont en ISO 8601 UTC (`…Z`) ; la page les affiche à
l'heure de Paris. Les nombres sont bruts (indices non arrondis) : la page formate.

| Clé | Type | Sens |
|---|---|---|
| `schema_version` | `4` | la page refuse toute autre version |
| `generated_at` | heure | instant de lecture de ClickHouse |
| `bandeau` | texte ou `null` | `DASHBOARD_BANDEAU` (ex. « Données synthétiques ») |
| `periode` | objet | `code` (`24h`, `7j`, `30j`, `tout`, `perso`), `debut`, `fin`, `pas_min`, `seuil`, `seuil_defaut`, `periodes` (`["24h", "7j", "30j", "tout"]`), `premiere_donnee` (heure de la plus ancienne fenêtre en base, ou `null`) |
| `etat` | objet | `base_vide`, `periode_vide` (booléens) ; `fraicheur` (`ok`, `warn`, `critical`, `unknown`) ; `derniere_maj` (heure ou `null`) ; `fraicheur_ok_min`, `fraicheur_alerte_min` ; `lexique_charge` (booléen) ; `hors_lexique` (entités lues absentes du lexique) ; `avertissements` (textes) |
| `pipeline` | objet | `posts` (posts scorés sur la période), `latence_moyenne_s` (nombre ou `null`) |
| `tranches` | heures | début de chaque tranche de `pas_min` minutes ; `volume` et `serie_ton` ont la même longueur |
| `volume` | entiers | posts scorés par tranche |
| `ton` | objet | `positif`, `neutre`, `negatif`, `non_evalue` : posts sur la période |
| `serie_ton` | objets | par tranche : `positif`, `neutre`, `negatif` |
| `emotions` | objet | `joie`, `colere`, `peur`, `tristesse`, `surprise`, `degout`, `neutre` : posts (toutes les clés, même à 0) |
| `emotions_non_evaluees` | entier | posts sans émotion détectée |
| `themes` | objets | `theme` (id), `libelle`, `posts` ; par posts décroissants, `autre` en dernier |
| `candidats`, `partis` | objets | une ligne par entité citée (format ci-dessous), classées par l'API |
| `barre` | objet | barre d'opinion (format ci-dessous) |
| `series` | objet | id d'un candidat classé → points `{fin, pour, contre, indice}` (indice cumulé, `null` sous le seuil) |
| `non_classes_evalues` | entier | évaluations de candidats au camp `null`, hors de la barre |
| `croisements` | objet | `scoreur`, `themes`, `emotions` : règles ci-dessous |
| `serie_camps` | objets | par tranche (même longueur que `tranches`) : `gauche`, `centre`, `droite` → `{pour, contre}` (règles ci-dessous) |
| `adjectifs` | objet ou `null` | `scoreur`, `couverture` (`debut`, `fin`, `posts_hors`, ou `null`), `lignes` (`entite`, `stance`, `adjectif`, `posts`) ; `null` sans table `adjectifs_fenetre` (règles ci-dessous) |

Ligne d'entité : `entite` (id), `nom`, `camp` (`gauche`, `centre`, `droite` ou `null`), `rang`
(entier, `null` sous le seuil), `pour`, `contre`, `neutre`, `mention`, `ambigu`, `non_evalue`,
`cites`, `evalues`, `indice` (`null` sans évaluation), `couverture` (`null` sans citation).
L'ordre est celui de l'API : classés par rang, puis non classés.

Barre : `etat` (`ok`, `insuffisant`, `aucun_camp`), `seuil`, `valeur`, `bas`, `haut` (entre −1 et
+1, `null` hors `ok`), `manquants` (camp → évaluations qui manquent), `camps` (`gauche`, `centre`,
`droite` → `{pour, contre, evalues, indice, candidats}`), `precedente` (`{etat, valeur, bas,
haut}` sur la période précédente de même durée ; `null` pour `tout`).

Section `croisements` : `scoreur` ; `themes` (`entite`, `theme`, `libelle`, `posts`) ; `emotions` (`entite`, `emotion`, `occurrences`). Règles :

- **Fenêtre.** Lignes de `croisements_fenetre` avec `fenetre_debut` dans la période (`debut` inclus, `fin` exclue). Totaux sur la période entière, sans découpage par tranche.
- **Un seul scoreur.** Le scoreur est celui de la fenêtre la plus récente (`max(fenetre_debut)`) ; à égalité, l'ordre alphabétique départage. Thèmes et émotions ne lisent que ce scoreur : une réponse ne mélange jamais deux scoreurs (rupture de série, « Contrat ClickHouse »). Un scoreur vide ne compte pas. Sans ligne : `scoreur` vaut `null` et les listes sont vides.
- **Entités.** Seules les entités de `candidats` et de `partis` de la réponse. L'entité `''` est exclue.
- **Thèmes.** `themes[].posts` vaut la somme de `nb_posts` par (entité, thème). Une valeur vide ou un total nul est exclu. Une ligne existe par (post, cible, thème) : un post à deux thèmes compte dans chacun, donc la somme des thèmes peut dépasser le nombre de posts.
- **Émotions.** `emotions[].occurrences` vaut la somme de `nb_posts` par (entité, émotion). Sont exclues : la valeur vide, la valeur `non_evalue` (aucune émotion détectée, comptée à part dans `emotions_non_evaluees`) et le total nul. Seules les émotions présentes sont listées. occurrences : un post qui porte k thèmes compte k fois (« Contrat ClickHouse »).
- **Libellé.** `libelle` passe par la même fonction que `themes` (`_libelle_theme` de `serialisation.py`, table `LIBELLE_THEME`). Repli pour un identifiant inconnu : tirets remplacés par des espaces, première lettre en majuscule.
- **Ordre.** Entité (ordre de `candidats`, puis de `partis`), `posts` décroissants, puis identifiant.
- Seules des sommes sortent : aucun texte, aucun identifiant d'auteur.

Section `serie_camps` : évaluations par tranche et par camp, pour lire une réaction dans le
temps (page « Événement »). Règles :

- **Candidats.** Les mêmes que `barre.camps` : `type: candidat` et camp `gauche`, `centre` ou
  `droite`. Les partis et les candidats au camp `null` n'entrent pas.
- **Comptes.** Somme de `nb_posts` de `cibles_fenetre` pour les stances `pour` et `contre`, par
  tranche. Ce sont des évaluations : un post qui juge deux candidats d'un camp compte deux fois.
  Sur la période, la somme d'un camp égale `barre.camps.<camp>.pour` et `.contre`.

Section `adjectifs` : adjectifs associés à chaque entité, par stance. Règles :

- **Table facultative.** `null` quand `adjectifs_fenetre` n'existe pas (base créée avant elle) : la
  page dit que les adjectifs ne sont pas comptés. Table présente sans ligne sur la période :
  `scoreur` et `couverture` valent `null`, `lignes` est vide.
- **Couverture.** `debut` : début de la première fenêtre comptée sur la période ; `fin` : fin de la
  dernière. `posts_hors` : posts scorés de la période (`pipeline_fenetre`) hors de cet intervalle,
  donc sans adjectifs comptés (scorés par un job qui ne les comptait pas). Un trou entre `debut` et
  `fin` n'est pas détecté. La page affiche les dates quand `posts_hors` dépasse 0.
- **Un seul scoreur**, choisi comme pour `croisements` (fenêtre la plus récente) : la stance dépend du scoreur.
- **Filtres.** Entités de `candidats` et de `partis` de la réponse ; stances `pour` et `contre` ;
  au moins 3 posts par (entité, stance, adjectif) ; au plus 8 adjectifs par (entité, stance).
  Le minimum écarte un mot rare, donc proche d'un post précis.
- **Ordre.** Entité (ordre de `candidats`, puis de `partis`), stance (`pour`, puis `contre`),
  `posts` décroissants, puis adjectif.

Un changement de forme = `schema_version` suivante, dans le même commit pour l'API, la page et les exemples.

### 7.3 JSON `evenements`, version 1

Catalogue des faits datés dans lequel la page « Événement » cherche un fait à isoler. Exemple
(données inventées) : `src/dashboard/contrat/evenements-v1.json`.

| Clé | Type | Sens |
|---|---|---|
| `schema_version` | `1` | la page refuse toute autre version |
| `generated_at` | heure | instant de lecture |
| `disponible` | booléen | faux quand la table `evenements` n'existe pas (collecte non installée) |
| `evenements` | objets | `id`, `date` (heure UTC `…Z`), `titre`, `categorie`, `source`, `lien` (`null` ou URL `http(s)`) |

- **Ordre et borne.** Du plus récent au plus ancien, 1000 lignes au plus. La page filtre par
  texte et par catégorie ; l'API ne prend aucun paramètre.
- **Catégories.** `manifestation`, `loi`, `prix`, `bourse`, `greve`, `autre` ; toute autre
  valeur sort en `autre`.
- **Lien.** Seuls les schémas `http` et `https` sortent : un `javascript:` deviendrait un lien
  actif dans la page.
- Même règle d'en-têtes que `/api/tableau` (`ETag` sans `generated_at`, `304`).

## 8. Variables d'environnement

| Variable | Utilisée par | Valeur par défaut (dev) |
|---|---|---|
| `KAFKA_BOOTSTRAP` | producer, streaming | `kafka:9092` (hôte : `127.0.0.1:29092`) |
| `KAFKA_TOPIC` | producer, streaming | `raw-posts` |
| `KEYWORDS_FILE` | producer | `/app/keywords.txt` |
| `PRODUCER_SOURCE`, `PRODUCER_RATE` | producer | `jetstream`, `5` (posts/s, mode `synthetic`) |
| `LEAK_MARKER` | producer (mode `synthetic`) | mot-témoin du contrôle de non-fuite (voir « Où disparaît chaque donnée ») |
| `CURSOR_FILE` | producer | `/data/cursor.json` (volume nommé, facultatif) |
| `S3_ENDPOINT` | streaming | `http://minio:9000` |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | streaming | compte de service `pipeline` |
| `S3_BUCKET_SCORES`, `S3_BUCKET_CHECKPOINTS` | streaming | `scores`, `checkpoints` |
| `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT` | streaming, dashboard-api | `clickhouse`, `8123` |
| `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD` | streaming, dashboard-api | `pipeline` / `dashboard` + `infra/.env` |
| `CLICKHOUSE_DB` | streaming, dashboard-api | `sae` |
| `LEXIQUE_DIR` | producer (`synthetic`), streaming, dashboard-api | `/app/lexique` ; `/opt/lexique` ; `/app/lexique` |
| `FENETRE_MINUTES`, `TRIGGER_SECONDS`, `WATERMARK_MINUTES` | streaming | `5`, `30`, `10` |
| `DASHBOARD_SEUIL_DEFAUT`, `FRAICHEUR_OK_MIN`, `FRAICHEUR_ALERTE_MIN` | dashboard-api | `20`, `5`, `30` |
| `DASHBOARD_BANDEAU` | dashboard-api | vide (aucun bandeau) |
| `SAE_CORPUS_DIR` | training (poste local) | dossier du corpus, hors dépôt |
| `SAE_GPU_HOTE` | training (`distant/`) | `utilisateur@hôte` de la machine GPU, jamais versionné |

`infra/.env.example` est versionné ; `infra/.env` ne l'est pas. Aucun mot de passe de
production dans le dépôt.

## 9. Où disparaît chaque donnée

| Donnée | Kafka (≤ 1 h 10) | Mémoire Spark | Checkpoint | MinIO `scores` | ClickHouse | Dashboard | Journaux |
|---|---|---|---|---|---|---|---|
| `did`, `rkey`, `cid`, `reply`, `embed` | présent | supprimé à l'étape 1 | non | non | non | non | non |
| texte du post | présent | jeté après le scoring ; copie nettoyée dans les fichiers shuffle des workers (voir « Limites déclarées ») | hash SHA-256 (1 jour) | non | non | non | non |
| heure précise (`time_us`) | présente | jusqu'à la latence | non | fenêtre de 5 min | fenêtre de 5 min | fenêtre | non |
| scores par cible | — | oui | non | 30 jours | 365 jours | oui | compteurs seuls |
| croisements agrégés (cible × stance × sentiment × émotion × thème × scoreur, par fenêtre) | — | oui | non | 30 jours (lignes) | 365 jours (`croisements_fenetre`) | oui, sommes par entité seulement (« JSON `tableau`, version 4 ») : `posts` pour les thèmes, `occurrences` pour les émotions | non |
| adjectifs du lexique fermé (cible × stance × adjectif, par fenêtre) | — | oui | non | non | 365 jours (`adjectifs_fenetre`) | oui, au moins 3 posts par (entité, stance, adjectif) | non |

**Contrôle de non-fuite.** Le producteur `synthetic` insère des marqueurs reconnaissables (un
`did` fictif, un mot-témoin dans le texte). Après un essai, un script cherche ces marqueurs
dans les objets MinIO (checkpoints compris), dans les tables ClickHouse et dans les journaux de
chaque conteneur : zéro occurrence attendue. Ce contrôle prouve la slide 5 (« logs, checkpoints,
dashboards »).

## 10. Pseudonymisation

Le Livrable 1 v1.3 interdit tout pseudonyme en stockage, même haché (M1, M2). Le POC n'en
produit aucun. Un compteur d'auteurs distincts exigerait une dérogation à M1 et M2 : clé HMAC
propre à chaque fenêtre, jamais écrite, et agrégat de type HyperLogLog dont seul le nombre
sortirait. Cette extension est hors POC et soumise à une nouvelle version du L1.

## 11. Limites déclarées

- **At-least-once.** Pas de committer S3 ni de Delta Lake : un micro-lot rejoué après une panne
  double les lignes MinIO et les compteurs ClickHouse. Le `rename` S3 n'est pas atomique.
- **MinIO.** La distribution de l'image communautaire a changé fin 2025 ; l'image épinglée et
  ses limites sont consignées dans `infra/AGENTS.md`.
- **Scoreur à règles.** Couverture faible de la stance ; aucun résultat n'est une mesure du
  modèle (Livrable 3).
- **Biais de la source.** Les utilisateurs de Bluesky ne représentent pas l'électorat ; le
  corpus penche à gauche (Livrable 1, R5).
- **Poste de développement.** Les durées observées sur le poste de l'utilisateur sont
  indicatives. Aucune campagne de `mesures/` n'a lieu ici.
- **Kafka sans authentification** (réseau Docker interne, hôte en `127.0.0.1`).
- **Fichiers shuffle.** Les workers Spark écrivent leurs données intermédiaires dans `/tmp` de
  leur conteneur. Ces fichiers contiennent le texte nettoyé (sans auteur, handle, URL ni `did`).
  Constat du 28/10/2026 sur la pile locale : un mot-témoin injecté est retrouvé dans un fichier
  shuffle du worker 1, et les plus anciens fichiers présents ont 5 heures. Le même mot-témoin est
  absent de MinIO, de ClickHouse, des checkpoints et des journaux. La pile de l'école n'a pas été
  contrôlée. Le chiffrement des fichiers temporaires (`spark.io.encryption.enabled`) n'est pas
  activé.

## 12. Contrat du modèle : `src/training/`

Deux modèles affinés depuis `almanach/camembert-base`, un par tâche : `stance` (paire nom de la
cible, texte → `pour`, `contre`, `neutre`, `mention`, `ambigu`) et `emotion` (texte → étiquettes
de `annotation/schema.yaml`). Entraînement hors cluster (slide 6), sur le silver seul pour
l'instant : un résultat silver est un test de fumée, pas une mesure (`training/AGENTS.md`).

Un **run** est un dossier, unique interface entre `modele/`, `distant/` et le chargement
par `streaming/` (scoreur à modèles CamemBERT) :

```
<run>/                    nom : <tache>-<AAAAMMJJ-HHMM>, sous $SAE_CORPUS_DIR/modeles/
  model/                  modèle et tokenizer Hugging Face (save_pretrained, safetensors)
  modele.json             tache, etiquettes, base, entree {longueur_max, normaliser}, noms_cibles
  metriques.json          accuracy, f1_macro, par_classe {precision, rappel, f1, support},
                          matrice_confusion, effectifs, epoque_retenue, historique (par époque),
                          source ("silver"), mention, duree_s, materiel
  config_entrainement.json hyperparamètres, graine, versions (torch, transformers)
```

Ligne de commande (depuis `src/training/`), seule interface entre `modele/` et `distant/` :

```
python -m modele.entrainer --tache stance|emotion --corpus <dossier> --sortie <dossier des runs>
       [--base almanach/camembert-base] [--epoques 3] [--lot 16] [--lr 2e-5] [--longueur-max 256]
       [--plafond N] [--appareil auto|cpu|cuda] [--graine 2027] [--stance-regroupe-neutre]
```

`--corpus` contient `annotation/train_silver.jsonl` et `annotation/eval_fige.json` (garde-fou).
Le run est écrit dans `<sortie>/<tache>-<AAAAMMJJ-HHMM>/` ; la **dernière ligne** de la sortie
standard est son chemin absolu. Code de retour non nul en cas d'échec. La progression (époque,
perte, F1 de validation) va sur la sortie d'erreur, sans texte de post.

- Aucun texte de post dans `modele.json`, `metriques.json`, `config_entrainement.json` ni dans
  les journaux d'entraînement.
- Les poids ne sont jamais versionnés (`src/training/.gitignore`) ; le dossier d'un run reste sous
  `$SAE_CORPUS_DIR/modeles/` et suit la purge du corpus (M11).
- **Machine GPU.** Le corpus copié sur la machine GPU vit dans un seul dossier
  (`~/sae-data/corpus/`, droits 700) et est effacé dès le run rapatrié (`distant/`, commande
  `purger`). Adresse de la machine : variable `SAE_GPU_HOTE`, jamais dans le dépôt.
