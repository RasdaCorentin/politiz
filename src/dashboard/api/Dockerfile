# API du tableau de bord : modules Python du dossier, dépendances épinglées (requirements.txt).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LEXIQUE_DIR=/app/lexique

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt \
 && useradd --system --no-create-home --shell /usr/sbin/nologin api

# Code possédé par root, lu par l'utilisateur `api` : le processus ne peut pas le modifier.
WORKDIR /app
COPY *.py /app/
USER api

EXPOSE 8000

# Interroge /api/sante, qui touche ClickHouse : « sain » signifie « capable de répondre ».
HEALTHCHECK --interval=15s --timeout=3s --retries=3 --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/sante', timeout=2)"]

# Système de fichiers en lecture seule possible : Gunicorn écrit ses fichiers temporaires dans /tmp
# (tmpfs). Le socket de contrôle est désactivé : il n'est pas utilisé ici.
CMD ["gunicorn", "--bind=0.0.0.0:8000", "--workers=2", "--access-logfile=-", "--no-control-socket", "app:app"]
