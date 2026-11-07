"""Modèle de la vue : assemble les calculs purs à partir des lignes agrégées par tranche. Aucune entrée-sortie."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import calculs as k
from camps import Lexique, camps_des_candidats, trouver
from donnees import Brut


@dataclass(frozen=True)
class Vue:
    bornes: k.Bornes
    premiere: datetime | None  # première fenêtre en base
    seuil: int
    maintenant: datetime
    base_vide: bool  # aucune fenêtre en base : le flux n'a jamais écrit
    periode_vide: bool  # aucune ligne sur la période choisie
    pipeline: k.Pipeline
    fraicheur: k.Fraicheur
    derniere_maj: datetime | None
    volume: list[int]
    ton: k.Ton
    serie_ton: list[k.TrancheTon]
    emotions: dict[str, int]
    emotions_sans: int
    themes: list[tuple[str, int]]
    comptes: dict[str, k.Comptes]
    candidats: list[k.LigneClassement]
    partis: list[k.LigneClassement]
    position: k.Position
    position_precedente: k.Position | None  # None pour `tout`
    series: dict[str, list[k.PointIndice]] = field(default_factory=dict)
    non_classes_evalues: int = 0  # évaluations de candidats sans camp, hors de la barre
    hors_lexique: int = 0  # entités lues mais absentes du lexique (ignorées)
    lexique: Lexique = field(default_factory=Lexique)
    croisements: k.Croisements = field(default_factory=k.Croisements)
    serie_camps: list[dict[str, dict[str, int]]] = field(default_factory=list)  # par tranche (tableau v4)
    adjectifs: k.Adjectifs | None = None  # None : table `adjectifs_fenetre` absente


def construire(brut: Brut, lexique: Lexique, seuil: int, ok_min: int, alerte_min: int, maintenant: datetime) -> Vue:
    b = brut.bornes
    comptes = k.agreger_cibles(brut.cibles)

    ids_candidats = [e for e in comptes if trouver(lexique, e).type == "candidat"]
    ids_partis = [e for e in comptes if trouver(lexique, e).type == "parti"]
    hors_lexique = sum(1 for e in comptes if e not in lexique.entites)

    camp_de = camps_des_candidats(lexique)
    renseignes = set(camp_de.values())
    position = k.position_barre(k.resultats_par_camp(comptes, camp_de), seuil, renseignes)
    position_prec = None
    if b.precedente is not None:
        prec = k.agreger_cibles(brut.cibles_precedentes)
        position_prec = k.position_barre(k.resultats_par_camp(prec, camp_de), seuil, renseignes)

    candidats = k.classer(comptes, seuil, ids_candidats)
    partis = k.classer(comptes, seuil, ids_partis)
    series = {
        l.entite: k.serie_indice_cumulee(brut.cibles, l.entite, b.tranches, b.fin, seuil)
        for l in candidats
        if l.rang is not None
    }
    non_classes = sum(comptes[e].evalues for e in ids_candidats if e not in camp_de)

    emotions, sans = k.repartition_emotions(brut.posts)
    pipeline = k.resume_pipeline(brut.pipeline)
    # Croisements : seulement les entités de cette réponse (candidats puis partis, dans leur ordre).
    ordre = [l.entite for l in candidats + partis]
    croisements = k.Croisements(
        scoreur=brut.scoreur,
        themes=k.totaux_par_entite(brut.croisements_themes, ordre),
        emotions=k.totaux_par_entite(brut.croisements_emotions, ordre, exclues=frozenset({k.EMOTION_NON_DETECTEE})),
    )
    adjectifs = None
    if brut.adjectifs is not None:
        debut_adj, fin_adj = k.couverture_adjectifs(brut.couverture_adjectifs)
        adjectifs = k.Adjectifs(
            scoreur=brut.scoreur_adjectifs,
            lignes=k.adjectifs_par_entite(brut.adjectifs, ordre),
            debut=debut_adj,
            fin=fin_adj,
            posts_hors=brut.posts_hors_adjectifs if debut_adj is not None else 0,
        )
    return Vue(
        bornes=b,
        premiere=brut.etat.premiere,
        seuil=seuil,
        maintenant=maintenant,
        base_vide=brut.etat.premiere is None and brut.etat.derniere_maj is None,
        periode_vide=not (brut.cibles or brut.posts or brut.themes or brut.pipeline),
        pipeline=pipeline,
        derniere_maj=brut.etat.derniere_maj,
        fraicheur=k.etat_fraicheur(brut.etat.derniere_maj, maintenant, ok_min, alerte_min),
        volume=k.serie_volume(brut.pipeline, b.tranches, b.fin),
        ton=k.repartition_ton(brut.posts),
        serie_ton=k.serie_ton(brut.posts, b.tranches, b.fin),
        emotions=emotions,
        emotions_sans=sans,
        themes=k.classer_themes(brut.themes),
        comptes=comptes,
        candidats=candidats,
        partis=partis,
        position=position,
        position_precedente=position_prec,
        series=series,
        non_classes_evalues=non_classes,
        hors_lexique=hors_lexique,
        lexique=lexique,
        croisements=croisements,
        serie_camps=k.serie_camps(brut.cibles, camp_de, b.tranches, b.fin),
        adjectifs=adjectifs,
    )
