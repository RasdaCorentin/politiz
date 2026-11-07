// Bulles de mots : un adjectif par bulle, le mot et son nombre de posts écrits dedans.
// Surface proportionnelle au nombre de posts (rayon en racine carrée), avec un rayon minimal qui laisse
// le mot lisible : une petite bulle peut donc paraître un peu grande, le nombre écrit fait foi.
// Disposition déterministe : la plus grande bulle au centre, chaque suivante à la place libre la plus
// proche du centre, en privilégiant la largeur (les panneaux sont plus larges que hauts).
import { fmtNombre } from "../lib/format.js";

const RMAX = 54; // rayon de la plus grande bulle, en unités du viewBox
const POLICE_MIN = 11; // taille minimale du mot
const POLICE_MAX = 16;
const LARGEUR_CAR = 0.56; // largeur moyenne d'un caractère, en fraction de la taille de police
const REMPLISSAGE = 0.84; // part du diamètre que le mot peut occuper
const GAP = 4;
const PAD = 4;
const ETIREMENT_Y = 1.9; // une distance verticale « coûte » plus qu'une horizontale : disposition en largeur
const PAS_ANGLE = Math.PI / 18;
export const DECALAGE_ENTREE_MS = 70;

// Rayon d'une bulle : surface proportionnelle, puis au moins la place du mot à la taille minimale.
function rayon(mot, posts, max) {
  const surface = RMAX * Math.sqrt(Math.max(posts, 0) / max);
  const pourLeMot = (mot.length * LARGEUR_CAR * POLICE_MIN) / (2 * REMPLISSAGE);
  return Math.max(surface, pourLeMot, POLICE_MIN * 1.6);
}

// Taille du mot : la plus grande qui tient dans la bulle, bornée.
function police(mot, r) {
  const tient = (2 * r * REMPLISSAGE) / (Math.max(mot.length, 1) * LARGEUR_CAR);
  return Math.max(POLICE_MIN, Math.min(POLICE_MAX, tient, r * 0.5));
}

export function disposerMots(items) {
  if (!items.length) return { bulles: [], viewBox: "0 0 10 10" };
  const max = Math.max(...items.map((i) => i.posts), 1);
  const bulles = [];
  for (const it of items) {
    const r = rayon(it.mot, it.posts, max);
    if (!bulles.length) {
      bulles.push({ ...it, x: 0, y: 0, r });
      continue;
    }
    let meilleure = null;
    for (const b of bulles) {
      for (let a = 0; a < 2 * Math.PI; a += PAS_ANGLE) {
        const x = b.x + (b.r + r + GAP) * Math.cos(a);
        const y = b.y + (b.r + r + GAP) * Math.sin(a);
        const libre = bulles.every((o) => Math.hypot(o.x - x, o.y - y) >= o.r + r + GAP - 0.01);
        if (!libre) continue;
        const cout = x * x + (ETIREMENT_Y * y) ** 2;
        if (!meilleure || cout < meilleure.cout) meilleure = { x, y, cout };
      }
    }
    bulles.push({ ...it, x: meilleure.x, y: meilleure.y, r });
  }
  const x0 = Math.min(...bulles.map((b) => b.x - b.r)) - PAD;
  const y0 = Math.min(...bulles.map((b) => b.y - b.r)) - PAD;
  const x1 = Math.max(...bulles.map((b) => b.x + b.r)) + PAD;
  const y1 = Math.max(...bulles.map((b) => b.y + b.r)) + PAD;
  return { bulles, viewBox: `${x0} ${y0} ${x1 - x0} ${y1 - y0}` };
}

/**
 * @param {object} p
 * @param {{cle: string, mot: string, posts: number}[]} p.items  du plus fréquent au moins fréquent
 * @param {"pour"|"contre"} p.stance  teinte des bulles (jetons de ton)
 * @param {string} p.titre  description pour les lecteurs d'écran
 */
export function BullesMots({ items, stance, titre }) {
  const { bulles, viewBox } = disposerMots(items);
  const resume = items.map((i) => `${i.mot} ${fmtNombre(i.posts)}`).join(", ");
  return (
    <svg className={`bulles-mots stance-${stance}`} viewBox={viewBox} role="img" aria-label={`${titre} : ${resume}.`}>
      {bulles.map((b, i) => {
        const fs = police(b.mot, b.r);
        return (
          <g key={b.cle} className="bulle-mot" style={{ animationDelay: `${i * DECALAGE_ENTREE_MS}ms` }}>
            <circle cx={b.x} cy={b.y} r={b.r} />
            <text className="mot" x={b.x} y={b.y - 1} textAnchor="middle" style={{ fontSize: `${fs}px` }}>
              {b.mot}
            </text>
            <text className="nombre" x={b.x} y={b.y + 12} textAnchor="middle">
              {fmtNombre(b.posts)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
