#!/bin/sh
# Déploiement de la variante distribuée, lancé depuis le poste de commande (infra/distribue/AGENTS.md).
#
#   deployer.sh envoyer <1|2|c>    copie le dépôt dans /opt/sae-data (sans .git, infra/.env, caches)
#   deployer.sh demarrer <1|2|c>   docker compose up -d --build sur la machine
#   deployer.sh arreter <1|2|c>    docker compose stop sur la machine (données conservées)
#   deployer.sh etat               docker compose ps sur les trois machines
#
# Accès, par variables d'environnement (aucune adresse ni compte dans ce fichier) :
#   SAE_SSH_1, SAE_SSH_2, SAE_SSH_C   commande ssh complète, pour les commandes distantes
#                                     (ex. « ssh -J saut utilisateur@hôte »)
#   SAE_RSYNC_RSH_1, _2, _C           la même commande ssh, sans destination, pour rsync (-e)
#   SAE_CIBLE_1, _2, _C               destination rsync, ex. « utilisateur@adresse »
#   SAE_SUDO_C                        élévation pour docker sur C, ex. « sudo -n ». Vide sur les VM :
#                                     koda est dans le groupe docker, aucune commande n'y demande sudo.
# Prérequis sur chaque machine : /opt/sae-data existe et appartient à l'utilisateur ssh. rsync est
# utilisé s'il est installé ; à défaut, envoyer se rabat sur tar (même périmètre, sans --delete natif).
set -eu

RACINE=$(cd "$(dirname "$0")/../.." && pwd)
DEST=/opt/sae-data

usage() {
    echo "usage : $0 envoyer|demarrer|arreter <1|2|c>  |  $0 etat" >&2
    exit 2
}

# Renseigne CIBLE_SSH, CIBLE_SUDO, FICHIER, CIBLE_RSH et CIBLE_HOTE pour la machine donnée.
cible() {
    case "$1" in
        1) CIBLE_SSH=${SAE_SSH_1:-}; CIBLE_SUDO=${SAE_SUDO_1:-}; CIBLE_RSH=${SAE_RSYNC_RSH_1:-}
           CIBLE_HOTE=${SAE_CIBLE_1:-}; FICHIER=compose-1.yml ;;
        2) CIBLE_SSH=${SAE_SSH_2:-}; CIBLE_SUDO=${SAE_SUDO_2:-}; CIBLE_RSH=${SAE_RSYNC_RSH_2:-}
           CIBLE_HOTE=${SAE_CIBLE_2:-}; FICHIER=compose-2.yml ;;
        c|C) CIBLE_SSH=${SAE_SSH_C:-}; CIBLE_SUDO=${SAE_SUDO_C:-}; CIBLE_RSH=${SAE_RSYNC_RSH_C:-}
           CIBLE_HOTE=${SAE_CIBLE_C:-}; FICHIER=compose-c.yml ;;
        *) echo "machine inconnue : $1 (1, 2 ou c)" >&2; exit 2 ;;
    esac
}

# Affiche « oui » si rsync est installé sur la machine distante, « non » sinon.
rsync_distant() {
    $CIBLE_SSH 'command -v rsync >/dev/null 2>&1 && echo oui || echo non'
}

# Envoi sans rsync : vide $DEST (sauf infra/distribue/.env), puis extrait une archive tar envoyée
# par ssh avec les mêmes exclusions que rsync. Contrairement à rsync --delete, ce vidage retire aussi
# les chemins exclus côté envoi (infra/.env, data/, *.db) déjà présents sur la machine.
# Les motifs ancrés à la racine (/.git, /data…) utilisent --anchored ; les autres valent à tous niveaux.
envoyer_tar() {
    $CIBLE_SSH "cd $DEST && mkdir -p infra/distribue && find . -mindepth 1 -maxdepth 1 ! -name infra -exec rm -rf {} + && find infra -mindepth 1 -maxdepth 1 ! -name distribue -exec rm -rf {} + && find infra/distribue -mindepth 1 -maxdepth 1 ! -name .env -exec rm -rf {} +"
    tar -C "$RACINE" --anchored --no-wildcards-match-slash \
        --exclude=./.git --exclude=./.claude --exclude=./infra/.env --exclude=./data \
        --exclude='./mesures/*/brut' \
        --no-anchored \
        --exclude=node_modules --exclude=__pycache__ --exclude=.venv --exclude='*.pyc' \
        --exclude='*.db' --exclude='*.sqlite' --exclude='*.sqlite3' \
        -cf - . | $CIBLE_SSH "cd $DEST && tar -xf -"
}

envoyer() {
    cible "$1"
    if [ -z "$CIBLE_RSH" ] || [ -z "$CIBLE_HOTE" ]; then
        echo "SAE_RSYNC_RSH pour la machine $1 et SAE_CIBLE pour la machine $1 doivent être définies" >&2
        exit 2
    fi
    if [ ! -f "$RACINE/infra/distribue/.env" ]; then
        echo "infra/distribue/.env absent : le créer depuis .env.example" >&2
        exit 2
    fi
    REP=$(rsync_distant) || { echo "connexion ssh impossible vers la machine $1" >&2; exit 1; }
    echo "envoi du dépôt vers la machine $1"
    if [ "$REP" = oui ]; then
        # --delete retire de $DEST ce qui n'existe plus localement. Les exclusions ancrées à la racine
        # du dépôt protègent le corpus et les fichiers locaux : rien de tout cela ne part.
        rsync -a --delete \
            --exclude=/.git --exclude=/.claude --exclude=/infra/.env \
            --exclude=node_modules --exclude=__pycache__ --exclude=.venv --exclude='*.pyc' \
            --exclude='*.db' --exclude='*.sqlite' --exclude='*.sqlite3' \
            --exclude=/data --exclude='/mesures/*/brut' \
            -e "$CIBLE_RSH" \
            "$RACINE/" "$CIBLE_HOTE:$DEST/"
    else
        echo "rsync absent sur la machine $1 : envoi par tar"
        envoyer_tar
    fi
}

compose() {
    # $1 : sous-commande docker compose (up -d --build, stop, ps...)
    cible "$2"
    if [ -z "$CIBLE_SSH" ]; then
        echo "SAE_SSH_$2 non définie (commande ssh de la machine $2)" >&2
        exit 2
    fi
    $CIBLE_SSH "cd $DEST && ${CIBLE_SUDO:+$CIBLE_SUDO }docker compose -f infra/distribue/$FICHIER --env-file infra/distribue/.env --env-file infra/distribue/modeles.env $1"
}

etat() {
    for x in 1 2 c; do
        echo "== machine $x"
        compose ps "$x"
    done
}

[ $# -ge 1 ] || usage
action=$1
case "$action" in
    envoyer) [ $# -eq 2 ] || usage; envoyer "$2" ;;
    demarrer) [ $# -eq 2 ] || usage; compose "up -d --build" "$2" ;;
    arreter) [ $# -eq 2 ] || usage; compose "stop" "$2" ;;
    etat) [ $# -eq 1 ] || usage; etat ;;
    *) usage ;;
esac
