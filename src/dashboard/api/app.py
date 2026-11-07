"""API de lecture du tableau de bord : application WSGI sans framework, servie par Gunicorn.

Trois routes en lecture seule (routes du dashboard dans docs/technique/contrats-poc.md) :
`GET /api/tableau` (JSON `tableau` v4), `GET /api/evenements` (catalogue v1) et `GET /api/sante`. Les erreurs sortent en JSON ;
le détail d'une panne de base reste dans les journaux.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Iterable
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import parse_qs

import calculs
import donnees
from calculs import PERIODE_PERSO, PERIODES
from camps import charger_lexique
from config import PERIODE_DEFAUT, Config, depuis_env
from modele import construire
from serialisation import serialiser, serialiser_evenements

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
journal = logging.getLogger("dashboard-api")

SEUIL_MAX = 10_000
METHODES = ("GET", "HEAD")
Reponse = tuple[str, Any]  # (statut HTTP, corps)


class ParametreInvalide(Exception):
    """Paramètre de requête hors des valeurs admises : réponse 400."""


def _parametre(qs: dict[str, list[str]], nom: str) -> str | None:
    valeurs = qs.get(nom)
    if valeurs is None:
        return None
    if len(valeurs) > 1:
        raise ParametreInvalide(f"{nom} : une seule valeur attendue")
    return valeurs[0]


DATE_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _date(brut: str, nom: str) -> date:
    if not DATE_ISO.fullmatch(brut):
        raise ParametreInvalide(f"{nom} : date AAAA-MM-JJ")
    try:
        return date.fromisoformat(brut)
    except ValueError as exc:
        raise ParametreInvalide(f"{nom} : date AAAA-MM-JJ valide") from exc


def _periode(qs: dict[str, list[str]]) -> tuple[str, tuple[date, date] | None]:
    """(code de période, plage de dates ou `None`). `debut` et `fin` ensemble imposent `perso`."""
    code = _parametre(qs, "periode")
    debut, fin = _parametre(qs, "debut"), _parametre(qs, "fin")
    if debut is None and fin is None:
        code = PERIODE_DEFAUT if code is None else code
        if code not in PERIODES:
            raise ParametreInvalide("periode : 24h, 7j, 30j ou tout (perso exige debut et fin)")
        return code, None
    if debut is None or fin is None:
        raise ParametreInvalide("debut et fin vont ensemble")
    if code not in (None, PERIODE_PERSO):
        raise ParametreInvalide("debut et fin exigent periode=perso, ou aucune periode")
    return PERIODE_PERSO, (_date(debut, "debut"), _date(fin, "fin"))


def _seuil(qs: dict[str, list[str]], defaut: int) -> int:
    brut = _parametre(qs, "seuil")
    if brut is None:
        return defaut
    if not re.fullmatch(r"[0-9]{1,5}", brut) or not 1 <= int(brut) <= SEUIL_MAX:
        raise ParametreInvalide(f"seuil : entier de 1 à {SEUIL_MAX}")
    return int(brut)


def _etiquettes(entete: str) -> set[str]:
    """Étiquettes d'un `If-None-Match` (liste séparée par des virgules, préfixe `W/` ignoré)."""
    return {e.strip().removeprefix("W/") for e in entete.split(",") if e.strip()}


def _ok(environ: dict, start_response: Callable, methode: str, corps: dict[str, Any]) -> Iterable[bytes]:
    # ETag sur les données seules : `generated_at` change à chaque lecture et annulerait le 304.
    stable = {cle: val for cle, val in corps.items() if cle != "generated_at"}
    etag = '"' + hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32] + '"'
    entetes = [("ETag", etag), ("X-Generated-At", corps["generated_at"])]
    if etag in _etiquettes(environ.get("HTTP_IF_NONE_MATCH", "")):
        start_response("304 Not Modified", [("Cache-Control", "no-store"), *entetes, ("Content-Length", "0")])
        return [b""]
    return _reponse(start_response, "200 OK", corps, methode, entetes)


def _reponse(start_response: Callable, statut: str, corps: Any, methode: str, extra: Iterable[tuple[str, str]] = ()) -> Iterable[bytes]:
    charge = json.dumps(corps, ensure_ascii=False).encode()
    entetes = [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store"), *extra]
    start_response(statut, [*entetes, ("Content-Length", str(len(charge)))])
    return [] if methode == "HEAD" else [charge]


def creer_app(
    cfg: Config | None = None, horloge: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
) -> Callable:
    """Application WSGI. `cfg` et `horloge` se fixent dans les tests ; sinon ils viennent de l'environnement."""
    cfg = cfg or depuis_env()

    def tableau(qs: dict[str, list[str]]) -> Reponse:
        code, plage = _periode(qs)
        seuil = _seuil(qs, cfg.seuil_defaut)
        maintenant = horloge()
        try:
            calculs.valider_periode(code, plage, maintenant)
        except calculs.PeriodeInvalide as exc:
            raise ParametreInvalide(str(exc)) from exc
        etat = donnees.etat_base(cfg)
        bornes = calculs.bornes(code, maintenant, etat.premiere, plage)
        brut = donnees.lire(cfg, bornes, etat)
        vue = construire(
            brut,
            charger_lexique(cfg.lexique_dir),
            seuil,
            cfg.fraicheur_ok_min,
            cfg.fraicheur_alerte_min,
            maintenant,
        )
        return "200 OK", serialiser(vue, cfg, maintenant)

    def catalogue(_qs: dict[str, list[str]]) -> Reponse:
        disponible, liste = donnees.evenements(cfg)
        return "200 OK", serialiser_evenements(disponible, liste, horloge())

    def sante(_qs: dict[str, list[str]]) -> Reponse:
        donnees.ping(cfg)
        return "200 OK", {"status": "ok"}

    routes = {"/api/tableau": tableau, "/api/evenements": catalogue, "/api/sante": sante}

    def app(environ: dict, start_response: Callable) -> Iterable[bytes]:
        chemin = environ.get("PATH_INFO", "")
        methode = environ.get("REQUEST_METHOD", "GET")
        if chemin not in routes:
            return _reponse(start_response, "404 Not Found", {"erreur": "route inconnue"}, methode)
        if methode not in METHODES:
            return _reponse(
                start_response, "405 Method Not Allowed", {"erreur": "lecture seule"}, methode, [("Allow", "GET, HEAD")]
            )
        qs = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        try:
            statut, corps = routes[chemin](qs)
        except ParametreInvalide as exc:
            return _reponse(start_response, "400 Bad Request", {"erreur": str(exc)}, methode)
        except donnees.ErreurBase as exc:
            journal.error("base injoignable : %s", exc)
            return _reponse(start_response, "503 Service Unavailable", {"erreur": "base injoignable"}, methode)
        except Exception:  # noqa: BLE001 (une route qui échoue ne doit pas exposer sa trace)
            journal.exception("erreur interne sur %s", chemin)
            return _reponse(start_response, "500 Internal Server Error", {"erreur": "erreur interne"}, methode)
        if "generated_at" in corps:
            return _ok(environ, start_response, methode, corps)
        return _reponse(start_response, statut, corps, methode)

    return app


app = creer_app()
