// État de la page, lu dans l'URL et écrit dans l'URL (DESIGN.md §1.10).
// Paramètres : vue, periode ou debut+fin, seuil, cible. Page événement : ev_id (fait du catalogue),
// ev_libelle, ev_date (AAAA-MM-JJ, jour de Paris), ev_heure (HH:MM, heure de Paris, facultative).
import { CIBLE_DEFAUT, PAGE_DEFAUT, PAGES, PERIODE_DEFAUT, PERIODES, SEUIL_MAX, SEUIL_MIN } from "../constantes.js";
import { dateValide, heureValide } from "./dates.js";

export const LIBELLE_EVENEMENT_MAX = 160;
const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

// Une plage vaut seulement si ses deux dates sont valides et dans l'ordre.
function plage(debut, fin) {
  return dateValide(debut) && dateValide(fin) && debut <= fin ? { debut, fin } : { debut: null, fin: null };
}

export function etatParDefaut() {
  return {
    vue: PAGE_DEFAUT,
    periode: PERIODE_DEFAUT,
    debut: null,
    fin: null,
    seuil: null,
    cible: CIBLE_DEFAUT,
    evenement: { id: null, libelle: "", date: null, heure: null },
  };
}

// Une plage valide l'emporte sur `periode`. Sans paramètre : 7 jours, page « contraste ».
export function lireUrl() {
  try {
    const p = new URLSearchParams(window.location.search);
    const s = Number(p.get("seuil"));
    const seuil = p.has("seuil") && Number.isInteger(s) && s >= SEUIL_MIN && s <= SEUIL_MAX ? s : null;
    const vue = PAGES.some((x) => x.valeur === p.get("vue")) ? p.get("vue") : PAGE_DEFAUT;
    const cible = p.get("cible") === "partis" ? "partis" : CIBLE_DEFAUT;
    const personnalisee = plage(p.get("debut"), p.get("fin"));
    const periode = personnalisee.debut
      ? null
      : PERIODES.some((x) => x.valeur === p.get("periode"))
        ? p.get("periode")
        : PERIODE_DEFAUT;
    const evenement = {
      id: ID_RE.test(p.get("ev_id") ?? "") ? p.get("ev_id") : null,
      libelle: (p.get("ev_libelle") ?? "").slice(0, LIBELLE_EVENEMENT_MAX),
      date: dateValide(p.get("ev_date")) ? p.get("ev_date") : null,
      heure: heureValide(p.get("ev_heure")) ? p.get("ev_heure") : null,
    };
    return { vue, periode, debut: personnalisee.debut, fin: personnalisee.fin, seuil, cible, evenement };
  } catch {
    return etatParDefaut();
  }
}

// Paramètres de l'URL pour cet état. Les paramètres de la page événement ne vont que sur cette page.
export function construireQuery(e) {
  const p = new URLSearchParams();
  p.set("vue", e.vue);
  if (e.periode) {
    p.set("periode", e.periode);
  } else {
    p.set("debut", e.debut);
    p.set("fin", e.fin);
  }
  if (e.seuil) p.set("seuil", String(e.seuil));
  if (e.cible !== CIBLE_DEFAUT) p.set("cible", e.cible);
  if (e.vue === "evenement") {
    if (e.evenement.id) p.set("ev_id", e.evenement.id);
    if (e.evenement.libelle) p.set("ev_libelle", e.evenement.libelle);
    if (e.evenement.date) p.set("ev_date", e.evenement.date);
    if (e.evenement.heure) p.set("ev_heure", e.evenement.heure);
  }
  return p.toString();
}
