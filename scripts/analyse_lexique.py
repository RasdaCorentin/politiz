#!/usr/bin/env python3
"""Analyse lexicale du corpus Bluesky et évaluation de la bibliothèque de règles.

Ce script répond à une question : que peut décider une règle (regex, lexique) sans
modèle ? Il lit le corpus en lecture seule et n'écrit QUE des agrégats (termes,
comptes, taux). Aucun post n'est affiché ni copié (Livrable 1, mesure M9).

Sections (`--sections`, toutes par défaut) :
  volumes, doublons, ngrammes, hashtags, derives, emojis, alias, cooccurrences, regles

Exemples :
  uv run --with pyyaml python scripts/analyse_lexique.py --db CORPUS.db
  uv run --with pyyaml python scripts/analyse_lexique.py --db CORPUS.db --sections regles --json out.json

La bibliothèque évaluée est `ressources/lexique/` (format : README.md du dossier).
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import re
import sqlite3
import statistics
import sys
import unicodedata

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_KEYWORDS = os.path.join(REPO_ROOT, "src", "ingestion", "keywords.txt")
DEFAULT_LEXIQUE = os.path.join(REPO_ROOT, "ressources", "lexique")

# --- contrat d'étiquettes (partagé avec l'outil d'annotation) -----------------
STANCES = ("pour", "contre", "neutre", "mention", "ambigu")
CAMPS_ENTITE = ("gauche", "centre", "droite", None)
CIBLES_SPECIALES = ("entite_capturee", "co_mentionnee", "camp", "gouvernement", "groupe-politique")
THEMES = ("economie", "social-retraites", "immigration", "securite", "ecologie",
          "europe-international", "institutions", "sante-education",
          "campagne-sondages", "autre")
EMOTIONS = ("joie", "colere", "peur", "tristesse", "surprise", "degout", "neutre")
CONFIANCES = ("haute", "moyenne", "basse")
TYPES_ENTITE = ("candidat", "parti")
SECTIONS_KEYWORDS = ("identites", "orientations", "jargon")

STOPWORDS = frozenset("""
a ai au aux avec ce ces cet cette ceux chez comme dans de des du elle elles en et eu
il ils je j la le les leur leurs lui ma mais me meme mes moi mon ne ni nos notre nous
on ou par pas pour qu que qui sa se ses si son sur ta te tes toi ton tu un une vos
votre vous c d l m n s t y est sont etre ete etait suis es sera serait ont avoir avait
aura fait faire fais font va vont vais peut peut-etre dit dire plus moins tres trop
bien tout tous toute toutes ca cela ceci ici alors donc car puis aussi encore deja
quand comment pourquoi dont ou entre sans sous apres avant depuis vers contre
http https www com fr bsky app social the to of and in is not it x1 qu'il qu'on qu'ils
c'est n'est j'ai n'a d'un d'une l'on s'est d'etre c'etait n'y
""".split())

TOKEN_RE = re.compile(r"[a-z0-9]+(?:['\-][a-z0-9]+)*")
URL_RE = re.compile(r"https?://\S+|\bwww\.\S+")
HASHTAG_RE = re.compile(r"#\w+")
MENTION_RE = re.compile(r"@[a-z0-9][a-z0-9._\-]*")


# --- normalisation (identique à src/ingestion/ingestion.py) -------------------
def normalize(text: str) -> str:
    """Minuscules + suppression des accents (présidentielle == presidentielle)."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def alt_regex(forms: list[str]) -> str:
    """Alternance à frontières de mot, comme `_alt` de l'ingestion."""
    if not forms:
        return r"(?!)x"
    ordered = sorted(set(forms), key=len, reverse=True)
    return r"\b(?:" + "|".join(map(re.escape, ordered)) + r")\b"


def strip_mentions(norm: str) -> str:
    """Retire les @handles (un robot qui tague @gabriel-attal.bsky.social ne parle pas d'Attal)."""
    return MENTION_RE.sub(" ", norm)


def tokenize(norm: str) -> list[str]:
    """Mots d'un texte normalisé (URLs retirées, hashtags inclus sans '#')."""
    return TOKEN_RE.findall(URL_RE.sub(" ", norm))


def ngrams(tokens: list[str], n: int) -> list[str]:
    """n-grammes dont ni le premier ni le dernier mot n'est un mot vide."""
    out = []
    for i in range(len(tokens) - n + 1):
        gram = tokens[i:i + n]
        if gram[0] in STOPWORDS or gram[-1] in STOPWORDS:
            continue
        out.append(" ".join(gram))
    return out


def is_emoji(ch: str) -> bool:
    o = ord(ch)
    if o in (0x200D, 0xFE0F, 0x20E3):
        return False
    return (0x1F300 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF or 0x1F000 <= o <= 0x1F2FF
            or o in (0x2B50, 0x2B55, 0x2764, 0x203C, 0x2049))


def emojis_of(text: str) -> list[str]:
    return [c for c in text if is_emoji(c)]


# --- keywords.txt --------------------------------------------------------------
def parse_keywords(path: str) -> dict[str, list[str]]:
    """Même lecture que `load_keywords` de l'ingestion (formes normalisées)."""
    classes: dict[str, list[str]] = {s: [] for s in SECTIONS_KEYWORDS}
    current = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("#"):
                tag = s.lstrip("#").strip().lower()
                if tag in SECTIONS_KEYWORDS:
                    current = tag
                continue
            if current:
                classes[current].append(normalize(s))
    return classes


# --- bibliothèque (ressources/lexique/) ---------------------------------------
class LexiqueError(ValueError):
    """Erreur de schéma dans un fichier du lexique."""


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise LexiqueError(msg)


def _load_yaml(path: str):
    import yaml  # import tardif : seul le chargement du lexique en a besoin
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class Lexique:
    """Entités, règles de stance, thèmes et (option) émotions, compilés."""

    def __init__(self, entites: list[dict], stance: list[dict], themes: list[dict],
                 emotions: list[dict]):
        self.entites = entites
        self.alias: dict[str, dict] = {}           # forme normalisée -> {entite, ambigu...}
        for e in entites:
            for a in e["alias"]:
                self.alias[a["forme"]] = {"entite": e["id"], "ambigu": a["ambigu"],
                                          "type": e["type"]}
        self.alias_re = re.compile(alt_regex(list(self.alias)))
        self.alias_sure_re = re.compile(
            alt_regex([f for f, v in self.alias.items() if not v["ambigu"]]))
        self.stance = stance
        self.themes = themes
        self.emotions = emotions
        self._compile()

    def _expand(self, motif: str) -> str:
        return motif.replace("{ENTITE}", alt_regex(list(self.alias)).replace(r"\b", ""))

    def _compile(self) -> None:
        for r in self.stance:
            r["_re"] = re.compile(self._expand(r["motif"]))
        for t in self.themes:
            for term in t["termes"]:
                term["_re"] = re.compile(term["motif"])
        for e in self.emotions:
            for m in e["marqueurs"]:
                m["_re"] = re.compile(m["motif"])

    def entites_dans(self, norm: str) -> set[str]:
        """Entités citées (hors @handles)."""
        norm = strip_mentions(norm)
        return {self.alias[m.group(0)]["entite"] for m in self.alias_re.finditer(norm)}


def load_lexique(directory: str = DEFAULT_LEXIQUE) -> Lexique:
    """Charge et VALIDE le lexique ; lève LexiqueError au premier défaut."""
    data = _load_yaml(os.path.join(directory, "entites.yaml"))
    _need(isinstance(data, dict) and isinstance(data.get("entites"), list),
          "entites.yaml : clé 'entites' (liste) attendue")
    seen_alias: dict[str, str] = {}
    ids = set()
    for e in data["entites"]:
        _need(isinstance(e, dict) and e.get("id"), "entité sans 'id'")
        _need(e["id"] not in ids, f"entité en double : {e['id']}")
        ids.add(e["id"])
        _need(e.get("type") in TYPES_ENTITE, f"{e['id']} : type {e.get('type')!r} invalide")
        _need("camp" in e, f"{e['id']} : clé 'camp' requise (null si inconnu)")
        _need(e["camp"] in CAMPS_ENTITE, f"{e['id']} : camp {e['camp']!r} invalide")
        _need("nom" not in e or (isinstance(e["nom"], str) and e["nom"].strip()),
              f"{e['id']} : 'nom' doit être une chaîne non vide")
        _need(isinstance(e.get("alias"), list) and e["alias"], f"{e['id']} : alias requis")
        for a in e["alias"]:
            _need(isinstance(a.get("forme"), str) and a["forme"] == normalize(a["forme"]),
                  f"{e['id']} : alias {a.get('forme')!r} non normalisé (minuscules, sans accents)")
            _need(isinstance(a.get("ambigu"), bool), f"alias {a['forme']} : 'ambigu' booléen requis")
            _need(a["forme"] not in seen_alias,
                  f"alias {a['forme']!r} déjà pris par {seen_alias.get(a['forme'])}")
            seen_alias[a["forme"]] = e["id"]
    entites = data["entites"]

    st = _load_yaml(os.path.join(directory, "stance.yaml"))
    _need(isinstance(st, dict) and isinstance(st.get("regles"), list),
          "stance.yaml : clé 'regles' (liste) attendue")
    rule_ids = set()
    for r in st["regles"]:
        rid = r.get("id")
        _need(rid and rid not in rule_ids, f"stance : id manquant ou en double ({rid})")
        rule_ids.add(rid)
        _need(r.get("stance") in STANCES, f"{rid} : stance {r.get('stance')!r} invalide")
        _need(r.get("confiance") in CONFIANCES, f"{rid} : confiance invalide")
        cible = r.get("cible")
        _need(cible in CIBLES_SPECIALES or cible in ids,
              f"{rid} : cible {cible!r} invalide")
        if cible == "camp":
            _need(r.get("camp_vise"), f"{rid} : 'camp_vise' requis quand cible=camp")
        _need(isinstance(r.get("motif"), str), f"{rid} : motif manquant")
        if cible == "entite_capturee":
            _need("(?P<cible>" in r["motif"], f"{rid} : groupe nommé (?P<cible>...) requis")
        ex = r.get("exemples") or {}
        _need(ex.get("positifs"), f"{rid} : au moins un exemple positif inventé")
        _need("negatifs" in ex, f"{rid} : clé exemples.negatifs requise")

    th = _load_yaml(os.path.join(directory, "themes.yaml"))
    _need(isinstance(th, dict) and isinstance(th.get("themes"), list),
          "themes.yaml : clé 'themes' (liste) attendue")
    for t in th["themes"]:
        _need(t.get("theme") in THEMES, f"thème {t.get('theme')!r} hors contrat")
        _need(t["theme"] != "autre", "le thème 'autre' n'a pas de termes (résiduel)")
        for term in t["termes"]:
            _need(term.get("confiance") in CONFIANCES, f"{t['theme']} : confiance invalide")
            _need(isinstance(term.get("motif"), str), f"{t['theme']} : motif manquant")

    emotions: list[dict] = []
    path_emo = os.path.join(directory, "emotions.yaml")
    if os.path.exists(path_emo):
        em = _load_yaml(path_emo)
        emotions = (em or {}).get("emotions") or []
        for e in emotions:
            _need(e.get("emotion") in EMOTIONS, f"émotion {e.get('emotion')!r} hors contrat")
            for m in e["marqueurs"]:
                _need(m.get("confiance") in CONFIANCES, f"{e['emotion']} : confiance invalide")

    return Lexique(entites, st["regles"], th["themes"], emotions)


def stance_matches(lex: Lexique, norm: str) -> list[dict]:
    """Règles de stance déclenchées + cible résolue. Texte déjà normalisé."""
    hits = []
    present = None
    for r in lex.stance:
        m = r["_re"].search(norm)
        if not m:
            continue
        cible = r["cible"]
        if cible == "entite_capturee":
            forme = m.group("cible")
            info = lex.alias.get(forme)
            cible = info["entite"] if info else None
        elif cible == "co_mentionnee":
            present = present if present is not None else lex.entites_dans(norm)
            cible = sorted(present) or None
        hits.append({"regle": r["id"], "stance": r["stance"], "confiance": r["confiance"],
                     "cible": cible})
    return hits


def theme_matches(lex: Lexique, norm: str) -> list[tuple[str, str, str]]:
    return [(t["theme"], term["motif"], term["confiance"])
            for t in lex.themes for term in t["termes"] if term["_re"].search(norm)]


def emotion_matches(lex: Lexique, text: str, norm: str) -> list[tuple[str, str, str]]:
    # les émojis se testent sur le texte brut (la normalisation les conserve, mais
    # on évite tout risque de décomposition)
    return [(e["emotion"], m["motif"], m["confiance"])
            for e in lex.emotions for m in e["marqueurs"] if m["_re"].search(text) or m["_re"].search(norm)]


# --- corpus ---------------------------------------------------------------------
def load_posts(db_path: str) -> list[dict]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT created_at, text FROM posts").fetchall()
    finally:
        con.close()
    return [{"date": d, "text": t, "norm": normalize(t)} for d, t in rows]


def _top(counter: collections.Counter, n: int, min_count: int = 2) -> list[list]:
    return [[k, v] for k, v in counter.most_common(n) if v >= min_count]


def template_key(norm: str) -> str:
    """Signature de gabarit : 8 premiers mots, chiffres écrasés (repère les posts de robots)."""
    toks = TOKEN_RE.findall(URL_RE.sub(" ", re.sub(r"\d", "0", norm)))
    return " ".join(toks[:8])


def quasi_doublons(posts, seuil: int = 5) -> dict[str, int]:
    """Gabarits partagés par au moins `seuil` posts : {signature: taille}."""
    c = collections.Counter(template_key(p["norm"]) for p in posts)
    return {k: n for k, n in c.items() if n >= seuil and k}


def dedoublonner(posts, seuil: int = 5):
    """Garde un seul post par gabarit répété (>= seuil). Renvoie (posts, nb_retires)."""
    gros = quasi_doublons(posts, seuil)
    vus, out = set(), []
    for p in posts:
        k = template_key(p["norm"])
        if k in gros:
            if k in vus:
                continue
            vus.add(k)
        out.append(p)
    return out, len(posts) - len(out)


# --- sections -------------------------------------------------------------------
def sec_volumes(posts, **_):
    lengths = [len(p["text"]) for p in posts]
    jours = collections.Counter(p["date"][:10] for p in posts)
    return {"posts": len(posts), "caracteres_mediane": int(statistics.median(lengths)),
            "caracteres_moyenne": round(statistics.mean(lengths), 1),
            "du": min(p["date"] for p in posts)[:10], "au": max(p["date"] for p in posts)[:10],
            "jours": len(jours), "posts_par_jour_median": int(statistics.median(jours.values()))}


def sec_doublons(posts, **_):
    g = quasi_doublons(posts)
    return {"gabarits": len(g), "posts_concernes": sum(g.values()),
            "part_pct": round(100 * sum(g.values()) / len(posts), 1),
            "tailles": sorted(g.values(), reverse=True)[:15],
            "note": "signatures non affichées : ce sont des textes de robots, décrits à la main dans la doc"}


def sec_ngrammes(posts, top, **_):
    uni, bi, tri = collections.Counter(), collections.Counter(), collections.Counter()
    for p in posts:
        toks = tokenize(p["norm"])
        uni.update(t for t in set(toks) if t not in STOPWORDS and len(t) > 1 and not t.isdigit())
        bi.update(set(ngrams(toks, 2)))
        tri.update(set(ngrams(toks, 3)))
    return {"unigrammes": _top(uni, top), "bigrammes": _top(bi, top, 3),
            "trigrammes": _top(tri, top, 3), "note": "comptes en nombre de posts"}


def sec_hashtags(posts, top, **_):
    c = collections.Counter()
    for p in posts:
        c.update(set(HASHTAG_RE.findall(p["norm"])))
    return {"hashtags": _top(c, top)}


# racines de personnalités : on relève toutes les formes dérivées effectivement présentes
RACINES = ["macron", "melench", "meluch", "le pen", "lepen", "bardella", "glucksm", "gluksm",
           "zemmour", "philippe", "attal", "retailleau", "ruffin", "roussel", "tondelier",
           "hollande", "bayrou", "darmanin", "faure", "villepin", "trump", "poutine", "sarko",
           "mlp", "jlm", "raphael", "insoumis", "socialo", "ecolo", "facho", "islamo", "woke"]


def sec_derives(posts, **_):
    out = {}
    tokcount = collections.Counter()
    for p in posts:
        tokcount.update(set(tokenize(p["norm"])))
    for rac in RACINES:
        r = rac.replace(" ", "")
        formes = {t: n for t, n in tokcount.items() if t.replace("-", "").replace("'", "").find(r) >= 0
                  and (t.startswith(r) or t.endswith(r) or "-" in t)}
        if rac == "le pen":
            formes = {t: n for t, n in tokcount.items() if t.startswith("lepen") or t == "pen"}
        if formes:
            out[rac] = _top(collections.Counter(formes), 12, 1)
    return {"formes_par_racine": out, "note": "comptes en nombre de posts"}


def sec_emojis(posts, top, **_):
    c, n_posts = collections.Counter(), 0
    for p in posts:
        e = set(emojis_of(p["text"]))
        if e:
            n_posts += 1
        c.update(e)
    return {"posts_avec_emoji": n_posts, "emojis": _top(c, top, 3)}


# alias absents de keywords.txt mais fréquents dans le corpus (à évaluer)
CANDIDATS_AJOUT = ["ps", "mlp", "glucksman", "gluksmann", "raphael glucksmann", "macron", "macroniste",
                   "macronie", "sarkozy", "insoumis", "insoumise", "primaire", "ecologistes",
                   "marine tondelier", "gabriel attal", "fabien roussel", "jordan bardella",
                   "marine le pen", "renaissance", "horizons", "pen", "lepen", "melenchon2027",
                   "jlmelenchon", "retailleau", "fn", "ump", "nfp", "nupes"]


def sec_alias(posts, keywords, lex=None, **_):
    """Couverture de chaque alias de #identites (frontières de mot, comme l'ingestion)."""
    ids = keywords["identites"]
    id_re = re.compile(alt_regex(ids))
    per_alias = collections.Counter()
    seul = collections.Counter()           # posts où l'alias est le SEUL alias #identites
    mention = collections.Counter()        # posts où l'alias n'apparaît que dans un @handle
    n_kept_by_id = n_kept_sans_mention = 0
    for p in posts:
        found = {m.group(0) for m in id_re.finditer(p["norm"])}
        hors = {m.group(0) for m in id_re.finditer(strip_mentions(p["norm"]))}
        if found:
            n_kept_by_id += 1
        if hors:
            n_kept_sans_mention += 1
        per_alias.update(found)
        mention.update(found - hors)
        if len(found) == 1:
            seul.update(found)
    rows = [{"alias": a, "posts": per_alias.get(a, 0), "seul": seul.get(a, 0),
             "via_mention_seulement": mention.get(a, 0)} for a in ids]
    rows.sort(key=lambda r: -r["posts"])
    # alias candidats à l'ajout : présents dans le corpus SANS aucun alias #identites
    # (donc gardés seulement grâce à orientations + jargon) : borne basse du rappel perdu
    candidats = []
    for c in CANDIDATS_AJOUT:
        c_re = re.compile(alt_regex([c]))
        tous = sans = 0
        for p in posts:
            if c_re.search(p["norm"]):
                tous += 1
                if not id_re.search(p["norm"]):
                    sans += 1
        candidats.append({"alias": c, "posts": tous, "sans_alias_identites": sans})
    candidats.sort(key=lambda r: -r["posts"])
    return {"posts_gardes_par_identites": n_kept_by_id,
            "posts_gardes_hors_mentions": n_kept_sans_mention, "alias": rows,
            "alias_jamais_vus": [a for a in ids if not per_alias.get(a)],
            "candidats_ajout": candidats}


def sec_cooccurrences(posts, lexique, top, **_):
    """Entité × terme : comptes bruts et lift (co * N / (n_entité * n_terme))."""
    if lexique is None:
        return {"erreur": "lexique requis"}
    N = len(posts)
    termes_post, ent_post = [], []
    n_terme = collections.Counter()
    for p in posts:
        toks = {t for t in tokenize(p["norm"]) if t not in STOPWORDS and len(t) > 2 and not t.isdigit()}
        termes_post.append(toks)
        n_terme.update(toks)
        ent_post.append(lexique.entites_dans(p["norm"]))
    alias_toks = {t for a in lexique.alias for t in a.split()}
    n_ent = collections.Counter(e for s in ent_post for e in s)
    out = {}
    for e, ne in n_ent.most_common():
        if ne < 15:
            continue
        co = collections.Counter()
        for toks, ents in zip(termes_post, ent_post):
            if e in ents:
                co.update(toks)
        rows = []
        for t, c in co.items():
            if c < 5 or t in alias_toks:
                continue
            rows.append([t, c, round(c * N / (ne * n_terme[t]), 1)])
        rows.sort(key=lambda r: (-r[1]))
        out[e] = {"posts": ne, "termes_frequents": rows[:top],
                  "termes_distinctifs": sorted([r for r in rows if r[1] >= 6], key=lambda r: -r[2])[:top]}
    return out


def sec_regles(posts, lexique, **_):
    """Déclenchement des règles et couverture (part des posts décidables sans modèle)."""
    if lexique is None:
        return {"erreur": "lexique requis"}
    N = len(posts)
    freq_regle, freq_theme, freq_emo = collections.Counter(), collections.Counter(), collections.Counter()
    freq_alias = collections.Counter()
    cov = collections.Counter()
    stance_dist = collections.Counter()
    conflits = 0
    for p in posts:
        norm, text = strip_mentions(p["norm"]), p["text"]
        sm = stance_matches(lexique, norm)
        tm = theme_matches(lexique, norm)
        em = emotion_matches(lexique, text, norm)
        ents = lexique.entites_dans(norm)
        hors = strip_mentions(norm)
        sure = {lexique.alias[m.group(0)]["entite"] for m in lexique.alias_sure_re.finditer(hors)}
        freq_alias.update({m.group(0) for m in lexique.alias_re.finditer(hors)})
        for h in sm:
            freq_regle[h["regle"]] += 1
        for t, motif, c in tm:
            freq_theme[(t, motif, c)] += 1
        for e, motif, c in em:
            freq_emo[(e, motif, c)] += 1
        s_h = [h for h in sm if h["confiance"] == "haute" and h["cible"]]
        t_h = [t for t in tm if t[2] == "haute"]
        e_h = [e for e in em if e[2] == "haute"]
        if ents:
            cov["avec_entite"] += 1
        if sure:
            cov["avec_entite_non_ambigue"] += 1
        if sm:
            cov["stance_toute_confiance"] += 1
        if s_h:
            cov["stance_haute"] += 1
            for h in s_h:
                stance_dist[h["stance"]] += 1
        if t_h:
            cov["theme_haut"] += 1
        if e_h:
            cov["emotion_haute"] += 1
        if s_h or e_h:
            cov["stance_ou_emotion_haute"] += 1
        if s_h or t_h or e_h:
            cov["au_moins_une_regle_haute"] += 1
        if s_h and t_h:
            cov["stance_haute_et_theme_haut"] += 1
        if len({h["stance"] for h in s_h}) > 1:
            conflits += 1
    return {"posts": N,
            "couverture": {k: [v, round(100 * v / N, 1)] for k, v in cov.items()},
            "conflits_stance_haute": conflits,
            "stances_hautes_declenchees": dict(stance_dist),
            "freq_regles_stance": dict(freq_regle.most_common()),
            "freq_themes": [[t, m, c, n] for (t, m, c), n in freq_theme.most_common()],
            "freq_emotions": [[e, m, c, n] for (e, m, c), n in freq_emo.most_common()],
            "freq_alias": dict(freq_alias.most_common())}


SECTIONS = {"volumes": sec_volumes, "ngrammes": sec_ngrammes, "hashtags": sec_hashtags,
            "derives": sec_derives, "doublons": sec_doublons, "emojis": sec_emojis, "alias": sec_alias,
            "cooccurrences": sec_cooccurrences, "regles": sec_regles}


def run(db, keywords_path, lexique_dir, sections, top, dedup=False):
    posts = load_posts(db)
    if dedup:
        posts, _ = dedoublonner(posts)
    keywords = parse_keywords(keywords_path)
    lex = load_lexique(lexique_dir) if os.path.exists(os.path.join(lexique_dir, "entites.yaml")) else None
    ctx = {"posts": posts, "keywords": keywords, "lexique": lex, "lex": lex, "top": top}
    return {name: SECTIONS[name](**ctx) for name in sections}


def render(result: dict) -> str:
    """Rendu texte lisible (le JSON reste la sortie de référence)."""
    lines = []
    for name, data in result.items():
        lines.append(f"\n== {name} ==")
        lines.append(json.dumps(data, ensure_ascii=False, indent=1))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True, help="SQLite du corpus (lecture seule, jamais copié)")
    ap.add_argument("--keywords", default=DEFAULT_KEYWORDS)
    ap.add_argument("--lexique", default=DEFAULT_LEXIQUE)
    ap.add_argument("--sections", default=",".join(SECTIONS), help="liste séparée par des virgules")
    ap.add_argument("--dedoublonner", action="store_true",
                    help="garde un post par gabarit répété (>= 5), pour limiter l'effet des robots")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--json", help="écrit les agrégats dans ce fichier (hors dépôt de préférence)")
    args = ap.parse_args(argv)
    sections = [s.strip() for s in args.sections.split(",") if s.strip()]
    inconnues = [s for s in sections if s not in SECTIONS]
    if inconnues:
        ap.error(f"sections inconnues : {inconnues}")
    result = run(args.db, args.keywords, args.lexique, sections, args.top, args.dedoublonner)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
    else:
        sys.stdout.write(render(result) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
