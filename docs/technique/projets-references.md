# Projets Git de référence — Sujet 1 (Suivi des sentiments)

Dépôts open source classés par brique du pipeline. On s'en inspire pour les patterns. On ne les
copie pas : le défi de la SAÉ est d'intégrer toute la chaîne (Livrable 0, slide 2).

## 1. Ingestion — Bluesky → Kafka

| Dépôt | Ce qu'on en retient |
| --- | --- |
| [arjungop/bluesky-sentiment-pipeline](https://github.com/arjungop/bluesky-sentiment-pipeline) | **Le plus proche de notre sujet.** Producteur Python branché sur Jetstream, filtre langue et mots-clés, envoi vers Kafka. Puis Spark Structured Streaming, Parquet et Grafana. |
| [Sebasalazaro/FakeNewsDetection](https://github.com/Sebasalazaro/FakeNewsDetection) | Producteur Jetstream minimal (WebSocket → Kafka, configuration par variables d'environnement). Bon point de départ. |
| [chenlamchan/Bluesky-StreamPulse](https://github.com/chenlamchan/Bluesky-StreamPulse) | Lakehouse Kafka + Flink + **MinIO**. Montre comment normaliser les événements Jetstream et les enrichir par ML en asynchrone. Flink est hors socle : on garde seulement le schéma d'événement. |
| [graze-social/grazer](https://github.com/graze-social/grazer/blob/main/app/jetstream.py) | Consumer Jetstream asynchrone en Python : **sauvegarde du curseur, batching, reconnexion**. À reprendre pour fiabiliser notre producteur. |
| [hrbrmstr/skygrep](https://github.com/hrbrmstr/skygrep) | Consumer Jetstream léger avec filtre regex vers Kafka (Deno/TypeScript). Référence secondaire. |

## 2. Socle : Kafka + Spark Streaming + MinIO + ClickHouse (+ dashboard)

| Dépôt | Ce qu'on en retient |
| --- | --- |
| [Pizz0x/Retail-Data-Pipeline](https://github.com/Pizz0x/Retail-Data-Pipeline) | **Même socle que la SAÉ** : Kafka → Spark Streaming → MinIO (checkpoints en S3, exactly-once, DLQ) → ClickHouse (connecteur clickhouse-spark) → Grafana. Meilleur modèle pour notre `docker-compose.yml`. |
| [Ducdata1808/music-streaming-data-pipeline](https://github.com/Ducdata1808/music-streaming-data-pipeline) | Kafka → PySpark → Parquet sur MinIO → ClickHouse, sous Docker Compose, avec une app Streamlit. |
| [kanhaiya-gupta/Media_Publishing](https://github.com/kanhaiya-gupta/Media_Publishing) | Kafka → Spark Streaming → Delta Lake sur MinIO + ClickHouse, avec CI/CD GitHub Actions. Utile pour l'exactly-once sur S3. |
| [MarkPhamm/local_streaming_pipeline](https://github.com/MarkPhamm/local_streaming_pipeline) | Kafka → Spark → ClickHouse → API et dashboard, 100 % local avec `run.sh`. Bonne documentation. Pas de MinIO. |
| [kanak-b/thousand-wishes](https://github.com/kanak-b/thousand-wishes) | Kafka + Spark Streaming + MinIO + Grafana sous Docker. Postgres remplace ClickHouse. |

## 3. IA : sentiment français + inférence dans Spark

| Dépôt / ressource | Ce qu'on en retient |
| --- | --- |
| [TheophileBlard/french-sentiment-analysis-with-bert](https://github.com/TheophileBlard/french-sentiment-analysis-with-bert) | **Base de notre entraînement.** Affine CamemBERT sur le jeu Allociné (97,4 % d'accuracy). Modèle [tblard/tf-allocine](https://huggingface.co/tblard/tf-allocine) (TensorFlow/Keras) et jeu `allocine` sur Hugging Face. |
| [visalkao/sentiment-analysis-french](https://huggingface.co/visalkao/sentiment-analysis-french) | CamemBERT prêt à l'emploi (environ 96 %). Candidat pour l'inférence sans réentraînement. |
| [ac0hik/Sentiment_Analysis_French](https://huggingface.co/ac0hik/Sentiment_Analysis_French) | CamemBERT entraîné sur des tweets français, 3 classes (positif, négatif, neutre). Plus proche de nos posts qu'Allociné. |
| [NVIDIA/cudf-spark-examples — Spark-DL dl_inference](https://github.com/NVIDIA/cudf-spark-examples/blob/main/examples/ML%2BDL-Examples/Spark-DL/dl_inference/README.md) | Notebooks d'inférence de sentiment Hugging Face **dans Spark** avec `predict_batch_udf` (Spark 3.4+). Pattern officiel pour l'inférence dans les workers. |
| [pySpark `predict_batch_udf` (doc officielle)](https://apache.github.io/spark/api/python/reference/api/pyspark.ml.functions.predict_batch_udf.html) | Référence de l'API qui charge le modèle une fois par worker Python. |
| [NavinAnik/pyspark-gpu-batch-inference](https://github.com/NavinAnik/pyspark-gpu-batch-inference) | DistilBERT (Hugging Face) via `pandas_udf` (Arrow) sur PySpark. Pattern Parquet → inférence par lots. |
| [LegenQS/Real-time-Hashtag-generation-for-tweets](https://github.com/LegenQS/Real-time-Hashtag-generation-for-tweets/blob/main/spark_receiver.ipynb) | Modèle PyTorch en `pandas_udf` sur un **flux** (broadcast + Arrow `maxRecordsPerBatch`). Le plus proche de notre streaming. |
| [Akashsingh310/spark-ai](https://github.com/Akashsingh310/spark-ai) | Wrapper `ai.sentiment(col)` sur PySpark. Idée d'API simple, non indispensable. |

## À étudier en premier

1. **[arjungop/bluesky-sentiment-pipeline](https://github.com/arjungop/bluesky-sentiment-pipeline)** — couvre presque tout notre sujet (Bluesky, sentiment, Spark, Grafana).
2. **[Pizz0x/Retail-Data-Pipeline](https://github.com/Pizz0x/Retail-Data-Pipeline)** — reproduit le socle unifié (Kafka, Spark, MinIO, ClickHouse, Grafana, checkpoints S3).
3. **[TheophileBlard/french-sentiment-analysis-with-bert](https://github.com/TheophileBlard/french-sentiment-analysis-with-bert)** — couvre l'entraînement du modèle de sentiment français.
4. **[LegenQS/Real-time-Hashtag-generation-for-tweets](https://github.com/LegenQS/Real-time-Hashtag-generation-for-tweets/blob/main/spark_receiver.ipynb)** + **[NVIDIA dl_inference](https://github.com/NVIDIA/cudf-spark-examples/blob/main/examples/ML%2BDL-Examples/Spark-DL/dl_inference/README.md)** — montrent l'inférence dans Spark Structured Streaming.