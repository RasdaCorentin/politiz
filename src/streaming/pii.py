"""Étapes 1 et 2 du contrat Spark (docs/technique/contrats-poc.md) : projection par
liste blanche, puis nettoyage du texte.

Le schéma de lecture ne déclare que les champs gardés. Tout autre champ de l'événement
Jetstream (did, rkey, cid, rev, reply, embed, createdAt, mentions) est ignoré par `from_json`
et n'entre jamais dans le DataFrame.
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd
from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F
from pyspark.sql import types as T

# --- étape 1 : liste blanche -----------------------------------------------------
# facets : seul le hashtag (`tag`) est déclaré. Les entités de mention (`did`) et de lien (`uri`)
# d'une facette n'ont pas de champ dans le schéma.
SCHEMA_EVENEMENT = T.StructType([
    T.StructField("time_us", T.LongType()),
    T.StructField("commit", T.StructType([
        T.StructField("operation", T.StringType()),
        T.StructField("collection", T.StringType()),
        T.StructField("record", T.StructType([
            T.StructField("text", T.StringType()),
            T.StructField("langs", T.ArrayType(T.StringType())),
            T.StructField("facets", T.ArrayType(T.StructType([
                T.StructField("features", T.ArrayType(T.StructType([
                    T.StructField("tag", T.StringType()),
                ]))),
            ]))),
        ])),
    ])),
])

COLONNES_PROJETEES = ("time_us", "operation", "collection", "texte_brut", "langs", "hashtags")


def projeter(df: DataFrame, colonne_valeur: str = "value") -> DataFrame:
    """JSON Kafka (octets ou texte) -> colonnes plates de la liste blanche."""
    ev = F.from_json(F.col(colonne_valeur).cast("string"), SCHEMA_EVENEMENT).alias("ev")
    plat = df.select(ev).select(
        F.col("ev.time_us").alias("time_us"),
        F.col("ev.commit.operation").alias("operation"),
        F.col("ev.commit.collection").alias("collection"),
        F.col("ev.commit.record.text").alias("texte_brut"),
        F.col("ev.commit.record.langs").alias("langs"),
        F.expr("filter(transform(flatten(transform(coalesce(ev.commit.record.facets, "
               "array()), f -> coalesce(f.features, array()))), x -> x.tag), t -> t is not null)"
               ).alias("hashtags"),
    )
    return plat


# --- étape 2 : nettoyage ---------------------------------------------------------
_URL = re.compile(r"https?://\S+|\bwww\.\S+")
_HANDLE = re.compile(r"@[a-z0-9][a-z0-9._\-]*")
_DID = re.compile(r"\bdid:[a-z0-9]+:[a-z0-9._:%\-]*")
_ESPACES = re.compile(r"\s+")


def normaliser(texte: str) -> str:
    """Minuscules, sans accents. Recopie de `normalize()` de src/ingestion/ingestion.py
    (équivalence vérifiée par un test sur chaînes inventées)."""
    nfkd = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def nettoyer_texte(texte: str | None) -> str:
    """Normalise, puis masque les URL, les `@handles` et toute chaîne `did:`."""
    if not texte:
        return ""
    t = normaliser(texte)
    t = _URL.sub(" ", t)
    t = _DID.sub(" ", t)
    t = _HANDLE.sub(" ", t)
    return _ESPACES.sub(" ", t).strip()


def nettoyer_serie(s: pd.Series) -> pd.Series:
    return s.map(nettoyer_texte)


_nettoyer_udf = F.pandas_udf(nettoyer_serie, T.StringType())


def nettoyer(df: DataFrame) -> DataFrame:
    """Filtre (create, post, fr, texte non vide) et nettoie. Sortie : `time_us`, `event_time`,
    `texte` (nettoyé), `hash` (SHA-256 du texte nettoyé). Rien d'autre."""
    return (
        df.where(
            (F.col("operation") == "create")
            & (F.col("collection") == "app.bsky.feed.post")
            & F.coalesce(F.array_contains(F.col("langs"), "fr"), F.lit(False))
            & F.col("time_us").isNotNull()
            & (F.length(F.trim(F.coalesce(F.col("texte_brut"), F.lit("")))) > 0)
        )
        .select("time_us", _nettoyer_udf(F.col("texte_brut")).alias("texte"))
        .where(F.length(F.col("texte")) > 0)
        .select(
            "time_us",
            F.expr("timestamp_micros(time_us)").alias("event_time"),
            "texte",
            F.sha2(F.col("texte"), 256).alias("hash"),
        )
    )
