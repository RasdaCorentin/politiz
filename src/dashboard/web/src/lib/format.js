// Formats et libellés en français, heure de Paris. Ce fichier n'applique aucune formule : il met
// en forme les nombres, heures et textes reçus de l'API.

export const MOINS = "−"; // U+2212 : vrai signe moins
export const NBSP = " "; // espace insécable

const nombre = new Intl.NumberFormat("fr-FR");
const decimal1 = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const signe2 = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: "exceptZero" });
const pourcentFmt = new Intl.NumberFormat("fr-FR", { style: "percent", maximumFractionDigits: 0 });
const heureFmt = new Intl.DateTimeFormat("fr-FR", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit" });
const dateHeureFmt = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const dateCourte = new Intl.DateTimeFormat("fr-FR", { timeZone: "Europe/Paris", day: "numeric", month: "short", year: "numeric" });
const partsTranche = new Intl.DateTimeFormat("fr-FR", { timeZone: "Europe/Paris", day: "numeric", month: "short", hour: "numeric", hourCycle: "h23" });
const jourCourt = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit" });

export const fmtNombre = (v) => (v == null ? "n/d" : nombre.format(v));
export const fmtPourcent = (v) => (v == null ? "n/d" : pourcentFmt.format(v).replace(/\s/g, NBSP));
export const fmtDecimal = (v) => (v == null ? "n/d" : decimal1.format(v));
// Indice signé : « +0,28 » ou « −0,31 ».
export const fmtSigne = (v) => (v == null ? "n/d" : signe2.format(v).replace("-", MOINS));
export const fmtHeure = (iso) => (iso ? heureFmt.format(new Date(iso)) : "n/d");
export const fmtDateHeure = (iso) => (iso ? dateHeureFmt.format(new Date(iso)).replace(",", "") : "n/d");

// Le pas suit la période : 60 min (heures), 360 (6 h), 1440 (jour), 10080 (semaine).
export function libellePas(pas) {
  if (pas <= 60) return "1 h";
  if (pas < 1440) return `${Math.round(pas / 60)} h`;
  if (pas < 10080) return "jour";
  return "semaine";
}

function piecesTranche(iso) {
  const p = Object.fromEntries(partsTranche.formatToParts(new Date(iso)).map((x) => [x.type, x.value]));
  return { jour: p.day, mois: p.month, heure: p.hour };
}

// Libellé complet d'une tranche, pour le tableau : « 19 oct. 14 h », « 19 oct. », « sem. du 12 oct. ».
export function libelleTranche(iso, pas) {
  const { jour, mois, heure } = piecesTranche(iso);
  if (pas < 1440) return `${jour} ${mois} ${heure}${NBSP}h`;
  if (pas < 10080) return `${jour} ${mois}`;
  return `sem. du ${jour} ${mois}`;
}

// Libellé d'axe : sur les pas horaires, la date n'apparaît qu'au changement de jour.
export function libelleAxe(iso, pas, precedenteIso) {
  const meme = precedenteIso && jourCourt.format(new Date(iso)) === jourCourt.format(new Date(precedenteIso));
  if (pas < 1440 && meme) return `${piecesTranche(iso).heure}${NBSP}h`;
  return libelleTranche(iso, pas);
}

// Durée d'une fenêtre : « 24 h » sous deux jours, « 7 jours » au-delà.
export function dureeFenetre(p) {
  const heures = (Date.parse(p.fin) - Date.parse(p.debut)) / 3_600_000;
  if (heures < 48) return { heures: Math.round(heures), texte: `${Math.round(heures)}${NBSP}h` };
  const jours = Math.round(heures / 24);
  return { heures, jours, texte: `${jours}${NBSP}${jours > 1 ? "jours" : "jour"}` };
}

// « du 12 oct. 2026 au 18 oct. 2026 · 7 jours ». Le dernier jour est inclus (fin exclue).
export function libelleFenetre(p) {
  const duree = dureeFenetre(p);
  if (duree.heures < 48) return `du ${fmtDateHeure(p.debut)} au ${fmtDateHeure(p.fin)} · ${duree.texte}`;
  const dernier = new Date(Date.parse(p.fin) - 1);
  return `du ${dateCourte.format(new Date(p.debut))} au ${dateCourte.format(dernier)} · ${duree.texte}`;
}

// Repère de la période précédente : « 7 jours précédents », « 24 h précédentes ».
export function libellePrecedente(p) {
  const duree = dureeFenetre(p);
  if (duree.heures < 48) return `${duree.heures}${NBSP}h précédentes`;
  return `${duree.jours}${NBSP}${duree.jours > 1 ? "jours précédents" : "jour précédent"}`;
}

// Durée lisible : « 42 s », « 7 min », « 2 h 05 », « 3 j 4 h ».
export function duree(secondes) {
  if (secondes == null || !Number.isFinite(secondes) || secondes < 0) return "n/d";
  if (secondes < 60) return `${Math.round(secondes)}${NBSP}s`;
  const min = Math.floor(secondes / 60);
  if (min < 60) return `${min}${NBSP}min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}${NBSP}h ${String(min % 60).padStart(2, "0")}`;
  return `${Math.floor(h / 24)}${NBSP}j ${h % 24}${NBSP}h`;
}

// L'âge se mesure entre deux heures serveur (lecture et dernière donnée) : pas d'horloge locale.
export function ageSecondes(etat, lectureIso) {
  if (!etat.derniere_maj || !lectureIso) return null;
  return (Date.parse(lectureIso) - Date.parse(etat.derniere_maj)) / 1000;
}

export function libelleFraicheur(etat, age) {
  switch (etat.fraicheur) {
    case "ok":
      return `À jour · dernière donnée il y a ${duree(age)}`;
    case "warn":
      return `En retard · aucun nouveau post depuis ${duree(age)}`;
    case "critical":
      return `Flux arrêté ou nuit calme · aucun nouveau post depuis ${duree(age)}`;
    default:
      return "Aucune donnée reçue";
  }
}

// Initiales : « Alice Fictive » donne « AF ». Un identifiant « alice-fictive » donne aussi « AF ».
export function initiales(nom) {
  const mots = String(nom ?? "").trim().split(/[\s_-]+/).filter(Boolean);
  const lettres = mots.slice(0, 2).map((m) => Array.from(m)[0]).join("");
  return lettres.toUpperCase() || "?";
}
