"""Saisie rapide d'un lot gold (Streamlit) : un post à la fois, sauvegarde à chaque validation.

Lancement depuis src/training (dossier du corpus fourni par SAE_CORPUS_DIR ou --corpus-dir) :

    SAE_CORPUS_DIR=<dossier du corpus> streamlit run annotation/app.py -- \\
        --lot <dossier du corpus>/annotation/lots_gold/lot_gold_01.jsonl --annotateur <prenom>

Variables équivalentes : SAE_LOT, SAE_ANNOTATEUR. Sortie : <corpus>/annotation/annotations/<prenom>.jsonl.
Au lancement, les posts déjà annotés dans ce fichier sont sautés.
"""
from __future__ import annotations

import html
import os
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # permet `import annotation`

from annotation.common import annotation_dir, entity_choices, load_entites, load_schema  # noqa: E402
from annotation.saisie import config, contexte, enregistrement, lire_lot, valeurs_initiales  # noqa: E402
from annotation.storage import (annotations_path, first_unannotated, load_annotations,  # noqa: E402
                                save_annotation)

# Raccourcis clavier : Alt+Entrée enregistre, Alt+← revient au post précédent.
JS = """
<script>
const d = window.parent.document;
if (!window.parent.__annotKeys) {
  window.parent.__annotKeys = true;
  function clic(txt) {
    for (const b of d.querySelectorAll('button')) { if (b.innerText.includes(txt)) { b.click(); return; } }
  }
  d.addEventListener('keydown', (e) => {
    if (e.altKey && e.key === 'Enter') { clic('Enregistrer'); e.preventDefault(); }
    if (e.altKey && e.key === 'ArrowLeft') { clic('Précédent'); e.preventDefault(); }
  });
}
</script>
"""

# Affichage seulement : la valeur enregistrée reste celle du schéma.
AFFICHAGE = {"colere": "colère", "degout": "dégoût", "social-retraites": "social · retraites",
             "europe-international": "Europe · international", "sante-education": "santé · éducation",
             "campagne-sondages": "campagne · sondages", "groupe-politique": "groupe politique"}


def libelle(valeur: str) -> str:
    return AFFICHAGE.get(valeur, valeur)


def texte_html(texte: str) -> str:
    """Texte du post : échappé, retours à la ligne conservés, pas de rendu Markdown."""
    return (f'<div style="white-space:pre-wrap;font-size:1.15rem;line-height:1.55">'
            f"{html.escape(texte)}</div>")


def init_widgets(prefix: str, existing: dict | None, entites: list[str]) -> None:
    """Charge dans session_state les valeurs du post (une fois par post et par session)."""
    if f"{prefix}init" in st.session_state:
        return
    v = valeurs_initiales(existing, entites)
    st.session_state[f"{prefix}pertinent"] = v["pertinent"]
    st.session_state[f"{prefix}cibles"] = [c["entite"] for c in v["cibles"]]
    for c in v["cibles"]:
        st.session_state[f"{prefix}stance:{c['entite']}"] = c.get("stance")
    st.session_state[f"{prefix}themes"] = list(v["themes"] or [])
    for k in ("emotion", "ironie", "regle_suffit"):
        st.session_state[f"{prefix}{k}"] = v[k]
    st.session_state[f"{prefix}indice"] = v["indice"] or ""
    st.session_state[f"{prefix}commentaire"] = v["commentaire"] or ""
    st.session_state[f"{prefix}init"] = True


def choix_boutons(cle: str, options: list[str], titre: str | None = None) -> str | None:
    """Boutons larges, dans l'ordre du schéma ; le choix courant est en couleur d'accent.

    La valeur vit dans session_state[cle] (pas un widget : un clic relance la page).
    """
    if titre:
        st.caption(titre)
    courant = st.session_state.get(cle)
    for debut in range(0, len(options), 4):  # 4 boutons par rangée au plus
        rangee = options[debut:debut + 4]
        for col, valeur in zip(st.columns(len(rangee)), rangee):
            if col.button(libelle(valeur), key=f"{cle}|{valeur}", use_container_width=True,
                          type="primary" if valeur == courant else "secondary"):
                st.session_state[cle] = valeur
                st.rerun()
    return st.session_state.get(cle)


def formulaire(prefix: str, schema: dict, entites: list[str]) -> dict:
    """Choix de l'annotateur pour le post affiché. Les champs non affichés restent vides."""
    choix = {"pertinent": choix_boutons(f"{prefix}pertinent", schema["pertinent"]["valeurs"],
                                        schema["pertinent"]["aide"])}
    if choix["pertinent"] in ("oui", "doute"):
        if choix["pertinent"] == "doute":
            st.caption("Doute : les autres champs sont facultatifs.")
        cibles = st.multiselect("Cibles (entités visées)", entites, key=f"{prefix}cibles",
                                placeholder="Choisir dans la liste", format_func=libelle)
        choix["cibles"] = [
            {"entite": e, "stance": choix_boutons(f"{prefix}stance:{e}", schema["cibles"]["stance"],
                                                  f"Stance envers « {libelle(e)} »")}
            for e in cibles]
        choix["themes"] = st.pills("Thèmes", schema["themes"]["valeurs"], selection_mode="multi",
                                   key=f"{prefix}themes", format_func=libelle) or []
        choix["emotion"] = choix_boutons(f"{prefix}emotion", schema["emotion"]["valeurs"],
                                         "Émotion dominante")
        choix["ironie"] = choix_boutons(f"{prefix}ironie", schema["ironie"]["valeurs"], "Ironie ?")
        choix["regle_suffit"] = choix_boutons(f"{prefix}regle_suffit", schema["regle_suffit"]["valeurs"],
                                              "Une règle suffit-elle ?")
        if choix["regle_suffit"] == "oui":
            choix["indice"] = st.text_input("Indice (l'expression qui suffit)", key=f"{prefix}indice")
    choix["commentaire"] = st.text_input("Commentaire (doute, cas limite)", key=f"{prefix}commentaire")
    return choix


def main() -> None:
    st.set_page_config(page_title="Annotation gold", layout="wide")
    components.html(JS, height=0)

    lot_path, nom, corpus = config(sys.argv[1:], dict(os.environ))
    if not lot_path or not nom:
        st.error("Lancement incomplet. Exemple : streamlit run annotation/app.py -- "
                 "--lot <fichier.jsonl> --annotateur <prénom>")
        st.stop()
    try:
        posts = lire_lot(lot_path)
        schema = load_schema()
        entites = entity_choices(schema, load_entites())
        path = annotations_path(annotation_dir(corpus), nom)
    except (OSError, ValueError, SystemExit) as e:
        st.error(f"Lancement impossible : {e}")
        st.stop()

    annots = load_annotations(path)
    n = len(posts)
    faits = sum(p["post_id"] in annots for p in posts)
    st.progress(faits / n, text=f"{faits} / {n} annotés")
    st.caption(f"Lot {lot_path.stem} · annotateur {nom}")

    cle_pos = f"pos:{path}"
    if cle_pos not in st.session_state:  # reprise au premier post non annoté
        st.session_state[cle_pos] = first_unannotated(posts, annots)
    idx = st.session_state[cle_pos]

    if idx >= n:
        st.success("Lot terminé. Merci !")
        if st.button("Revoir le dernier post"):
            st.session_state[cle_pos] = n - 1
            st.rerun()
        st.stop()

    post = posts[idx]
    pid = post["post_id"]
    prefix = f"{lot_path.stem}:{path.stem}:{pid}:"
    init_widgets(prefix, annots.get(pid), entites)

    gauche, droite = st.columns([3, 2], gap="large")
    with gauche:
        st.caption(f"Post {idx + 1} / {n}"
                   + ("  · déjà annoté : enregistrer ajoute une ligne qui remplace la précédente"
                      if pid in annots else ""))
        with st.container(border=True):
            st.html(texte_html(post["texte"]))
        ctx = contexte(post)
        if ctx:
            with st.container(border=True):
                st.caption(ctx[0])
                st.html(texte_html(ctx[1]))
    with droite:
        choix = formulaire(prefix, schema, entites)
        c1, c2 = st.columns(2)
        if c1.button("Précédent", disabled=idx == 0, use_container_width=True):
            st.session_state[cle_pos] = idx - 1
            st.rerun()
        if c2.button("Enregistrer et suivant", type="primary", use_container_width=True):
            try:
                save_annotation(path, enregistrement(post, nom, choix), schema, entites)
            except ValueError as e:
                st.error(f"Non enregistré : {e}")
            else:
                st.session_state[cle_pos] = idx + 1
                st.rerun()


main()
