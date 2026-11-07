// Bulles de thèmes d'une entité. La surface est proportionnelle au nombre de posts (rayon en racine
// carrée). Disposition fixe et déterministe : la plus grande bulle au centre, les autres sur un
// anneau, dans l'ordre des rangs. Chaque libellé se place à côté de sa bulle, sur la première
// position libre ; sans place, il reste dans le tableau (aucun chevauchement de texte).
import { fmtNombre } from "../lib/format.js";

const RMAX = 40; // rayon de la plus grande bulle, en unités du viewBox
const GAP = 8; // écart minimal entre deux bulles
const DECALAGE = 6; // écart entre une bulle et son libellé
const MARGE = 6; // marge intérieure du libellé
const H_ETIQUETTE = 34; // deux lignes : libellé (12 px) et valeur (13 px)
const CAR_LIBELLE = 7.2; // largeur estimée d'un caractère du libellé (majorée)
const CAR_VALEUR = 8.4; // largeur estimée d'un caractère de la valeur (majorée)
const PAD = 6;
const DECALAGE_ENTREE_MS = 70; // entrée des bulles, de la plus grande à la plus petite

// Ordre des positions pour une étiquette, selon la direction de la bulle sur l'anneau.
function ordreAutour(theta) {
  const dx = Math.cos(theta);
  const dy = Math.sin(theta);
  const pref = [];
  if (dx > 0.35) pref.push("droite");
  else if (dx < -0.35) pref.push("gauche");
  if (dy < -0.35) pref.push("dessus");
  else if (dy > 0.35) pref.push("dessous");
  return [...new Set([...pref, "droite", "gauche", "dessous", "dessus"])];
}

// Coin haut-gauche et ancre d'une étiquette côté `cote`, ou null si la place ne convient pas.
function position(cote, b, w, h) {
  const { x, y, r } = b;
  switch (cote) {
    case "dedans":
      return (w / 2) ** 2 + (h / 2) ** 2 <= (r - 2) ** 2 ? { x0: x - w / 2, y0: y - h / 2, ancre: "middle" } : null;
    case "droite":
      return { x0: x + r + DECALAGE, y0: y - h / 2, ancre: "start" };
    case "gauche":
      return { x0: x - r - DECALAGE - w, y0: y - h / 2, ancre: "end" };
    case "dessous":
      return { x0: x - w / 2, y0: y + r + DECALAGE, ancre: "middle" };
    default:
      return { x0: x - w / 2, y0: y - r - DECALAGE - h, ancre: "middle" };
  }
}

const chevauche = (a, c) => a.x0 < c.x1 && c.x0 < a.x1 && a.y0 < c.y1 && c.y0 < a.y1;

// Calcule les positions. `items` : [{cle, libelle, posts}], du plus grand au plus petit.
export function disposerBulles(items) {
  if (!items.length) return { placees: [], etiquettes: [], centre: null, viewBox: "0 0 10 10" };
  const pmax = Math.max(...items.map((i) => i.posts), 1);
  const rayons = items.map((i) => RMAX * Math.sqrt(Math.max(i.posts, 0) / pmax));

  const placees = [{ x: 0, y: 0, r: rayons[0], theta: 0 }];
  const k = items.length - 1;
  if (k > 0) {
    // Éloignement de l'anneau : assez pour la plus grande bulle du centre, et des voisins sans contact.
    let D = rayons[0] + Math.max(...rayons.slice(1)) + GAP;
    if (k > 1) {
      for (let m = 0; m < k; m++) {
        const a = rayons[m + 1];
        const c = rayons[((m + 1) % k) + 1];
        D = Math.max(D, (a + c + GAP) / (2 * Math.sin(Math.PI / k)));
      }
    }
    for (let m = 0; m < k; m++) {
      const theta = -Math.PI / 2 + (2 * Math.PI * m) / k;
      placees.push({ x: D * Math.cos(theta), y: D * Math.sin(theta), r: rayons[m + 1], theta });
    }
  }

  // Cadres occupés par les bulles (carrés englobants, plus sûrs que les cercles).
  const bulles = placees.map((b) => ({ x0: b.x - b.r, y0: b.y - b.r, x1: b.x + b.r, y1: b.y + b.r }));
  const etiquettes = [];
  items.forEach((it, i) => {
    const b = placees[i];
    const texte = fmtNombre(it.posts);
    const w = Math.max(it.libelle.length * CAR_LIBELLE, texte.length * CAR_VALEUR) + 2 * MARGE;
    const ordre = i === 0 ? ["dedans", "droite", "gauche", "dessous", "dessus"] : ordreAutour(b.theta);
    for (const cote of ordre) {
      const p = position(cote, b, w, H_ETIQUETTE);
      if (!p) continue;
      const boite = { x0: p.x0, y0: p.y0, x1: p.x0 + w, y1: p.y0 + H_ETIQUETTE };
      const libre =
        bulles.every((o, j) => j === i || !chevauche(o, boite)) && etiquettes.every((e) => !chevauche(e.boite, boite));
      if (libre) {
        etiquettes.push({ i, ancre: p.ancre, boite, texte, libelle: it.libelle });
        break;
      }
    }
  });

  // Bulle centrale sans place pour son libellé (entourée par l'anneau) : sa valeur s'écrit dedans,
  // son libellé passe dans la légende sous le graphique (`centre`).
  let centre = null;
  if (!etiquettes.some((e) => e.i === 0)) {
    const texte = fmtNombre(items[0].posts);
    const b = placees[0];
    if (((texte.length * CAR_VALEUR) / 2) ** 2 + 8 ** 2 <= (b.r - 2) ** 2) centre = { x: b.x, y: b.y, texte };
  }

  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const o of [...bulles, ...etiquettes.map((e) => e.boite)]) {
    x0 = Math.min(x0, o.x0);
    y0 = Math.min(y0, o.y0);
    x1 = Math.max(x1, o.x1);
    y1 = Math.max(y1, o.y1);
  }
  const viewBox = `${x0 - PAD} ${y0 - PAD} ${x1 - x0 + 2 * PAD} ${y1 - y0 + 2 * PAD}`;
  return { placees, etiquettes, centre, viewBox };
}

const ancreX = (e) => (e.ancre === "start" ? e.boite.x0 : e.ancre === "end" ? e.boite.x1 : (e.boite.x0 + e.boite.x1) / 2);

export function Bulles({ items, nom, camp }) {
  const { placees, etiquettes, centre, viewBox } = disposerBulles(items);
  const centreSansLibelle = items.length > 0 && !etiquettes.some((e) => e.i === 0);
  const resume = items.map((it) => `${it.libelle} ${fmtNombre(it.posts)} posts`).join(" ; ");
  return (
    <figure className="figure-bulles">
    <svg className={`bulles camp-${camp ?? "sans-camp"}`} viewBox={viewBox} role="img" aria-label={`Thèmes de ${nom} : ${resume}.`}>
      {placees.map((b, i) => (
        <circle key={items[i].cle} className="bulle" cx={b.x} cy={b.y} r={b.r} style={{ animationDelay: `${i * DECALAGE_ENTREE_MS}ms` }}>
          <title>{`${items[i].libelle} : ${fmtNombre(items[i].posts)} posts`}</title>
        </circle>
      ))}
      {etiquettes.map((e) => (
        <g key={items[e.i].cle} className="etiquette-bulle" style={{ animationDelay: `${300 + e.i * DECALAGE_ENTREE_MS}ms` }}>
          <text className="libelle-bulle" x={ancreX(e)} y={e.boite.y0 + 13} textAnchor={e.ancre}>
            {e.libelle}
          </text>
          <text className="valeur-bulle" x={ancreX(e)} y={e.boite.y0 + 30} textAnchor={e.ancre}>
            {e.texte}
          </text>
        </g>
      ))}
      {centre && (
        <text className="valeur-bulle etiquette-bulle" x={centre.x} y={centre.y + 5} textAnchor="middle" style={{ animationDelay: "300ms" }}>
          {centre.texte}
        </text>
      )}
    </svg>
    {centreSansLibelle && (
      <figcaption className="note">
        Au centre : {items[0].libelle}, {fmtNombre(items[0].posts)} posts.
      </figcaption>
    )}
    </figure>
  );
}
