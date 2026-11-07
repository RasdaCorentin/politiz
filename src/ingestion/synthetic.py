#!/usr/bin/env python3
"""Générateur de posts synthétiques, de même forme que les événements Jetstream.

Il sert aux tests et aux essais de charge du pipeline (contrat Kafka et contrôle de non-fuite de
docs/technique/contrats-poc.md). Aucun post réel : les textes viennent des exemples
inventés, des alias, des thèmes et des émotions de ressources/lexique/ (lus comme des
données, jamais importés) et de quelques modèles de phrases.

Chaque événement porte un `did` fictif reconnaissable (préfixe `did:plc:synthetic`). Un
mot-témoin (LEAK_MARKER) est inséré dans une part des textes : le contrôle de non-fuite
les cherche dans MinIO, ClickHouse et les journaux.

Usage (aperçu de N événements, un JSON par ligne) :
    python synthetic.py --count 5 --seed 1
"""
import argparse
import json
import os
import random
import re
import secrets
import sys
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

COLLECTION = "app.bsky.feed.post"
DID_PREFIX = "did:plc:synthetic"          # reconnaissable dans tous les événements
CID_PREFIX = "bafyreisynthetic"           # idem pour les `cid` (59 caractères comme un vrai)
B32 = "234567abcdefghijklmnopqrstuvwxyz"  # alphabet des rkey / rev (TID)

# Modèles de phrases. Les deux premières listes décrivent des posts politiques (les modèles de
# thème portent une orientation et du jargon, donc passent la règle de keywords.txt) ; les deux
# suivantes n'en contiennent aucun mot-clé (vérifié par les tests avec keywords.txt).
MENTION_MODELES = [
    "{cible} sera-t-il candidat en 2027 ?",
    "Sondage : {cible} progresse dans les intentions de vote.",
    "Débat ce soir avec {cible}, je regarde ça.",
    "Ce que propose {cible} sur {theme}, ça mérite d'être lu.",
    "On reparle de {cible} dans toutes les conversations.",
    "{cible} a encore parlé de {theme} ce matin.",
]
THEME_MODELES = [
    "À gauche comme à droite, le sujet {theme} va compter dans la campagne de 2027.",
    "Le gouvernement et la gauche restent flous sur {theme}.",
    "{theme} : ce que la droite et la gauche proposent pour la campagne.",
    "La droite parle beaucoup de {theme}, mais que fera le prochain gouvernement ?",
]
HORS_SUJET = [
    "Ce matin, la boulangerie était fermée, je me suis contenté d'un café.",
    "Match nul hier soir, on a quand même passé une bonne soirée.",
    "Je viens de finir ce roman, la fin m'a vraiment surpris.",
    "Il pleut sur Lyon depuis ce matin, parfait pour rester sous la couette.",
    "Recette du jour : tarte aux pommes, pâte maison et beaucoup de beurre.",
    "Mon chat a décidé que mon clavier était son nouveau lit.",
    "Premier jour de randonnée, les jambes sont lourdes mais la vue est superbe.",
    "Quelqu'un connaît une bonne adresse de ramen à Nantes ?",
]
ETRANGER = [
    ("en", "Just finished the new season, absolutely loved the ending."),
    ("en", "Coffee first, then the world. Have a great day everyone!"),
    ("es", "Hoy hace un día perfecto para salir a caminar por la playa."),
    ("de", "Heute gibt es Kuchen und Kaffee, das Wochenende kann kommen."),
    ("pt", "Hoje o dia foi longo, mas o jantar foi ótimo."),
]

FACET_RE = re.compile(r"(?P<tag>#\w+)|(?P<mention>@[\w-]+\.invalid)|(?P<lien>https://\S+)")


class LexiqueError(Exception):
    """Dossier du lexique absent ou fichier de forme inattendue."""


@dataclass(frozen=True)
class Lexique:
    exemples: tuple[str, ...]            # stance.yaml : textes inventés qui déclenchent une règle
    cibles: tuple[str, ...]              # entites.yaml : alias non ambigus
    themes: dict[str, tuple[str, ...]]   # themes.yaml : thème -> mots simples
    emojis: tuple[str, ...]              # emotions.yaml : émojis
    mots_emotion: tuple[str, ...]        # emotions.yaml : mots simples


def repo_lexique_dir() -> str:
    """ressources/lexique du dépôt (poste de développement, `../../ressources/lexique`)."""
    return str(Path(__file__).resolve().parent.parent.parent / "ressources" / "lexique")


def default_lexique_dir(env=os.environ) -> str:
    """LEXIQUE_DIR (`/app/lexique` dans l'image), sinon le lexique du dépôt."""
    return env.get("LEXIQUE_DIR") or repo_lexique_dir()


def _jetons(motif: str) -> list[str]:
    """Alternatives de premier niveau d'un motif `\\b(?:a|b|c)\\b` ou `a|b|c`."""
    m = motif.replace("\\b", "")
    if m.startswith("(?:") and m.endswith(")"):
        m = m[3:-1]
    jetons, courant, prof = [], [], 0
    for c in m:
        prof += (c == "(") - (c == ")")
        if c == "|" and prof == 0:
            jetons.append("".join(courant))
            courant = []
        else:
            courant.append(c)
    jetons.append("".join(courant))
    return jetons


def mots_simples(motif: str) -> list[str]:
    """Mots littéraux d'un motif de thème ou d'émotion ; ignore les alternatives à regex.

    `deficits?` donne `deficit` ; `ecoeurant\\w*` donne `ecoeurant` ; `palestin\\w+`,
    `vote[rz]?` et les sous-groupes sont écartés (ils ne désignent pas un mot unique).
    """
    mots = []
    for j in _jetons(motif):
        if j.endswith("\\w*"):
            j = j[:-3]
        elif re.search(r"[a-z]\?$", j):
            j = j[:-2]
        if re.fullmatch(r"[a-z0-9][a-z0-9 \-]*", j):
            mots.append(j)
    return mots


def emojis(motif: str) -> list[str]:
    """Jetons d'un motif formés de caractères non ASCII seulement (émojis)."""
    return [j for j in _jetons(motif) if j and all(ord(c) > 0x2000 for c in j)]


def load_lexique(dossier: str | os.PathLike) -> Lexique:
    """Lit stance.yaml, entites.yaml, themes.yaml et emotions.yaml du dossier."""
    try:
        import yaml
    except ImportError as e:
        raise LexiqueError("PyYAML absent (requirements-producer.txt)") from e

    def lire(nom: str):
        try:
            return yaml.safe_load((Path(dossier) / nom).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as e:
            raise LexiqueError(f"{nom} illisible ({type(e).__name__})") from e

    try:
        exemples = [x for r in lire("stance.yaml")["regles"]
                    for x in ((r.get("exemples") or {}).get("positifs") or [])
                    if isinstance(x, str) and x.strip()]
        cibles = [a["forme"] for e in lire("entites.yaml")["entites"]
                  for a in e["alias"] if not a.get("ambigu")]
        themes: dict[str, tuple[str, ...]] = {}
        for t in lire("themes.yaml")["themes"]:
            mots = sorted({w for x in t["termes"] for w in mots_simples(x["motif"])})
            if mots:
                themes[t["theme"]] = tuple(mots)
        motifs = [x["motif"] for e in lire("emotions.yaml")["emotions"] for x in e["marqueurs"]]
    except (KeyError, TypeError, AttributeError) as e:
        raise LexiqueError(f"forme inattendue ({type(e).__name__})") from e
    if not (exemples and cibles and themes):
        raise LexiqueError("lexique vide (exemples, alias ou thèmes)")
    return Lexique(
        exemples=tuple(exemples), cibles=tuple(cibles), themes=themes,
        emojis=tuple(sorted({e for m in motifs for e in emojis(m)})),
        mots_emotion=tuple(sorted({w for m in motifs for w in mots_simples(m)})))


@dataclass(frozen=True)
class Mix:
    """Composition du flux. Les quatre premières parts s'excluent ; le reste est politique."""
    dup_ratio: float = 0.10        # texte identique à celui d'un post récent (dédoublonnage)
    offtopic_ratio: float = 0.15   # français, sans cible, thème ni émotion (filtre fin)
    foreign_ratio: float = 0.10    # langue déclarée autre que `fr`, ou absente (filtre de langue)
    ops_ratio: float = 0.03        # update et delete (create seulement)
    leak_ratio: float = 0.20       # part des textes qui portent le mot-témoin

    def __post_init__(self):
        for nom, v in vars(self).items():
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{nom} doit être compris entre 0 et 1 (reçu {v})")
        if self.dup_ratio + self.offtopic_ratio + self.foreign_ratio + self.ops_ratio > 1.0:
            raise ValueError("dup + offtopic + foreign + ops dépasse 1")


def add_mix_arguments(ap: argparse.ArgumentParser, env=os.environ) -> None:
    """Options du mélange, valeurs par défaut lues dans PRODUCER_*_RATIO."""
    d = Mix()
    for nom, defaut in vars(d).items():
        var = "PRODUCER_" + nom.upper()
        ap.add_argument("--" + nom.replace("_", "-"), dest=nom, type=float,
                        default=env.get(var) or defaut, help=f"{var} (défaut {defaut})")


def mix_from_args(args) -> Mix:
    return Mix(**{nom: getattr(args, nom) for nom in vars(Mix())})


class SyntheticGenerator:
    """Événements Jetstream fictifs. Un tirage graine fixe = une suite fixe (à horloge égale)."""

    def __init__(self, lexique: Lexique, *, seed: int | None = None, mix: Mix | None = None,
                 leak_marker: str | None = None, authors: int = 500):
        self.lex = lexique
        self.rng = random.Random(seed)
        self.mix = mix or Mix()
        # propre à chaque exécution si absent (indépendant de la graine)
        self.leak_marker = leak_marker or "temoin" + secrets.token_hex(5)
        self.authors = authors
        self.kinds: Counter[str] = Counter()        # ontopic, dup, offtopic, foreign, ops
        self._recent: deque[str] = deque(maxlen=100)  # textes français récents (doublons)
        self._last_us = 0

    # --- briques -------------------------------------------------------------------------
    def _tid(self) -> str:
        return "".join(self.rng.choices(B32, k=13))

    def _cid(self) -> str:
        return CID_PREFIX + "".join(self.rng.choices(B32, k=43))

    def _did(self) -> str:
        return f"{DID_PREFIX}{self.rng.randrange(self.authors):04d}"

    def _uri(self) -> str:
        return f"at://{self._did()}/{COLLECTION}/{self._tid()}"

    def _theme_word(self) -> str:
        theme = self.rng.choice(sorted(self.lex.themes))
        return self.rng.choice(self.lex.themes[theme])

    def _cible(self) -> str:
        forme = self.rng.choice(self.lex.cibles)
        if self.rng.random() < 0.2:
            return forme                                   # tout en minuscules, comme beaucoup de posts
        return forme.upper() if len(forme) <= 4 and " " not in forme else forme.title()

    def _created_at(self, now_us: int) -> str:
        t = now_us / 1e6 - self.rng.uniform(0.2, 3.0)
        if self.rng.random() < 0.02:                       # horloge du client fausse
            t += self.rng.choice((-1, 1)) * self.rng.uniform(86400, 3 * 86400)
        dt = datetime.fromtimestamp(t, timezone.utc)
        if self.rng.random() < 0.15:                       # le client écrit son fuseau local
            return dt.astimezone(timezone(timedelta(hours=2))).isoformat(timespec="seconds")
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

    def _ontopic(self) -> str:
        r = self.rng.random()
        if r < 0.45:
            base = self.rng.choice(self.lex.exemples)
        elif r < 0.75:
            base = self.rng.choice(MENTION_MODELES).format(
                cible=self._cible(), theme=self._theme_word())
        else:
            base = self.rng.choice(THEME_MODELES).format(theme=self._theme_word())
        rng, lex = self.rng, self.lex
        if lex.emojis and rng.random() < 0.20:
            base += " " + rng.choice(lex.emojis)
        if lex.mots_emotion and rng.random() < 0.08:
            base += f" C'est vraiment {rng.choice(lex.mots_emotion)}."
        if rng.random() < 0.10:
            base += " https://exemple.invalid/a/" + rng.randbytes(3).hex()
        if rng.random() < 0.08:
            base = f"@personne{rng.randrange(100):02d}-fictive.invalid {base}"
        if rng.random() < 0.10:
            base += " #" + re.sub(r"[ \-]", "", self._theme_word())
        return base

    def _facets(self, texte: str) -> list[dict]:
        """Hashtags, mentions et liens du texte, avec leurs positions en octets UTF-8."""
        facettes = []
        for m in FACET_RE.finditer(texte):
            debut = len(texte[:m.start()].encode("utf-8"))
            fin = debut + len(m.group().encode("utf-8"))
            if m.lastgroup == "tag":
                feature = {"$type": "app.bsky.richtext.facet#tag", "tag": m.group()[1:]}
            elif m.lastgroup == "mention":
                feature = {"$type": "app.bsky.richtext.facet#mention", "did": self._did()}
            else:
                feature = {"$type": "app.bsky.richtext.facet#link", "uri": m.group()}
            facettes.append({"index": {"byteStart": debut, "byteEnd": fin}, "features": [feature]})
        return facettes

    def _record(self, now_us: int, langs: list[str] | None, texte: str) -> dict:
        record: dict = {"$type": COLLECTION, "createdAt": self._created_at(now_us)}
        if langs is not None:
            record["langs"] = langs
        if self.rng.random() < 0.20:                       # réponse : `uri` contient un did
            ref = {"cid": self._cid(), "uri": self._uri()}
            record["reply"] = {"parent": ref, "root": ref}
        record["text"] = texte
        facets = self._facets(texte)
        if facets:
            record["facets"] = facets
        if self.rng.random() < 0.05:
            record["embed"] = {"$type": "app.bsky.embed.external", "external": {
                "uri": "https://exemple.invalid/article/" + self.rng.randbytes(3).hex(),
                "title": "Titre d'article inventé", "description": "Description inventée."}}
        return record

    # --- API -----------------------------------------------------------------------------
    def next_event(self, now_us: int | None = None) -> dict:
        """Prochain événement. `time_us` = maintenant, strictement croissant."""
        if now_us is None:
            now_us = time.time_ns() // 1000
        now_us = max(now_us, self._last_us + 1)
        self._last_us = now_us
        rng, mix = self.rng, self.mix

        x, kind = rng.random(), "ontopic"
        for nom, part in (("ops", mix.ops_ratio), ("foreign", mix.foreign_ratio),
                          ("offtopic", mix.offtopic_ratio), ("dup", mix.dup_ratio)):
            if x < part:
                kind = nom if nom != "dup" or self._recent else "ontopic"
                break
            x -= part
        self.kinds[kind] += 1

        operation, langs = "create", ["fr"]
        if kind == "foreign":
            code, texte = rng.choice(ETRANGER)
            langs = [code] if rng.random() < 0.9 else None     # `langs` absent dans 10 % des cas
        elif kind == "dup":
            texte = rng.choice(self._recent)
        else:
            texte = rng.choice(HORS_SUJET) if kind == "offtopic" else self._ontopic()
            if kind == "ops":
                operation = rng.choice(("update", "delete"))
        if kind != "dup" and rng.random() < mix.leak_ratio:
            texte += " " + self.leak_marker
        if kind in ("ontopic", "offtopic"):
            self._recent.append(texte)

        commit = {"rev": self._tid(), "operation": operation, "collection": COLLECTION,
                  "rkey": self._tid()}
        if operation != "delete":                          # un `delete` n'a ni record ni cid
            commit["record"] = self._record(now_us, langs, texte)
            commit["cid"] = self._cid()
        return {"did": self._did(), "time_us": now_us, "kind": "commit", "commit": commit}

    @staticmethod
    def encode(event: dict) -> bytes:
        """JSON compact, UTF-8 non échappé, comme le sérialiseur de Jetstream."""
        return json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def next_raw(self, now_us: int | None = None) -> tuple[bytes, int]:
        """(valeur à publier, time_us) du prochain événement."""
        event = self.next_event(now_us)
        return self.encode(event), event["time_us"]


def cadence(rate: float, duration: float = 0.0, *, stop=None, clock=time.monotonic,
            sleep=time.sleep):
    """Cède une fois par événement dû, à `rate` événements par seconde.

    `duration` en secondes (0 = sans fin). `stop()` vrai arrête la boucle. Un retard de plus
    d'une seconde (Kafka bloqué) n'est pas rattrapé en rafale.
    """
    if rate <= 0:
        raise ValueError("le débit doit être positif")
    pas = 1.0 / rate
    debut = clock()
    echeance = debut
    fin = debut + duration if duration > 0 else None
    while not (stop and stop()):
        now = clock()
        if fin is not None and now >= fin:
            return
        if now < echeance:
            sleep(min(echeance - now, 0.05))
            continue
        echeance = max(echeance, now - 1.0)
        yield
        echeance += pas


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Posts synthétiques au format Jetstream (JSON par ligne)")
    ap.add_argument("--count", type=int, default=10, help="nombre d'événements")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--lexique-dir", default=default_lexique_dir())
    ap.add_argument("--leak-marker", default=os.environ.get("LEAK_MARKER") or None)
    add_mix_arguments(ap)
    args = ap.parse_args(argv)
    try:
        gen = SyntheticGenerator(load_lexique(args.lexique_dir), seed=args.seed,
                                 mix=mix_from_args(args), leak_marker=args.leak_marker)
    except (LexiqueError, ValueError) as e:
        ap.error(str(e))
    print(f"marqueur : {gen.leak_marker}", file=sys.stderr)
    for _ in range(args.count):
        sys.stdout.buffer.write(gen.next_raw()[0] + b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
