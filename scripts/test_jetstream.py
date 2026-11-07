#!/usr/bin/env python3
"""Test de l'API Bluesky Jetstream (firehose WebSocket public).

Capture N évéments du firehose, inventorie les champs reçus (utile pour le
schéma d'ingestion) et masque tout identifiant d'auteur (policy Liv. 1 M1/M2).

Usage :
    python scripts/test_jetstream.py                  # 5 événements post
    python scripts/test_jetstream.py -n 20 --lang fr  # 20 posts francophones
"""
import argparse
import json
import sys
import time

import websocket

from common import mask, preview

ENDPOINTS = [
    "wss://jetstream1.us-east.bsky.network/subscribe",
    "wss://jetstream2.us-east.bsky.network/subscribe",
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture d'événements Bluesky Jetstream")
    ap.add_argument("-n", type=int, default=5, help="nombre de posts à capturer (déf. 5)")
    ap.add_argument("--lang", default=None, help="ne garder que les posts de cette langue (ex: fr)")
    ap.add_argument("--timeout", type=int, default=30, help="durée max de capture en s (déf. 30)")
    args = ap.parse_args()

    if args.lang:
        print(f"Couverture : {args.lang} — filtrage côté client (Jetstream ne filtre pas la langue)")

    last_err = None
    for endpoint in ENDPOINTS:
        url = endpoint + "?wantedCollections=app.bsky.feed.post"
        try:
            print(f"Connexion à {endpoint} …")
            ws = websocket.create_connection(url, timeout=args.timeout)
            break
        except Exception as e:  # miroirs Jetstream : essayer le suivant
            last_err = e
    else:
        print(f"Échec de connexion aux deux miroirs : {last_err}")
        return 1

    events, posts, fields = 0, [], set()
    print(f"Capture de {args.n} posts (timeout {args.timeout} s)…")
    deadline = time.monotonic() + args.timeout
    stope = None
    try:
        while time.monotonic() < deadline and len(posts) < args.n:
            ws.sock.settimeout(1.0)  # recv court + deadline murale (robuste Windows)
            try:
                message = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if not message:
                continue
            msg = json.loads(message)
            events += 1
            commit = msg.get("commit") or {}
            # Jetstream envoie un seul record par commit : `commit.record`
            records = [commit["record"]] if commit.get("record") is not None else []
            for rec in records:
                record = rec or {}
                fields.update(record.keys())
                if args.lang and args.lang not in (record.get("langs") or []):
                    continue
                posts.append({
                    "did": mask(msg.get("did", "")),
                    "operation": commit.get("operation"),
                    "createdAt": record.get("createdAt"),
                    "langs": record.get("langs"),
                    "text": preview(record.get("text", "")),
                    "has_reply": bool(record.get("reply")),
                })
                if len(posts) >= args.n:
                    break
    except Exception as e:
        stope = e
    if stope:
        print(f"Fin de capture ({type(stope).__name__})")
    elif len(posts) < args.n:
        print(f"Deadline atteinte — {len(posts)}/{args.n} posts capturés")

    print(f"\n{events} événements reçus, {len(posts)} posts conservés "
          f"({events / max(args.timeout, 1):.0f}/s env.).")
    for p in posts[: args.n]:
        print(f"  [{p['operation']}] {p['createdAt']} langs={p['langs']} "
              f"reply={p['has_reply']} did={p['did']}")
        print(f"    {p['text']}")
    print("\nChamps observés dans record :", ", ".join(sorted(fields)))
    return 0


if __name__ == "__main__":
    sys.exit(main())