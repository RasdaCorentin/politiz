FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY ingestion.py .

# Utilisateur non-root. Le compose impose l'uid/gid de l'hôte (COLLECTE_UID/GID)
# pour écrire dans le dossier de données monté.
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin collecte \
    && mkdir /data && chown collecte /data
USER collecte

# keywords.txt est monté en lecture seule par le compose (/app/keywords.txt).
CMD ["python", "ingestion.py", "--db", "/data/bluesky_posts.db", \
     "--keywords", "/app/keywords.txt", "--heartbeat", "/tmp/heartbeat"]
