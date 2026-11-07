#!/usr/bin/env python3
"""Valide les couleurs de données du dashboard par le calcul.

Les couleurs sont lues dans `style.css` (jetons clair et sombre) : la validation porte sur ce
qui est livré. Les seuils suivent la méthode du skill `dataviz` :

* contraste WCAG : texte >= 4,5 ; marque >= 3 contre la surface ;
* bande de clarté OKLCH L : 0,43-0,77 (clair), 0,48-0,67 (sombre) ; chroma >= 0,10 ;
* séparation daltonisme : distance euclidienne OKLab x 100, simulation Machado-Oliveira-Fernandes
  (2009), sévérité 1,0, protanopie et deutéranopie ; cible >= 8, plancher >= 6 ;
* séparation en vision normale >= 15 (plancher dur).

Usage :
    python valider_palette.py                      # valide style.css, clair et sombre
    python valider_palette.py --liste "#d03b3b,#2f63c4" --mode clair --surface "#ffffff"

Code de sortie : 0 sans échec dur, 1 sinon. Aucune dépendance hors bibliothèque standard.
"""

from __future__ import annotations

import argparse
import itertools
import math
import re
import sys
from pathlib import Path

MACHADO = {
    "protanopie": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
    "deutéranopie": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
}
BANDE = {"clair": (0.43, 0.77), "sombre": (0.48, 0.67)}
CHROMA_MIN = 0.10
CVD_CIBLE, CVD_PLANCHER = 8.0, 6.0
NORMAL_PLANCHER = 15.0
CONTRASTE_MARQUE, CONTRASTE_TEXTE = 3.0, 4.5

CSS_PAR_DEFAUT = Path(__file__).resolve().parent.parent / "src" / "style.css"


# --- conversions -----------------------------------------------------------------------------
def _srgb(h: str) -> tuple[float, float, float]:
    h = h.strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise ValueError(f"couleur invalide : {h!r} (attendu #rrggbb)")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lineaire(h: str) -> tuple[float, float, float]:
    r, g, b = _srgb(h)
    return _lin(r), _lin(g), _lin(b)


def luminance(h: str) -> float:
    r, g, b = lineaire(h)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: str, b: str) -> float:
    haut, bas = sorted((luminance(a), luminance(b)), reverse=True)
    return (haut + 0.05) / (bas + 0.05)


def _oklab_lin(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = rgb
    l = math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    )


def oklch(h: str) -> tuple[float, float, float]:
    """Retourne (L, C, teinte en degrés)."""
    L, a, b = _oklab_lin(lineaire(h))
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def _simuler(h: str, type_: str) -> tuple[float, float, float]:
    r, g, b = lineaire(h)
    m = MACHADO[type_]
    return tuple(min(1.0, max(0.0, row[0] * r + row[1] * g + row[2] * b)) for row in m)  # type: ignore[return-value]


def delta_e(h1: str, h2: str, type_: str | None = None) -> float:
    """Distance OKLab x 100, en vision normale ou simulée."""
    a = _oklab_lin(_simuler(h1, type_) if type_ else lineaire(h1))
    b = _oklab_lin(_simuler(h2, type_) if type_ else lineaire(h2))
    return 100 * math.dist(a, b)


def delta_e_cvd(h1: str, h2: str) -> tuple[float, str]:
    """Pire séparation des deux types de daltonisme courants."""
    return min((delta_e(h1, h2, t), t) for t in MACHADO)


# --- lecture de style.css --------------------------------------------------------------------
_JETON = re.compile(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;")


def lire_jetons(css: str) -> dict[str, dict[str, str]]:
    """Jetons hexadécimaux du bloc `:root` (clair) et du bloc sombre (média `prefers-color-scheme`)."""
    racine = re.search(r":root\s*\{(.*?)\n\}", css, re.S)
    sombre = re.search(r"prefers-color-scheme:\s*dark\)\s*\{\s*:root[^{]*\{(.*?)\n\s*\}", css, re.S)
    if not racine or not sombre:
        raise ValueError("blocs :root et sombre introuvables dans le CSS")
    clair = dict(_JETON.findall(racine.group(1)))
    fonce = {**clair, **dict(_JETON.findall(sombre.group(1)))}
    return {"clair": clair, "sombre": fonce}


# --- rapport ---------------------------------------------------------------------------------
class Rapport:
    def __init__(self) -> None:
        self.echecs = 0
        self.alertes = 0

    def ligne(self, etat: str, nom: str, detail: str) -> None:
        if etat == "ÉCHEC":
            self.echecs += 1
        elif etat == "ALERTE":
            self.alertes += 1
        print(f"  [{etat:<6}] {nom:<34} {detail}")


def controle_texte(r: Rapport, jetons: dict[str, str]) -> None:
    for texte in ("--text", "--text-2", "--muted"):
        for fond in ("--bg", "--surface", "--surface-2"):
            if texte in jetons and fond in jetons:
                c = contraste(jetons[texte], jetons[fond])
                r.ligne("OK" if c >= CONTRASTE_TEXTE else "ÉCHEC", f"texte {texte} / {fond}", f"{c:.2f}:1 (>= {CONTRASTE_TEXTE})")


def controle_marques(r: Rapport, jetons: dict[str, str], noms: list[str], mode: str) -> None:
    surface = jetons["--surface"]
    bas, haut = BANDE[mode]
    for nom in noms:
        h = jetons[nom]
        c = contraste(h, surface)
        L, C, teinte = oklch(h)
        etat = "OK" if c >= CONTRASTE_MARQUE else "ALERTE"
        r.ligne(etat, f"marque {nom}", f"{h} contraste {c:.2f}:1 | L {L:.2f} C {C:.2f} teinte {teinte:.0f}°"
                + ("" if etat == "OK" else " (libellé ou tableau obligatoire)"))
        if C >= 0.08 and not (bas <= L <= haut):
            r.ligne("ALERTE", f"bande L {nom}", f"L {L:.2f} hors de {bas}-{haut}")


def controle_paire(r: Rapport, jetons: dict[str, str], a: str, b: str, *, teintes: bool) -> None:
    ha, hb = jetons[a], jetons[b]
    d_norm = delta_e(ha, hb)
    d_cvd, type_ = delta_e_cvd(ha, hb)
    etat_n = "OK" if d_norm >= NORMAL_PLANCHER else "ÉCHEC"
    etat_c = "OK" if d_cvd >= CVD_CIBLE else ("ALERTE" if d_cvd >= CVD_PLANCHER else "ÉCHEC")
    if not teintes:
        # Paire dont un membre est un gris : la séparation compte, la teinte non.
        etat_c = "OK" if d_cvd >= CVD_PLANCHER else "ÉCHEC"
    r.ligne(etat_n, f"vision normale {a} | {b}", f"ΔE {d_norm:.1f} (plancher {NORMAL_PLANCHER:.0f})")
    r.ligne(etat_c, f"daltonisme {a} | {b}", f"ΔE {d_cvd:.1f} ({type_}; cible {CVD_CIBLE:.0f}, plancher {CVD_PLANCHER:.0f})")


def valider_css(css: Path) -> int:
    modes = lire_jetons(css.read_text(encoding="utf-8"))
    r = Rapport()
    marques = ["--camp-gauche", "--camp-centre", "--camp-droite", "--ton-positif", "--ton-negatif", "--ton-neutre", "--data"]
    for mode, jetons in modes.items():
        print(f"\n== {mode} (surface {jetons['--surface']}, fond {jetons['--bg']}) ==")
        controle_texte(r, jetons)
        controle_marques(r, jetons, marques, mode)
        print("  -- camps (barre rouge, gris, bleu) --")
        controle_paire(r, jetons, "--camp-gauche", "--camp-droite", teintes=True)
        controle_paire(r, jetons, "--camp-gauche", "--camp-centre", teintes=False)
        controle_paire(r, jetons, "--camp-centre", "--camp-droite", teintes=False)
        print("  -- ton (positif, négatif, neutre) --")
        controle_paire(r, jetons, "--ton-positif", "--ton-negatif", teintes=True)
        controle_paire(r, jetons, "--ton-positif", "--ton-neutre", teintes=False)
        controle_paire(r, jetons, "--ton-negatif", "--ton-neutre", teintes=False)
        print("  -- statuts de fraîcheur (information : icône et libellé toujours présents) --")
        for nom in ("--status-ok", "--status-warn", "--status-critical", "--status-unknown"):
            if nom in jetons:
                print(f"  [info  ] {nom:<20} contraste {contraste(jetons[nom], jetons['--surface']):.2f}:1 sur la surface")
        print("  -- croisements camp x ton (information : jamais côte à côte) --")
        for a, b in itertools.product(("--camp-gauche", "--camp-droite"), ("--ton-positif", "--ton-negatif")):
            d_norm = delta_e(jetons[a], jetons[b])
            d_cvd, type_ = delta_e_cvd(jetons[a], jetons[b])
            print(f"  [info  ] {a} | {b:<14} normal {d_norm:5.1f}  daltonisme {d_cvd:5.1f} ({type_})")
    print(f"\nRésultat : {r.echecs} échec(s), {r.alertes} alerte(s).")
    return 1 if r.echecs else 0


def valider_liste(liste: str, mode: str, surface: str, toutes: bool) -> int:
    couleurs = [c.strip() for c in liste.split(",") if c.strip()]
    r = Rapport()
    jetons = {f"c{i}": c for i, c in enumerate(couleurs)}
    jetons["--surface"] = surface
    print(f"\n== liste ({mode}, surface {surface}) ==")
    controle_marques(r, jetons, [f"c{i}" for i in range(len(couleurs))], mode)
    paires = itertools.combinations(range(len(couleurs)), 2) if toutes else zip(range(len(couleurs)), range(1, len(couleurs)))
    for i, j in paires:
        controle_paire(r, jetons, f"c{i}", f"c{j}", teintes=True)
    print(f"\nRésultat : {r.echecs} échec(s), {r.alertes} alerte(s).")
    return 1 if r.echecs else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--css", type=Path, default=CSS_PAR_DEFAUT, help="fichier de jetons (défaut : src/style.css)")
    ap.add_argument("--liste", help="liste #hex,#hex à valider à la place du CSS")
    ap.add_argument("--mode", choices=("clair", "sombre"), default="clair")
    ap.add_argument("--surface", default="#ffffff")
    ap.add_argument("--toutes-paires", action="store_true", help="avec --liste : toutes les paires, pas seulement les voisines")
    args = ap.parse_args()
    if args.liste:
        return valider_liste(args.liste, args.mode, args.surface, args.toutes_paires)
    return valider_css(args.css)


if __name__ == "__main__":
    sys.exit(main())
