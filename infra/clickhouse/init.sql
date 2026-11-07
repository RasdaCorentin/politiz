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
    stance        LowCardinality(String),   -- pour ou contre
    adjectif      LowCardinality(String),   -- forme affichée de ressources/lexique/adjectifs.yaml
    scoreur       LowCardinality(String),
    nb_posts      UInt64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(fenetre_debut)
ORDER BY (fenetre_debut, entite, stance, adjectif, scoreur)
TTL fenetre_debut + INTERVAL 365 DAY;
