#!/usr/bin/env python3
"""Test de l'API REST publique Bluesky (AppView) : searchPosts.

Utile au POC : source déterministe et re-jouable, complémentaire du firehose
(l'AppView a un rate limit public ~60 req/min sans compte).

Usage :
    python scripts/test_bsky_search.py                     # "présidentielle 2027"
    python scripts/test_bsky_search.py "rugby 2027" -n 3
"""
import argparse
import sys

import requests

from common import mask, preview

APPVIEW = "https://api.bsky.app"
DEFAULT_QUERY = 'présidentielle 2027'


def main() -> int:
    ap = argparse.ArgumentParser(description="Recherche de posts via l'AppView Bluesky")
    ap.add_argument("query", nargs="?", default=DEFAULT_QUERY, help="terme de recherche")
    ap.add_argument("-n", "--limit", type=int, default=5, help="nb de posts (max 25)")
    ap.add_argument("--raw", action="store_true",
                    help="afficher la réponse JSON telle quelle (sans masquage)")
    args = ap.parse_args()

    resp = requests.get(
        f"{APPVIEW}/xrpc/app.bsky.feed.searchPosts",
        params={"q": args.query, "limit": min(args.limit, 25)},
        headers={"User-Agent": "sae-data-poc/0.1 (education)"},
        timeout=10,
    )
    print(f"GET {resp.url}  → HTTP {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()

    posts = data.get("posts", [])
    print(f"{len(posts)} post(s) pour « {args.query} »\n")
    for p in posts:
        record, author = p.get("record", {}), p.get("author", {})
        print(f"  @{mask(author.get('handle', ''))}  ({mask(author.get('did', ''))})")
        print(f"    {p.get('indexedAt')}  langs={record.get('langs')} "
              f"likes={p.get('likeCount')} replies={p.get('replyCount')}")
        print(f"    {preview(record.get('text', ''))}\n")

    if not args.raw:
        print("Champs d'un post :", sorted(next(iter(posts)).keys())
              if posts else "(aucun post)")
        print("Champs d'author :", sorted(next(iter(posts))["author"].keys())
              if posts else "(aucun post)")
        print("→ author.handle/did/avatar/displayName : à exclure avant sinks durables (Liv. 1 M2)")
    else:
        print(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())