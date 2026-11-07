# Image des conteneurs Spark (master, workers, job de streaming).
# Base épinglée : Spark 3.5.8 (dropDuplicatesWithinWatermark exige >= 3.5.0), Java 17, Python 3.10.
FROM apache/spark:3.5.8-scala2.12-java17-python3-ubuntu

USER root

# Jars téléchargés au build et vérifiés par SHA-256 (jars.txt) : aucun --packages à l'exécution.
COPY jars.txt /tmp/jars.txt
RUN set -eux; \
    grep -v '^#' /tmp/jars.txt | while read -r sha path; do \
        [ -n "$sha" ] || continue; \
        curl -fsSL --retry 3 -o "/opt/spark/jars/$(basename "$path")" "https://repo1.maven.org/maven2/$path"; \
        echo "$sha  /opt/spark/jars/$(basename "$path")" | sha256sum -c -; \
    done; \
    rm /tmp/jars.txt

RUN pip install --no-cache-dir \
        numpy==1.26.4 pandas==2.2.2 pyarrow==16.1.0 pyyaml==6.0.2

# Modèles CamemBERT (scoreur à modèles du streaming). Versions de src/training/requirements-train.txt, sauf torch :
# roue CPU de l'index PyTorch (la roue PyPI tire CUDA et les nvidia-* : ~2 Go de plus).
# numpy est répété : transformers ne doit pas le remonter à 2.x (pandas/pyarrow ci-dessus).
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
        torch==2.14.1 \
    && pip install --no-cache-dir \
        numpy==1.26.4 transformers==5.19.0 tokenizers==0.23.3 \
        safetensors==0.8.0 huggingface-hub==2.2.0

COPY spark-defaults.conf /opt/spark/conf/spark-defaults.conf
COPY log4j2.properties /opt/spark/conf/log4j2.properties

ENV PYTHONPATH=/opt/streaming \
    PYSPARK_PYTHON=python3

# Répertoire de travail des workers (logs d'executors) : propriété de l'utilisateur spark.
RUN mkdir -p /opt/spark/work /opt/streaming && chown -R spark:spark /opt/spark/work

USER spark
WORKDIR /opt/spark
