import sqlite3
from datetime import datetime, timedelta

import pytest


def make_posts(n=60, entites=("dupont", "martin", "durand")):
    """Posts synthétiques inventés (aucun contenu réel)."""
    base = datetime(2026, 10, 1, 8, 0)
    posts = []
    for i in range(n):
        if i % 4 == 3:
            texte = f"message numéro {i} sur la météo et le marché de la ville"
        else:
            e = entites[i % len(entites)]
            texte = f"opinion numéro {i} au sujet de {e} dans le débat"
        posts.append({"post_id": str(i), "created_at": (base + timedelta(hours=7 * i)).isoformat() + "Z",
                      "text": texte, "dedup_key": f"k{i}"})
    return posts


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "synth.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE posts(id INTEGER PRIMARY KEY, created_at TEXT, text TEXT, dedup_key TEXT)")
    for i, t in enumerate(["Bonjour Le Pen est là aujourd'hui sur place", "Bonjour Le Pen est là aujourd'hui sur place !!",
                           "ok", "Mélenchon parle de la retraite devant tous", "Une phrase sans rapport avec rien du tout"]):
        con.execute("INSERT INTO posts VALUES (?,?,?,?)", (i, f"2026-10-0{i + 1}T10:00:00Z", t, f"k{i}"))
    con.commit()
    con.close()
    return p
