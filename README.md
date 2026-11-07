# Sentiments Bluesky, présidentielle 2027

Ce projet collecte, traite en flux continu et affiche sur un tableau de bord les opinions et émotions exprimées sur Bluesky lors de l'élection présidentielle de 2027, sans conserver de données nominatives.

## Ce que fait le projet

Ce pipeline est réalisé en binôme dans un cadre d'école d'ingénieurs. Le dépôt ne contient ni corpus, ni modèle entraîné, ni livrable.

Le système ingère les publications de Bluesky via le flux Jetstream ou via un producteur synthétique. Un premier filtrage à la source ne retient que les créations de messages en français contenant des mots-clés ciblés. Les messages retenus transitent par un topic Kafka avant d'être traités par Spark Structured Streaming par micro-lots de 30 secondes et fenêtres de 5 minutes.

Le traitement calcule l'orientation d'opinion, le sentiment, les émotions et les thèmes. Deux méthodes de scoring coexistent : des règles fondées sur un lexique et des modèles de langue CamemBERT. Les scores détaillés sont écrits au format Parquet dans MinIO. Les agrégats par fenêtre temporelle sont insérés dans ClickHouse. Une interface web développée en React interroge une API Python en lecture seule pour afficher les indicateurs.

### Désidentification des données

La protection de la vie privée applique une désidentification dès l'entrée dans le moteur de streaming :

- Projection par liste blanche : à l'étape 1 du job Spark, un schéma strict écarte tous les identifiants d'auteur (did), identifiants de messages (rkey, cid, rev), informations de réponse (reply), contenus intégrés (embed), mentions et date de création client (createdAt). Seuls l'horodatage de réception, l'opération, la collection, le texte brut, les langues et les balises de facettes entrent dans le traitement.
- Nettoyage du texte : à l'étape 2, le système masque les adresses web, les identifiants d'utilisateurs (@handles) et les motifs d'identifiants décentralisés (did:), puis convertit le texte en minuscules non accentuées.
- Dédoublonnage anonyme : à l'étape 3, le dédoublonnage s'appuie sur l'empreinte SHA-256 du texte nettoyé dans la limite du filigrane de 10 minutes.
- Troncature temporelle et suppression du texte : à l'étape 6, l'horodatage précis est remplacé par le début de la fenêtre de 5 minutes après calcul de la latence. Le texte nettoyé est éliminé après le calcul des scores. Aucun texte n'est écrit dans MinIO, ClickHouse ou les journaux.
- Lexique fermé : pour les adjectifs associés aux cibles, le système limite les décomptes à une liste fermée de 200 adjectifs prédéfinis. Aucun mot libre du message n'est stocké en base.
- Absence totale de pseudonyme : aucun identifiant ni pseudonyme n'est conservé, y compris sous forme de hachage.
- Durées de rétention courtes : Kafka conserve les messages bruts pendant 1 heure au maximum. MinIO purge les scores individuels après 30 jours et les états de dédoublonnage après 1 jour. Les agrégats dans ClickHouse ont une durée de vie technique de 365 jours.
- Contrôle de non-fuite : un mot-témoin injecté dans le flux synthétique permet de vérifier l'absence de fuite dans les stockages et les journaux.

## État d'avancement

### Ce qui fonctionne

- Socle d'infrastructure local : configuration opérationnelle avec Kafka 3.9.2, MinIO, ClickHouse 25.8.33.6, Spark 3.5.8 avec 1 master et 2 workers.
- Ingestion : connecteur Jetstream et producteur synthétique avec filtrage de mots-clés selon 3 classes.
- Moteur de streaming : job Spark appliquant la projection PII, le nettoyage, le dédoublonnage, le calcul des agrégats par fenêtres de 5 minutes et l'écriture dans MinIO et ClickHouse.
- Scoring : scoreur par règles lexique-v1 et exécution de modèles CamemBERT pour la stance et l'émotion dans les exécuteurs Spark.
- Rejeu hors ligne : script de rejeu de corpus SQLite calculant les 6 tables d'agrégats ClickHouse avec garde-fou contre le double import.
- Restitution : API Python WSGI servant le schéma tableau en version 4 et le catalogue d'événements en version 1.
- Interface web : application React avec 4 vues (contraste, popularité, top 3, événement), gestion des thèmes clair et sombre, et palette validée sans échec.
- Entraînement : module d'entraînement hors cluster pour les modèles de stance et d'émotion.
- Vérification de la pile : script de contrôle de connectivité et de conformité de l'infrastructure.

### Ce qui n'est pas fait

- Absence de corpus, de modèle entraîné et de livrable dans le dépôt.
- Évaluation sur jeu annoté de référence (gold) : le modèle CamemBERT n'a pas encore été évalué sur le jeu gold ; seul le jeu silver y a été comparé. Le lot figé de 200 posts ne comporte aucune annotation humaine.
- Collecte des faits datés : la collecte automatique via flux RSS de presse n'est pas installée ; la table ClickHouse associée ne contient que des données synthétiques de test.
- Fichiers temporaires des workers Spark : les fichiers shuffle stockés dans le répertoire /tmp des conteneurs contiennent le texte nettoyé sans chiffrement.
- Sémantique de livraison : le pipeline fonctionne en mode at-least-once sans écriture transactionnelle S3 ni Delta Lake ; un rejeu de micro-lot double les métriques.
- Arbitrage règles et modèle : la cascade avec arbitrage et réorientation des désaccords vers une relecture humaine n'est pas implémentée.
- Vérification visuelle du tableau de bord : les tests sur navigateur en thème sombre, au format mobile de 390 pixels et sur la page événement ne sont pas finalisés.

## Architecture

- `docs/` : documentation technique, guides méthodologiques et diagrammes d'architecture.
- `infra/` : fichiers Docker Compose, configurations de Kafka, MinIO, ClickHouse et Spark, scripts de vérification et de déploiement distribué.
- `ressources/lexique/` : fichiers YAML contenant les référentiels d'entités, de stance, de thèmes, d'émotions et les 200 adjectifs du lexique fermé.
- `scripts/` : outils d'analyse lexicale, de rejeu de corpus, d'évaluation de modèles et de publication.
- `src/dashboard/` : code de l'interface utilisateur comprenant l'API Python en lecture seule (`api/`), le frontend React sous Nginx (`web/`) et les contrats de données JSON (`contrat/`).
- `src/ingestion/` : producteur assurant la collecte depuis Bluesky Jetstream ou la génération de données synthétiques avec filtrage par mots-clés.
- `src/streaming/` : job Spark Structured Streaming assurant la désidentification, le scoring et l'écriture dans MinIO et ClickHouse.
- `src/training/` : scripts d'annotation, de préparation des données et d'entraînement hors cluster des modèles CamemBERT.
- `tests/` : tests d'intégration portant sur l'analyse de lexique, l'entrée des modèles et le rejeu de corpus.

## Prérequis

- Docker et Docker Compose.
- Python 3.12 ou 3.13.
- Outil uv pour la gestion des environnements Python.
- Node.js avec npm pour le frontend React.
- Mémoire vive : environ 12,6 Gio alloués aux conteneurs, poste de 16 Gio requis.
- Ports hôtes disponibles liés sur 127.0.0.1 : 29092 (Kafka), 19000 et 19001 (MinIO), 18123 (ClickHouse), 18080, 18081 et 18082 (Spark master et workers), 14040 (Spark streaming) et 8501 (Dashboard Nginx).

## Installation et exécution

- Configuration de l'environnement :
```bash
cp infra/.env.example infra/.env
```

- Démarrage du socle d'infrastructure (Kafka, MinIO, ClickHouse, Spark master et workers) :
```bash
docker compose -f infra/docker-compose.yml up -d
```

- Démarrage de l'ensemble du pipeline (socle, producteur, streaming, API et tableau de bord) :
```bash
docker compose -f infra/docker-compose.yml --profile pipeline up -d
```

- Contrôle de la pile :
```bash
python3 infra/verifier.py
```

- Rejeu d'un corpus SQLite dans ClickHouse :
```bash
uv run --python 3.12 --extra-index-url https://download.pytorch.org/whl/cpu \
  --with-requirements src/streaming/requirements-dev.txt --with clickhouse-connect \
  python scripts/rejouer_corpus.py \
  --db <base.db> --depuis 2026-10-12T00:00:00Z --avant 2026-10-19T16:25:00Z \
  --run-stance <dossier-run-stance> --run-emotion <dossier-run-emotion> \
  [--agregats-sortie <dossier>] [--importer --env <infra/.env>] \
  [--tables <table,table>] [--taches <n>]
```

- Entraînement d'un modèle de stance ou d'émotion hors cluster :
```bash
python -m modele.entrainer --tache stance|emotion --corpus <dossier> --sortie <dossier des runs> \
       [--base almanach/camembert-base] [--epoques 3] [--lot 16] [--lr 2e-5] [--longueur-max 256] \
       [--plafond N] [--appareil auto|cpu|cuda] [--graine 2027] [--stance-regroupe-neutre]
```

- Validation de la palette de couleurs du tableau de bord :
```bash
python3 src/dashboard/web/outils/valider_palette.py
```

## Tests

- Tests de l'analyse du lexique :
```bash
uv run --with pyyaml --with pytest pytest tests/test_analyse_lexique.py
```

- Analyse du lexique sur un corpus :
```bash
uv run --with pyyaml python scripts/analyse_lexique.py --db CORPUS.db --sections regles
```

- Tests du rejeu de corpus :
```bash
pytest tests/test_rejouer_corpus.py
```

- Tests du module de comparaison règles et modèles :
```bash
uv run --python 3.12 --no-project --extra-index-url https://download.pytorch.org/whl/cpu \
  --with-requirements src/training/requirements-train.txt --with pandas \
  python -m pytest -q tests/test_comparer_regex_modele.py
```

- Exécution de la comparaison entre règles et CamemBERT sur le silver :
```bash
uv run -q --python 3.12 --no-project \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  --with-requirements src/training/requirements-train.txt --with pandas \
  python scripts/comparer_regex_modele.py \
  --corpus "$SAE_CORPUS_DIR" \
  --run-stance stance-20261019-1636 --run-emotion emotion-20261019-1700 \
  --sortie "$SAE_CORPUS_DIR/comparaisons/regex-vs-camembert-2026-10-19.json"
```

- Évaluation du silver contre le gold :
```bash
python3 -I src/training/comparer_gold_silver.py --corpus <dossier du corpus>
```

### Scores mesurés des modèles

Tous les scores ci-dessous proviennent de documents mesurés et consignés :

- Validation sur le corpus silver (runs stance-20261019-1636 sur 516 exemples et emotion-20261019-1700 sur 313 exemples) :
  - Stance règles : accuracy 0,010, F1 macro 0,008, couverture 0,016 (8 sur 516), F1 macro couvert 0,278.
  - Stance CamemBERT : accuracy 0,657, F1 macro 0,369, couverture 1,000, F1 macro couvert 0,369.
  - Émotion règles : accuracy 0,010, F1 macro 0,032, couverture 0,010 (3 sur 313), F1 macro couvert 1,000.
  - Émotion CamemBERT : accuracy 0,626, F1 macro 0,194, couverture 1,000, F1 macro couvert 0,194.
- Accord silver contre gold (30 posts, 45 lignes de cibles, 1 annotateur) :
  - Pertinence : 21 sur 30, soit 70,0 %.
  - Entité citée commune : 41 sur 45, soit 91,1 %.
  - Entité et stance identiques : 13 sur 45, soit 28,9 %.
  - Émotion sur 26 posts pertinents : 13 sur 26, soit 50,0 %.

## Choix techniques

- Projection PII et désidentification en amont dans Spark Structured Streaming :
  - Raison : Respecter l'interdiction de stocker des données nominatives ou des pseudonymes, même hachés.
  - Compromis : Suppression définitive du texte et des identifiants empêchant tout recalcul a posteriori sans source externe.
- Double approche de scoring associant règles lexicales et modèle CamemBERT :
  - Raison : Les règles de confiance haute ont une précision d'environ 90 % sur 67 résultats relus, mais ne décident qu'environ 3 % des posts du corpus du 12 octobre 2026. CamemBERT traite toutes les entrées.
  - Compromis : Consommation mémoire accrue de 4 Gio par worker pour charger les modèles PyTorch et rupture de série temporelle lors d'un changement de scoreur.
- Moteur analytique ClickHouse avec tables SummingMergeTree :
  - Raison : Permettre des lectures d'agrégats par sommation incrémentale à chaque micro-lot.
  - Compromis : Fonctionnement en mode at-least-once : l'absence d'écriture atomique sur S3 double les agrégats en cas de reprise sur incident d'un micro-lot.
- Rétention tampon de Kafka limitée à 1 heure :
  - Raison : Éviter l'accumulation de messages contenant des données personnelles dans le système de messagerie.
  - Compromis : En cas d'interruption de Spark pendant plus de 1 heure, les messages non consommés sont perdus.
- Composants graphiques SVG et HTML développés sans bibliothèque externe :
  - Raison : Maîtriser l'accessibilité, les ratios de contraste OKLCH et le double encodage visuel (forme et couleur) sans dépendance tierce.
  - Compromis : Effort de développement direct pour chaque visualisation.

## Limites

- Le dépôt ne contient ni corpus, ni modèle entraîné, ni livrable.
- Représentativité et biais de la source : les utilisateurs de Bluesky ne reflètent pas le corps électoral français et penchent vers la gauche.
- Fichiers temporaires des workers : les fichiers shuffle écrits dans /tmp par Spark contiennent le texte nettoyé sans chiffrement.
- Traitement at-least-once : sans committer S3 ni Delta Lake, la réexécution d'un micro-lot double les comptes dans MinIO et ClickHouse.
- Évaluation statistique restreinte : les performances de CamemBERT sont calculées sur un jeu synthétique silver généré par LLM. Le jeu gold ne comporte que 30 exemples annotés par 1 personne.
- Sécurité réseau locale : le courtier Kafka fonctionne sans authentification au sein du réseau Docker local.
- Données d'événements non connectées : le flux d'actualités réelles n'est pas alimenté en production.

## Licence

À définir.
