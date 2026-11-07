# Exemples de requêtes API — structure des données reçues (Sujet 1)

Requêtes testées en direct le **08/10/2026**. Ce document liste les champs que le pipeline ingère.
Il fonde l'analyse PII du [Livrable 1](../livrable1/livrable1-legalite-ethique.pdf) sur la
structure réellement observée. Les valeurs des exemples sont inventées : aucun post ni identifiant
réel n'est versionné.

## 1. Bluesky Jetstream — firehose WebSocket (ingestion principale)

### Connexion

```bash
# WebSocket public : ni clé, ni authentification
wss://jetstream1.us-east.bsky.network/subscribe?wantedCollections=app.bsky.feed.post
# Miroir équivalent : wss://jetstream2.us-east.bsky.network/subscribe?...
```

Paramètres utiles ([documentation Jetstream](https://github.com/bluesky-social/jetstream)) :

| Paramètre | Rôle |
| --- | --- |
| `wantedCollections` | Filtre les posts (`app.bsky.feed.post`) |
| `maxMessageSize` | Limite la taille d'un message |
| `cursor` | Reprend le flux à un instant donné (`time_us`) après un redémarrage |
| `compress` | Active la compression zstd |

### Événement reçu (structure réelle, valeurs inventées)

```json
{
  "did": "did:plc:exemple0001",
  "time_us": 1791400000000000,
  "kind": "commit",
  "commit": {
    "rev": "3exemplerev22",
    "operation": "create",
    "collection": "app.bsky.feed.post",
    "rkey": "3exemplerkey2",
    "record": {
      "$type": "app.bsky.feed.post",
      "createdAt": "2026-10-08T04:42:16.721Z",
      "langs": ["fr"],
      "reply": {"parent": {"cid": "bafyreia...", "uri": "at://did:plc:exemple0002/app.bsky.feed.post/3exempleparent"},
                "root":   {"cid": "bafyreia...", "uri": "at://did:plc:exemple0002/app.bsky.feed.post/3exempleparent"}},
      "text": "Texte inventé qui cite un candidat."
    },
    "cid": "bafyreiexemplecid"
  }
}
```

Champs observés dans un `record` : `$type`, `text`, `createdAt`, `langs`, `facets` (tags,
mentions), `embed` (image ou lien : title, description, uri, thumb), `reply` (parent, root),
`via`, `tags`.

Clés observées dans `commit` : `cid`, `collection`, `operation`, `record`, `rev`, `rkey`. Chaque
commit porte un seul `record`, comme le décrit la
[documentation Jetstream](https://github.com/bluesky-social/jetstream).

### Décision PII par champ (Livrable 1, audit des données)

| Champ | Nature | Décision |
| --- | --- | --- |
| `did` | Identifiant direct et durable de l'auteur | Supprimé dans Spark. Aucun pseudonyme ni hachage conservé. |
| `commit.rkey`, `cid` | Identifiants du post, reliables à l'auteur | Supprimés (M1) : le schéma de lecture de Spark ne les déclare pas ([contrats-poc.md](contrats-poc.md), contrat Spark `job.py`) |
| `text` | Opinion politique, retrouvable par recherche exacte | Scoré dans Spark puis jeté. **Jamais stocké.** |
| `reply.*.uri` | Contient le `did` de l'auteur parent : identifiant indirect | Supprimé. |
| `createdAt`, `time_us` | Quasi-identifiants : un horodatage précis retrouve le post | Tronqués à la fenêtre |
| `langs` | Nécessaire au filtrage | Conservé |
| `actor`, `bridgyOriginalUrl`, `bridgyOriginalText` | Posts relayés par Bridgy : identifiants d'auteur supplémentaires | Traités comme `did` (Livrable 1, M1) |
| `facets` (tags) | Sujet du post, pas un identifiant | Hashtags conservés par Spark ; mentions ignorées. Le corpus de développement garde le nom public d'un candidat mentionné (`[mention:<nom>]`, [ingestion-processus.md](ingestion-processus.md)). |

## 2. Bluesky AppView — API REST publique (complément au POC)

### Requête (testée, sans authentification)

```bash
curl "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=%22presidentielle%202027%22&limit=2" \
  -H "User-Agent: sae-data-poc/0.1 (education)"
```

L'AppView publique limite le débit (environ 60 requêtes/min sans compte). Elle ne suffit pas pour
du temps réel. Elle sert au POC : elle rejoue une recherche de façon déterministe. Jetstream reste
l'ingestion principale.

### Réponse (structure réelle, valeurs inventées)

```json
{
  "posts": [
    {
      "uri": "at://did:plc:exemple0003/app.bsky.feed.post/3exemplepost3",
      "cid": "bafyreiexemplecid3",
      "author": {
        "did": "did:plc:exemple0003",
        "handle": "exemple.bsky.social",
        "displayName": "", "avatar": "https://cdn.bsky.app/...",
        "createdAt": "2025-12-16T20:31:28.726Z"
      },
      "record": {
        "$type": "app.bsky.feed.post",
        "createdAt": "2026-10-08T06:05:36+02:00",
        "text": "...",
        "embed": {"$type": "app.bsky.embed.external",
                  "external": {"title": "Titre d'article inventé",
                                "uri": "https://exemple.org/article"}},
        "facets": [{"features": [{"$type": "app.bsky.richtext.facet#tag", "tag": "Elections"}]}]
      },
      "indexedAt": "2026-10-08T06:05:40.000Z",
      "likeCount": 0, "replyCount": 0, "repostCount": 0, "bookmarkCount": 0, "labels": []
    }
  ]
}
```

L'AppView ajoute des champs PII absents de Jetstream : `author.handle`, `author.avatar`,
`author.did`, `author.displayName`. Le pipeline les **supprime tous** avant stockage durable
(Livrable 1, M1).

## 3. Conséquences pour le Livrable 1

1. **Risque U1 confirmé.** Chaque événement transporte un identifiant d'auteur (`did`, `handle`).
   Le pipeline doit les neutraliser dans Spark.
2. **Champ PII indirect.** `reply.parent.uri` contient le `did` de l'auteur parent. Spark le
   supprime avant MinIO et ClickHouse (M1).
3. **Reprise Jetstream.** Le paramètre `cursor` permet de reprendre sans perte. Les identifiants
   d'événement (`rev`, `rkey`, `cid`) restent seulement dans les checkpoints techniques, à durée
   de vie courte (M6).
