# Rejeu d'un corpus par le job Spark

Le rejeu score une base SQLite de posts avec le code du job (`src/streaming/job.py`) et insère les
agrégats des six tables de `sae.*` (tables ClickHouse du contrat), ou de celles choisies. Il sert à remplir le tableau de bord avec des données déjà
collectées, sans attendre le flux temps réel. Script : `scripts/rejouer_corpus.py`.

## Commande

```bash
uv run --python 3.12 --extra-index-url https://download.pytorch.org/whl/cpu \
  --with-requirements src/streaming/requirements-dev.txt --with clickhouse-connect \
  python scripts/rejouer_corpus.py \
  --db <base.db> --depuis 2026-10-12T00:00:00Z --avant 2026-10-19T16:25:00Z \
  --run-stance <dossier-run-stance> --run-emotion <dossier-run-emotion> \
  [--agregats-sortie <dossier>] [--importer --env <infra/.env>] \
  [--tables <table,table>] [--taches <n>]
```

- Sans `--importer` : affiche les comptes seulement.
- Avec `--importer` : vérifie d'abord l'absence de lignes dans la période pour chaque table à
  importer, insère les agrégats, puis compare les sommes lues aux sommes calculées.
- `--tables adjectifs_fenetre` : importe ces tables seulement. Sert à ajouter une table à une
  période déjà importée sans doubler les autres.
- `--taches <n>` : tâches Spark simultanées, 2 cœurs chacune (défaut 2). Chaque tranche est
  répartie en `n` partitions.
- `--agregats-sortie <dossier>` : écrit `agregats.json` (comptes et clés, aucun texte).
- `--depuis-agregats <dossier>` : relit ce fichier et importe sans rescorer.
- Le mot de passe est lu dans `CLICKHOUSE_PIPELINE_PASSWORD` du fichier `--env`. Il n'est jamais
  affiché.

## Ce qui est identique au job

- Projection et nettoyage : `pii.projeter`, `pii.nettoyer` (liste blanche, URL et `@handles`
  masqués, minuscules sans accents).
- Scoreur : `job.traiter_micro_lot`, donc `scoring.scorer_serie` et les modèles du « Scoreur à modèles ».
- Agrégation : même fenêtre de 5 minutes (troncature de `time_us`), mêmes six tables, même filtre fin.
- Les lots se somment : traiter par tranches de 4 000 posts donne le même résultat qu'un seul appel
  (test `tests/test_rejouer_corpus.py`).

## Ce qui diffère

| Point | Job | Rejeu |
|---|---|---|
| Temps d'événement | `time_us` (réception Jetstream) | `created_at` de la base, en microsecondes |
| Dédoublonnage | `dropDuplicatesWithinWatermark`, 10 min | premier post par hash sur toute la période (le mode batch ne propose pas le filigrane) |
| Latence | calculée | nulle (`somme_latence_ms = 0`) : un rejeu ne mesure rien |
| `derniere_maj` | heure du micro-lot | fin de la fenêtre de 5 min |
| Langue | champ `langs` de l'événement | `fr` forcé : la base ne garde pas la langue |
| MinIO | lignes froides en Parquet | aucune écriture |
| Filtre de collecte | producteur (`langs` contenant `fr`) | collecteur de la base, autre code |

Conséquence du dédoublonnage : les doublons espacés de plus de 10 minutes sont retirés par le
rejeu, alors que le job les compte. Le rejeu en compte 638 sur le corpus du 19/10 (approximation :
écart à l'occurrence précédente de même hash, mesuré).

## Garde-fou contre le double import

`sae.*` se somme. Un second import doublerait les comptes. Le script refuse donc l'import si une
table à importer a déjà une ligne dans la période. Il lit et insère `pipeline_fenetre` en premier :
un import interrompu laisse une trace que le garde-fou détecte. Avec `--tables`, il ne lit que les
tables choisies.

La borne `--avant` tombe sur une frontière de fenêtre (16 h 25). La fenêtre 16 h 25 du flux
temps réel est déjà dans `sae.pipeline_fenetre`. Avec 16 h 26, le garde-fou refuserait l'import.

## Résultat du rejeu du 19/10 (mesuré)

Période : 2026-10-12T00:00Z à 2026-10-19T16:25Z (exclue). Modèles : stance
`stance-20261019-1636`, émotion `emotion-20261019-1700`.

| Mesure | Valeur |
|---|---|
| Posts lus | 26 029 |
| Après nettoyage (fr, texte non vide) | 26 010 |
| Doublons espacés de plus de 10 min (approximation) | 638 |
| Scorés (après dédoublonnage) | 24 259 |
| Gardés par le filtre fin | 22 870 |
| Durée du calcul | 7 077 s (environ 2 h) |
| Débit | 3,2 à 3,6 posts/s, une tâche à la fois (une tranche tenait dans une partition) |

Sommes importées (lues dans `sae.*`, égales aux sommes calculées) :

| Table | Somme de `nb_posts` | Lignes |
|---|---|---|
| `pipeline_fenetre` | 24 259 | 2 082 |
| `cibles_fenetre` | 26 452 | 17 255 |
| `posts_fenetre` | 22 870 | 7 153 |
| `themes_fenetre` | 27 992 | 10 701 |
| `croisements_fenetre` | 35 639 | 31 863 |

`scoreur` : `camembert:stance-20261019-1636+emotion-20261019-1700` (tout le rejeu).

## Protection des données

- Aucun texte de post ni identifiant ne sort du script : ni dans la sortie, ni dans les agrégats.
  Les erreurs n'affichent que le type d'exception.
- La base source reste hors dépôt. Elle suit la purge de la collecte (30 jours au plus).
- `agregats.json` contient des comptes par fenêtre et par libellé. Il reste hors dépôt.

## Limites

- Hypothèse `langs = fr` : la base ne conserve pas la langue.
- Temps d'événement `created_at`, pas `time_us` : un post créé avant 16 h 25 et reçu après
  16 h 26 peut apparaître dans les deux sources.
- Dédoublonnage sur toute la période : écart au job (voir plus haut).
- Latence absente : `somme_latence_ms = 0` pour toutes les lignes du rejeu.
  Le « Délai moyen de traitement » du tableau de bord est donc tiré vers zéro sur toute période
  qui contient le rejeu.
- Chaque tâche simultanée charge les modèles actifs (environ 1,2 Gio pour les deux runs).
  `spark.task.cpus=2` : 2 threads torch par tâche, `2 × --taches` cœurs au total.

## Tests manuels avant fusion

1. `uv run ... pytest tests/test_rejouer_corpus.py` : 10 tests verts.
2. Dans le tableau de bord (127.0.0.1:8501), période 7 j : vérifier à l'écran que les courbes couvrent
   la fenêtre `periode.debut` renvoyée par l'API (13/10 à 04 h UTC le 20/10).
3. `curl -s "http://127.0.0.1:8501/api/tableau?periode=7j"` : code 200, `etat.fraicheur` à `ok`.
