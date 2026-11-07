#!/usr/bin/env python3
"""Peuple un ClickHouse JETABLE avec des agrégats INVENTÉS et crée le compte `dashboard` en lecture seule.

Aucune donnée réelle : les candidats sont des personnages fictifs, les volumes viennent d'un
générateur aléatoire à graine fixe. Le DDL de `sae` est celui des tables ClickHouse du contrat de
`docs/technique/contrats-poc.md`, copié à l'identique.

Scénarios :
    normal   --jours jours (35 par défaut) de fenêtres de 5 min, plusieurs candidats et camps, un candidat non classé ;
             adjectifs et catalogue d'événements fictifs
    evenement comme `normal`, plus un événement simulé il y a 5 jours à 18 h (Paris) : pic d'évaluations
             « contre » sur les candidats de droite, décroissant sur deux jours (page « Événement »)
    peu      quelques posts seulement (états « peu de données »)
    vide     tables vides (état « base vide »)
    perime   comme `normal`, mais le flux s'est arrêté il y a 2 h

Usage (ClickHouse d'essai sur 127.0.0.1:18223, compte administrateur du conteneur) :
    uv run --python 3.12 --with clickhouse-connect python outils/donnees_synthetiques.py \\
        --scenario normal --admin-user admin --admin-password admin-dev \\
        --lexique-out <dossier>

Refuse toute cible hors 127.0.0.1 / localhost : le script supprime et recrée les tables.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import random
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import clickhouse_connect

DDL = [
    "CREATE DATABASE IF NOT EXISTS sae",
    """CREATE TABLE IF NOT EXISTS sae.cibles_fenetre      -- popularité : par candidat ou parti
(
    fenetre_debut DateTime('UTC'),
    entite        LowCardinality(String),
    stance        LowCardinality(String),
    nb_posts      UInt64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(fenetre_debut)
ORDER BY (fenetre_debut, entite, stance)
TTL fenetre_debut + INTERVAL 365 DAY""",
    """CREATE TABLE IF NOT EXISTS sae.posts_fenetre       -- baromètre : ton et émotions, tous posts
(
    fenetre_debut DateTime('UTC'),
    sentiment     LowCardinality(String),
    emotion       LowCardinality(String),
    nb_posts      UInt64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(fenetre_debut)
ORDER BY (fenetre_debut, sentiment, emotion)
TTL fenetre_debut + INTERVAL 365 DAY""",
    """CREATE TABLE IF NOT EXISTS sae.themes_fenetre      -- un post compte dans chacun de ses thèmes
(
    fenetre_debut DateTime('UTC'),
    theme         LowCardinality(String),
    nb_posts      UInt64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(fenetre_debut)
ORDER BY (fenetre_debut, theme)
TTL fenetre_debut + INTERVAL 365 DAY""",
    """CREATE TABLE IF NOT EXISTS sae.pipeline_fenetre    -- volume, latence, fraîcheur
(
    fenetre_debut    DateTime('UTC'),
    derniere_maj     DateTime('UTC'),
    nb_posts         UInt64,
    somme_latence_ms UInt64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(fenetre_debut)
ORDER BY (fenetre_debut, derniere_maj)
TTL fenetre_debut + INTERVAL 365 DAY""",
    """CREATE TABLE IF NOT EXISTS sae.croisements_fenetre -- historique long : toutes les dimensions croisées
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
TTL fenetre_debut + INTERVAL 365 DAY""",
    """CREATE TABLE IF NOT EXISTS sae.adjectifs_fenetre   -- adjectifs d'un lexique fermé, par cible et stance
(
    fenetre_debut DateTime('UTC'),
    entite        LowCardinality(String),
    stance        LowCardinality(String),
    adjectif      LowCardinality(String),
    scoreur       LowCardinality(String),
    nb_posts      UInt64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(fenetre_debut)
ORDER BY (fenetre_debut, entite, stance, adjectif, scoreur)
TTL fenetre_debut + INTERVAL 365 DAY""",
    """CREATE TABLE IF NOT EXISTS sae.evenements          -- faits datés : titre et lien publics, aucun texte
(
    id               String,
    date_publication DateTime('UTC'),
    titre            String,
    categorie        LowCardinality(String),
    source           LowCardinality(String),
    lien             String
)
ENGINE = ReplacingMergeTree
ORDER BY id
TTL date_publication + INTERVAL 365 DAY""",
]
TABLES = ("cibles_fenetre", "posts_fenetre", "themes_fenetre", "pipeline_fenetre", "croisements_fenetre",
          "adjectifs_fenetre", "evenements")
PARIS = ZoneInfo("Europe/Paris")

# (id, nom, type, camp, popularité : biais de « pour », attention : poids de citation)
ENTITES = [
    ("demo-g1", "Candidat G1", "candidat", "gauche", 0.62, 1.4),
    ("demo-g2", "Candidate G2", "candidat", "gauche", 0.35, 1.0),
    ("demo-c1", "Candidat C1", "candidat", "centre", 0.48, 0.8),
    ("demo-d1", "Candidate D1", "candidat", "droite", 0.30, 1.6),
    ("demo-d2", "Candidat D2", "candidat", "droite", 0.55, 0.9),
    ("demo-n1", "Candidat N1 (non classé)", "candidat", None, 0.45, 0.5),
    ("demo-p1", "Parti P1", "parti", None, 0.40, 1.1),
    ("demo-p2", "Parti P2", "parti", None, 0.52, 0.7),
]
THEMES = ["economie", "social-retraites", "immigration", "securite", "ecologie", "europe-international",
          "institutions", "sante-education", "campagne-sondages", "autre"]
EMOTIONS = [("joie", 0.10), ("colere", 0.28), ("peur", 0.07), ("tristesse", 0.06), ("surprise", 0.05),
            ("degout", 0.12), ("neutre", 0.12), ("non_evalue", 0.20)]


# Adjectifs : mots courants choisis ici, jamais tirés du corpus. Poids relatifs dans chaque stance.
ADJECTIFS = {
    "pour": [("courageux", 5), ("clair", 4), ("sérieux", 4), ("solide", 3), ("honnête", 3), ("compétent", 2),
             ("rassurant", 2), ("audacieux", 1)],
    "contre": [("flou", 5), ("arrogant", 4), ("incompétent", 3), ("démagogue", 3), ("hypocrite", 3),
               ("dangereux", 2), ("décevant", 2), ("ridicule", 1)],
}
ADJECTIFS_PIC = [("injuste", 6), ("brutal", 4), ("méprisant", 4), ("autoritaire", 3)]  # après l'événement simulé
DROITE = [e[0] for e in ENTITES if e[3] == "droite"]
# Catalogue fictif : (décalage en jours par rapport à l'événement simulé, heure de Paris, catégorie, titre).
CATALOGUE = [
    (0, 18, "loi", "[Simulation] Adoption par 49.3 d'une réforme des retraites fictive"),
    (-2, 9, "bourse", "[Simulation] Le CAC 40 recule de 4 % en séance (fait inventé)"),
    (-8, 7, "prix", "[Simulation] Hausse de 10 % du tarif de l'électricité (fait inventé)"),
    (-12, 6, "greve", "[Simulation] Journée de grève dans les transports (fait inventé)"),
    (-20, 14, "manifestation", "[Simulation] Manifestation nationale pour le climat (fait inventé)"),
]


def instant_evenement(maintenant: datetime) -> datetime:
    """Événement simulé : il y a 5 jours (Paris), à 18 h, heure de Paris."""
    jour = maintenant.astimezone(PARIS).date() - timedelta(days=5)
    return datetime.combine(jour, time(18, 0), tzinfo=PARIS).astimezone(timezone.utc)


def intensite_pic(t: datetime, evenement: datetime | None) -> float:
    """Réaction simulée : nulle avant l'événement, forte juste après, divisée par e toutes les 16 h."""
    if evenement is None or t < evenement:
        return 0.0
    return math.exp(-(t - evenement).total_seconds() / 3600 / 16)


def catalogue(maintenant: datetime) -> list[tuple]:
    d = instant_evenement(maintenant)
    lignes = []
    for decalage, heure, categorie, titre in CATALOGUE:
        jour = d.astimezone(PARIS).date() + timedelta(days=decalage)
        quand = datetime.combine(jour, time(heure, 0), tzinfo=PARIS).astimezone(timezone.utc)
        ident = hashlib.sha256(titre.encode()).hexdigest()[:16]
        lignes.append((ident, quand, titre, categorie, "simulation", ""))  # heure avec fuseau : sans fuseau, le client prendrait l'heure locale
    return lignes


def yaml_lexique() -> str:
    lignes = ["# Lexique INVENTÉ pour les essais du dashboard (aucun rapport avec des personnes réelles).", "version: 1", "entites:"]
    for id_, nom, type_, camp, _, _ in ENTITES:
        lignes += [f"  - id: {id_}", f"    nom: \"{nom}\"", f"    type: {type_}", f"    camp: {camp if camp else 'null'}", "    alias: []"]
    return "\n".join(lignes) + "\n"


def verifier_cible(host: str) -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        sys.exit(f"Refus : {host} n'est pas local. Ce script supprime les tables sae.")


def remplir(c, scenario: str, maintenant: datetime, jours: int) -> dict[str, int]:
    rng = random.Random(2027)
    fin = maintenant.replace(minute=maintenant.minute - maintenant.minute % 5, second=0, microsecond=0)
    nb_fen = {"normal": 288 * jours, "perime": 288 * jours, "evenement": 288 * jours, "peu": 6, "vide": 0}[scenario]
    evenement = instant_evenement(maintenant) if scenario == "evenement" else None
    rng_a = random.Random(2029)  # adjectifs : tirage à part, les autres tables gardent leur suite aléatoire
    adjectifs: dict[tuple, int] = {}
    decalage = timedelta(hours=2) if scenario == "perime" else timedelta(0)
    cibles, posts, themes, pipeline = [], [], [], []
    src: list[tuple[datetime, str, int]] = []  # (fenêtre, entité, citations) : base des croisements
    for k in range(nb_fen):
        t = fin - decalage - timedelta(minutes=5 * (nb_fen - k))
        heure = (t.hour + t.minute / 60 + 2) % 24  # heure de Paris approchée
        rythme = 0.55 + 0.45 * math.sin((heure - 8) / 24 * 2 * math.pi) ** 2
        n = max(1, int(rng.gauss(55 * rythme, 6))) if scenario != "peu" else rng.randint(1, 3)
        pic = intensite_pic(t, evenement)
        # Ton et émotion : un ton plus négatif en soirée, par déplacement lent de la probabilité.
        p_neg = 0.42 + 0.12 * math.sin(k / 40)
        sent = {"negatif": p_neg * 0.7, "positif": 0.2, "neutre": 0.15, "non_evalue": 0.3}
        for s, p in sent.items():
            for e, pe in EMOTIONS:
                m = int(round(n * p * pe + rng.random() - 0.4))
                if m > 0:
                    posts.append((t, s, e, m))
        for th in THEMES:
            w = 0.5 if th == "autre" else 0.35 - 0.02 * THEMES.index(th)
            m = int(round(n * w * rng.uniform(0.5, 1.2)))
            if m > 0:
                themes.append((t, th, m))
        for id_, _, _, _, pop, att in ENTITES:
            cites = int(round(n * 0.08 * att * rng.uniform(0.4, 1.6)))
            if scenario == "peu":
                cites = rng.randint(0, 1)
            src.append((t, id_, cites))
            for _ in range(cites):
                tirage = rng.random()
                if tirage < 0.13:  # posts évalués (couverture faible du scoreur à règles)
                    stance = "pour" if rng.random() < pop else "contre"
                elif tirage < 0.45:
                    stance = rng.choice(["neutre", "mention", "ambigu"])
                else:
                    stance = "non_evalue"
                cibles.append((t, id_, stance, 1))
                if stance in ADJECTIFS and rng_a.random() < 0.6:
                    mot = rng_a.choices(*zip(*ADJECTIFS[stance]))[0]
                    adjectifs[(t, id_, stance, mot)] = adjectifs.get((t, id_, stance, mot), 0) + 1
        # Événement simulé : évaluations « contre » en plus sur la droite, posts négatifs et colère en plus.
        if pic > 0:
            for id_ in DROITE:
                extra = int(round(3.0 * pic * rng_a.uniform(0.7, 1.3)))
                if extra:
                    cibles.append((t, id_, "contre", extra))
                    src.append((t, id_, extra))
                    for _ in range(extra):
                        if rng_a.random() < 0.7:
                            mot = rng_a.choices(*zip(*(ADJECTIFS_PIC + ADJECTIFS["contre"])))[0]
                            adjectifs[(t, id_, "contre", mot)] = adjectifs.get((t, id_, "contre", mot), 0) + 1
            n_extra = int(round(8 * pic))
            if n_extra:
                posts.append((t, "negatif", "colere", n_extra))
                themes.append((t, "social-retraites", n_extra))
                n += n_extra
        if scenario in ("normal", "evenement") and k < 120:
            cibles.append((t, "inconnu-xyz", "pour", 1))  # entité absente du lexique : ne casse rien
        derniere = min(t + timedelta(minutes=5, seconds=rng.randint(10, 40)), maintenant - decalage)
        pipeline.append((t, n, n * rng.randint(2200, 3400), derniere))
    agreg: dict[tuple, int] = {}
    for t, e, s, m in cibles:
        agreg[(t, e, s)] = agreg.get((t, e, s), 0) + m
    cibles = [(t, e, s, m) for (t, e, s), m in agreg.items()]
    # Croisements : une occurrence (post, cible, thème) par citation, un seul scoreur. Tirage à part
    # (graine 2028) : les autres tables gardent la même suite aléatoire.
    rng_c = random.Random(2028)
    cles: dict[tuple, int] = {}
    for t, id_, cites in src:
        for _ in range(cites):
            cle = (
                t, id_, rng_c.choice(["pour", "contre", "neutre", "mention", "ambigu", "non_evalue"]),
                rng_c.choice(["positif", "neutre", "negatif", "non_evalue"]),
                rng_c.choices([e for e, _ in EMOTIONS], [p for _, p in EMOTIONS])[0], rng_c.choice(THEMES),
            )
            cles[cle] = cles.get(cle, 0) + 1
    croisements = [(t, e, s, sen, em, th, "lexique-v1", m) for (t, e, s, sen, em, th), m in cles.items()]
    lignes_adj = [(t, e, s, a, "lexique-v1", m) for (t, e, s, a), m in adjectifs.items()]
    if lignes_adj:
        c.insert("sae.adjectifs_fenetre", lignes_adj,
                 column_names=["fenetre_debut", "entite", "stance", "adjectif", "scoreur", "nb_posts"])
    evenements = catalogue(maintenant) if scenario in ("normal", "evenement", "perime") else []
    if evenements:
        c.insert("sae.evenements", evenements,
                 column_names=["id", "date_publication", "titre", "categorie", "source", "lien"])
    if croisements:
        c.insert(
            "sae.croisements_fenetre", croisements,
            column_names=["fenetre_debut", "entite", "stance", "sentiment", "emotion", "theme", "scoreur", "nb_posts"],
        )
    if cibles:
        c.insert("sae.cibles_fenetre", cibles, column_names=["fenetre_debut", "entite", "stance", "nb_posts"])
    if posts:
        c.insert("sae.posts_fenetre", posts, column_names=["fenetre_debut", "sentiment", "emotion", "nb_posts"])
    if themes:
        c.insert("sae.themes_fenetre", themes, column_names=["fenetre_debut", "theme", "nb_posts"])
    if pipeline:
        c.insert("sae.pipeline_fenetre", pipeline, column_names=["fenetre_debut", "nb_posts", "somme_latence_ms", "derniere_maj"])
    return {
        "cibles_fenetre": len(cibles), "posts_fenetre": len(posts), "themes_fenetre": len(themes),
        "pipeline_fenetre": len(pipeline), "croisements_fenetre": len(croisements),
        "adjectifs_fenetre": len(lignes_adj), "evenements": len(evenements),
    }


def creer_compte_lecture(c, mot_de_passe: str) -> None:
    c.command("CREATE USER IF NOT EXISTS dashboard IDENTIFIED BY {mdp:String} SETTINGS PROFILE 'readonly'", parameters={"mdp": mot_de_passe})
    c.command("ALTER USER dashboard IDENTIFIED BY {mdp:String}", parameters={"mdp": mot_de_passe})
    c.command("GRANT SELECT ON sae.* TO dashboard")


def verifier_lecture_seule(host: str, port: int, mot_de_passe: str) -> None:
    d = clickhouse_connect.get_client(host=host, port=port, username="dashboard", password=mot_de_passe,
                                      database="sae", autogenerate_session_id=False)
    d.query("SELECT count() FROM sae.cibles_fenetre")
    try:
        d.command("INSERT INTO sae.cibles_fenetre VALUES (now(), 'x', 'pour', 1)")
    except Exception as exc:  # noqa: BLE001
        print(f"OK  le compte dashboard ne peut pas insérer ({type(exc).__name__})")
        return
    sys.exit("ECHEC : le compte dashboard a pu insérer")


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--port", type=int, default=18223)
    a.add_argument("--admin-user", default="admin")
    a.add_argument("--admin-password", default="admin-dev")
    a.add_argument("--dashboard-password", default="dashboard-dev")
    a.add_argument("--scenario", choices=["normal", "evenement", "peu", "vide", "perime"], default="normal")
    a.add_argument("--lexique-out", type=Path, help="dossier où écrire entites.yaml (lexique inventé)")
    a.add_argument("--jours", type=int, default=35, help="durée des scénarios normal et perime, en jours")
    args = a.parse_args()
    verifier_cible(args.host)
    c = clickhouse_connect.get_client(host=args.host, port=args.port, username=args.admin_user, password=args.admin_password)
    c.command("DROP DATABASE IF EXISTS sae")
    for ddl in DDL:
        c.command(ddl)
    compte = remplir(c, args.scenario, datetime.now(timezone.utc), args.jours)
    creer_compte_lecture(c, args.dashboard_password)
    if args.lexique_out:
        args.lexique_out.mkdir(parents=True, exist_ok=True)
        (args.lexique_out / "entites.yaml").write_text(yaml_lexique(), encoding="utf-8")
    print(f"scénario {args.scenario} : {compte}")
    verifier_lecture_seule(args.host, args.port, args.dashboard_password)


if __name__ == "__main__":
    main()
