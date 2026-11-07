// Dates au format AAAA-MM-JJ, jours de Paris. Une date ne passe dans l'interface qu'après validation.

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const jourFmt = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit" });

export function dateValide(s) {
  if (typeof s !== "string" || !DATE_RE.test(s)) return false;
  const [y, m, d] = s.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
}

// Jour de Paris d'un instant : « 2026-10-19 ».
export function jourParis(date) {
  const p = Object.fromEntries(jourFmt.formatToParts(date).map((x) => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}`;
}

// Décale une date AAAA-MM-JJ de `n` jours (calendrier, sans heure).
export function decalerJour(jour, n) {
  const [y, m, d] = jour.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + n));
  return t.toISOString().slice(0, 10);
}

const HEURE_RE = /^([01]\d|2[0-3]):[0-5]\d$/;
export const heureValide = (s) => typeof s === "string" && HEURE_RE.test(s);

const murale = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

// Heure murale de Paris d'un instant : « 18:00 ».
export function heureParis(date) {
  const p = Object.fromEntries(murale.formatToParts(date).map((x) => [x.type, x.value]));
  return `${p.hour}:${p.minute}`;
}

// Instant (Date) d'une date et d'une heure murales de Paris. Deux passes : le décalage de Paris
// dépend de l'instant (heure d'été), la seconde passe corrige le jour du changement d'heure.
export function instantParis(jour, heure = "00:00") {
  const [y, m, d] = jour.split("-").map(Number);
  const [h, mi] = heure.split(":").map(Number);
  const voulu = Date.UTC(y, m - 1, d, h, mi);
  let t = voulu;
  for (let i = 0; i < 2; i += 1) {
    const p = Object.fromEntries(murale.formatToParts(new Date(t)).map((x) => [x.type, Number(x.value)]));
    const lu = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute);
    t += voulu - lu;
  }
  return new Date(t);
}
