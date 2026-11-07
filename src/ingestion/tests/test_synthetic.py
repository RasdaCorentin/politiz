"""Tests du générateur de posts synthétiques. Aucun réseau ; le lexique est celui du dépôt."""
import json
import re
import time
from pathlib import Path

import pytest

pytest.importorskip("yaml")        # requirements-producer.txt (absent de requirements-dev.txt)

import ingestion
import synthetic
from synthetic import DID_PREFIX, Mix, SyntheticGenerator

ICI = Path(__file__).resolve()
LEXIQUE = ICI.parents[3] / "ressources" / "lexique"
KEYWORDS = ICI.parents[1] / "keywords.txt"
THEMES = {"economie", "social-retraites", "immigration", "securite", "ecologie",
          "europe-international", "institutions", "sante-education", "campagne-sondages"}


@pytest.fixture(scope="module")
def lexique():
    return synthetic.load_lexique(LEXIQUE)


@pytest.fixture(scope="module")
def filtre():
    return ingestion.load_keywords(str(KEYWORDS))[1]


def melange(**parts):
    """Mélange nul sauf les parts données."""
    zero = dict(dup_ratio=0, offtopic_ratio=0, foreign_ratio=0, ops_ratio=0, leak_ratio=0)
    return Mix(**{**zero, **parts})


def generer(lexique, n, mix=None, **kw):
    gen = SyntheticGenerator(lexique, mix=mix, **kw)
    return gen, [gen.next_event() for _ in range(n)]


def textes(events):
    return [e["commit"]["record"]["text"] for e in events if "record" in e["commit"]]


# --- lecture du lexique ------------------------------------------------------------------

def test_mots_simples_garde_les_mots_litteraux():
    motif = (r"\b(?:budget|plf(?:2027)?|deficits?|ecoeurant\w*|palestin\w+|vote[rz]?"
             r"|(?:premier|second) tour|pouvoir d['’]achat)\b")
    assert synthetic.mots_simples(motif) == ["budget", "deficit", "ecoeurant"]


def test_emojis_et_mots_ne_se_melangent_pas():
    assert synthetic.emojis("🤮|🤢") == ["🤮", "🤢"]
    assert synthetic.emojis(r"\b(?:degueulasse)\b") == []
    assert synthetic.mots_simples("🤮|🤢") == []


def test_lexique_du_depot(lexique):
    assert len(lexique.exemples) > 50 and len(lexique.cibles) > 50
    assert set(lexique.themes) == THEMES
    assert lexique.emojis and lexique.mots_emotion
    assert "raphael" not in lexique.cibles                       # alias ambigu écarté
    mots = [w for ws in lexique.themes.values() for w in ws] + list(lexique.mots_emotion)
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9 \-]*", w) for w in mots)


def test_lexique_absent_ou_malforme(tmp_path):
    with pytest.raises(synthetic.LexiqueError):
        synthetic.load_lexique(tmp_path / "absent")
    for nom in ("stance", "entites", "themes", "emotions"):
        (tmp_path / f"{nom}.yaml").write_text("regles: 3\nentites: 3\nthemes: 3\nemotions: 3\n")
    with pytest.raises(synthetic.LexiqueError, match="forme inattendue"):
        synthetic.load_lexique(tmp_path)


# --- forme des événements ----------------------------------------------------------------

def test_forme_jetstream(lexique):
    _, events = generer(lexique, 400)
    ops = set()
    for ev in events:
        assert ev["did"].startswith(DID_PREFIX) and ev["kind"] == "commit"
        c = ev["commit"]
        assert c["collection"] == "app.bsky.feed.post"
        assert re.fullmatch(r"[2-7a-z]{13}", c["rev"]) and re.fullmatch(r"[2-7a-z]{13}", c["rkey"])
        ops.add(c["operation"])
        if c["operation"] == "delete":
            assert "record" not in c and "cid" not in c
            continue
        r = c["record"]
        assert r["$type"] == "app.bsky.feed.post" and r["text"]
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{3}Z|\+02:00)", r["createdAt"])
        assert c["cid"].startswith(synthetic.CID_PREFIX) and len(c["cid"]) == 59
    assert ops == {"create", "update", "delete"}


def test_time_us_est_maintenant_et_croissant(lexique):
    avant = time.time_ns() // 1000
    gen = SyntheticGenerator(lexique)
    t = [gen.next_event()["time_us"] for _ in range(200)]
    apres = time.time_ns() // 1000
    assert avant <= t[0] and t[-1] <= apres + 1000
    assert all(a < b for a, b in zip(t, t[1:]))


def test_encodage_utf8_compact_et_reversible(lexique):
    gen, events = generer(lexique, 300)
    brut = [gen.encode(e) for e in events]
    assert all(b"\\u" not in b and b'": ' not in b for b in brut)  # ni échappement, ni espace
    assert any(re.search(rb"[\xc3\xf0]", b) for b in brut)         # accents et émojis en UTF-8
    assert [json.loads(b) for b in brut] == events


def test_graine_fixe_donne_la_meme_suite(lexique):
    def suite(seed):
        gen = SyntheticGenerator(lexique, seed=seed, leak_marker="tm")
        return [gen.next_event(now_us=10**15 + i) for i in range(200)]
    assert suite(7) == suite(7)
    assert suite(7) != suite(8)


def test_did_fictif_partout_y_compris_dans_les_references(lexique):
    gen, events = generer(lexique, 1000)
    trouves = {d for e in events for d in re.findall(r"did:[a-z]+:\w+", gen.encode(e).decode())}
    assert trouves and all(d.startswith(DID_PREFIX) for d in trouves)


def test_facets_pointent_les_octets_du_texte(lexique):
    _, events = generer(lexique, 800)
    vus = set()
    for ev in events:
        r = ev["commit"].get("record", {})
        octets = r.get("text", "").encode("utf-8")
        for f in r.get("facets", []):
            morceau = octets[f["index"]["byteStart"]:f["index"]["byteEnd"]].decode("utf-8")
            feat = f["features"][0]
            kind = feat["$type"].rsplit("#", 1)[1]
            vus.add(kind)
            if kind == "tag":
                assert morceau == "#" + feat["tag"]
            elif kind == "link":
                assert morceau == feat["uri"]
            else:
                assert morceau.startswith("@") and feat["did"].startswith(DID_PREFIX)
    assert vus == {"tag", "link", "mention"}


# --- mélange -----------------------------------------------------------------------------

def test_composition_par_defaut(lexique):
    n = 8000
    gen, _ = generer(lexique, n, seed=3)
    attendu = {"dup": 0.10, "offtopic": 0.15, "foreign": 0.10, "ops": 0.03, "ontopic": 0.62}
    for kind, part in attendu.items():
        assert gen.kinds[kind] / n == pytest.approx(part, abs=0.02), kind


def test_doublons_repetent_un_texte_recent(lexique):
    _, events = generer(lexique, 600, melange(dup_ratio=0.5), seed=1)
    vus, repetes = set(), 0
    for t in textes(events):
        repetes += t in vus
        vus.add(t)
    assert repetes >= 0.4 * len(events)


def test_hors_sujet_est_rejete_par_les_mots_cles(lexique, filtre):
    _, events = generer(lexique, 300, melange(offtopic_ratio=1.0))
    assert all(filtre.test(ingestion.normalize(t)) == "rien" for t in textes(events))
    assert all(e["commit"]["record"]["langs"] == ["fr"] for e in events)


def test_sur_sujet_passe_en_majorite_la_regle_de_mots_cles(lexique, filtre):
    # Les exemples de stance.yaml visent le scoreur : hashtags collés (#avecX), surnoms et
    # « PS » n'entrent pas dans keywords.txt (environ 28 % des textes sur-sujet).
    _, events = generer(lexique, 1000, melange(), seed=2)
    gardes = sum(filtre.test(ingestion.normalize(t)) is None for t in textes(events))
    assert gardes / len(events) >= 0.6


def test_etranger_n_est_jamais_declare_francais(lexique):
    _, events = generer(lexique, 400, melange(foreign_ratio=1.0), seed=4)
    langs = [e["commit"]["record"].get("langs") for e in events]
    assert all(l is None or "fr" not in l for l in langs)
    assert None in langs and ["en"] in langs                     # absente, et déclarée autre


def test_autres_operations_sans_create(lexique):
    _, events = generer(lexique, 200, melange(ops_ratio=1.0), seed=5)
    assert {e["commit"]["operation"] for e in events} == {"update", "delete"}


def test_mot_temoin_dans_une_part_des_textes(lexique):
    _, events = generer(lexique, 4000, melange(leak_ratio=0.2), seed=6, leak_marker="temoinxyz")
    avec = [t for t in textes(events) if re.search(r"(^|\s)temoinxyz($|\s)", t)]
    assert len(avec) / len(textes(events)) == pytest.approx(0.2, abs=0.03)


def test_mot_temoin_genere_propre_a_chaque_execution(lexique):
    a = SyntheticGenerator(lexique, seed=1).leak_marker
    b = SyntheticGenerator(lexique, seed=1).leak_marker           # même graine, autre exécution
    assert a != b
    assert re.fullmatch(r"temoin[0-9a-f]{10}", a) and re.fullmatch(r"temoin[0-9a-f]{10}", b)


def test_melange_invalide():
    with pytest.raises(ValueError, match="entre 0 et 1"):
        Mix(dup_ratio=1.2)
    with pytest.raises(ValueError, match="dépasse 1"):
        Mix(dup_ratio=0.6, offtopic_ratio=0.5)


# --- débit -------------------------------------------------------------------------------

class Horloge:
    """Horloge simulée : dormir fait avancer le temps."""
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, secondes):
        self.t += secondes


def test_cadence_respecte_le_debit_sur_horloge_simulee():
    h = Horloge()
    n = sum(1 for _ in synthetic.cadence(50, 10, clock=h, sleep=h.sleep))
    assert abs(n - 500) <= 1


def test_cadence_ne_rattrape_pas_plus_d_une_seconde():
    h, n = Horloge(), 0
    for i, _ in enumerate(synthetic.cadence(100, stop=lambda: h.t >= 20, clock=h, sleep=h.sleep)):
        n += 1
        if i == 99:
            h.t += 8.0                  # blocage de 8 s (Kafka) au bout d'une seconde
    assert 1250 <= n <= 1350            # sans plafond : 2000 ; la rafale ne couvre qu'une seconde


def test_cadence_en_temps_reel():
    debut = time.monotonic()
    n = sum(1 for _ in synthetic.cadence(400, 0.5))
    assert time.monotonic() - debut == pytest.approx(0.5, abs=0.15)
    assert n == pytest.approx(200, rel=0.1)


def test_cadence_s_arrete_sur_demande():
    arret = []
    for i, _ in enumerate(synthetic.cadence(1000, stop=lambda: bool(arret))):
        if i == 9:
            arret.append(True)
    assert i == 9


def test_debit_nul_refuse():
    with pytest.raises(ValueError):
        next(synthetic.cadence(0))


# --- ligne de commande -------------------------------------------------------------------

def test_apercu_en_ligne_de_commande(capsysbinary):
    assert synthetic.main(["--count", "3", "--seed", "1", "--leak-marker", "tm"]) == 0
    sortie = capsysbinary.readouterr()
    lignes = sortie.out.splitlines()
    assert len(lignes) == 3 and all(json.loads(l)["did"].startswith(DID_PREFIX) for l in lignes)
    assert b"marqueur : tm" in sortie.err
