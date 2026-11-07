// Courbes par candidat : petits multiples, échelle commune de −1 à +1 (DESIGN.md §6).
import { fmtSigne, MOINS } from "../lib/format.js";

// Petit multiple : indice cumulé d'un candidat au fil de la période.
export function Courbe({ nom, camp, points }) {
  const W = 300;
  const H = 110;
  const pad = { l: 30, r: 6, t: 8, b: 8 };
  const n = points.length;
  const x = (i) => pad.l + (n > 1 ? (i / (n - 1)) * (W - pad.l - pad.r) : 0);
  const y = (v) => pad.t + ((1 - v) / 2) * (H - pad.t - pad.b);
  // Un trait par suite de points valides : un indice null (sous le seuil) coupe la courbe.
  const traits = [];
  let courant = "";
  points.forEach((p, i) => {
    if (p.indice == null) {
      if (courant) traits.push(courant);
      courant = "";
    } else {
      courant += `${courant ? "L" : "M"}${x(i).toFixed(1)},${y(p.indice).toFixed(1)} `;
    }
  });
  if (courant) traits.push(courant);
  const valides = points.filter((p) => p.indice != null);
  const dernier = valides.at(-1);
  const classe = camp ? `camp-${camp}` : "sans-camp";
  const resume = valides.length
    ? `Indice net de ${nom} : ${fmtSigne(valides[0].indice)} au premier point valide, ${fmtSigne(dernier.indice)} à la fin de la période.`
    : `Indice net de ${nom} : aucun point au-dessus du seuil.`;

  return (
    <figure className="courbe">
      <figcaption className="courbe-titre">
        <span className="nom">{nom}</span>
        <span className="tnum">{dernier ? `dernier ${fmtSigne(dernier.indice)}` : "n/d"}</span>
      </figcaption>
      {valides.length >= 7 ? (
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={resume}>
          <line className="zero" x1={pad.l} x2={W - pad.r} y1={y(0)} y2={y(0)} />
          <line className="grille-ligne" x1={pad.l} x2={W - pad.r} y1={y(1)} y2={y(1)} />
          <line className="grille-ligne" x1={pad.l} x2={W - pad.r} y1={y(-1)} y2={y(-1)} />
          <text x={pad.l - 4} y={y(1) + 3} textAnchor="end">+1</text>
          <text x={pad.l - 4} y={y(0) + 3} textAnchor="end">0</text>
          <text x={pad.l - 4} y={y(-1) + 3} textAnchor="end">{MOINS}1</text>
          {traits.map((d, i) => (
            <path key={i} className={`trait ${classe}`} d={d} />
          ))}
        </svg>
      ) : (
        <p className="note">Pas assez de points au-dessus du seuil pour tracer une courbe.</p>
      )}
    </figure>
  );
}

export function Courbes({ data, nomPar }) {
  const series = data.series ?? {};
  const candidatsAvecCourbe = data.candidats.filter((e) => (series[e.entite] ?? []).length > 0);
  if (!candidatsAvecCourbe.length) return null;
  return (
    <div className="bloc bloc-courbes">
      <h4>Indice net par candidat au fil de la période</h4>
      <div className="courbes">
        {candidatsAvecCourbe.map((e) => (
          <Courbe key={e.entite} nom={nomPar(e)} camp={e.camp} points={series[e.entite]} />
        ))}
      </div>
    </div>
  );
}
