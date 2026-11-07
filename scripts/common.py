#!/usr/bin/env python3
"""Utilitaires partagés par les scripts de test (docs/technique/exemples-requetes-api.md).

Convention projet (Livrable 1, M2) : aucun identifiant personnel n'est affiché
tel quel en sortie de script — tout DID / handle est masqué.
"""
import os
import re
import sys
import zlib

# Terminal Windows en cp1252 : forcer l'UTF-8 pour l'affichage (accents, emojis)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def mask(value: str, keep: int = 0) -> str:
    """Masque un identifiant (DID, handle...) en n'en gardant que sa forme."""
    if not value:
        return "∅"
    if keep:
        return value[:keep] + "…(masqué)"
    return "did:plc:…(masqué)" if value.startswith("did:") else "…(masqué)"


def pdf_page_count(pdf_path: str) -> int:
    """Compte les pages d'un PDF via ses entrées /Count (suffit pour un contrôle).

    pdflatex range l'arbre des pages dans des flux compressés : on les décompresse aussi.
    Seuls les nœuds /Type /Pages comptent (les signets portent aussi un /Count) ; le nœud
    racine porte le plus grand.
    """
    with open(pdf_path, "rb") as f:
        data = f.read()
    chunks = [data]
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        try:
            chunks.append(zlib.decompress(m.group(1)))
        except zlib.error:
            pass
    pages_nodes = rb"<<[^<>]*?/Type\s*/Pages\b[^<>]*?>>"
    counts = [int(c)
              for chunk in chunks
              for node in re.findall(pages_nodes, chunk)
              for c in re.findall(rb"/Count\s+(\d+)", node)]
    if not counts:
        raise RuntimeError("PDF invalide : entrée /Count introuvable")
    return max(counts)


def preview(text: str, width: int = 80) -> str:
    """Aperçu monoligne d'un texte."""
    text = " ".join(text.split())
    return text[:width] + ("…" if len(text) > width else "")