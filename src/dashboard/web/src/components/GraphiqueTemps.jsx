// Ton par tranche de temps. Colonnes empilées pour une série courte ; surface empilée au-delà,
// où les colonnes deviennent des traits de moins d'un pixel. Même donnée, même ordre des tons.
import { useRef } from "react";
import { fmtNombre, libelleAxe } from "../lib/format.js";
import { useLargeur } from "../hooks/useLargeur.js";

const COLONNES_MAX = 60; // au-delà, une surface empilée remplace les colonnes (même donnée)
const ETIQUETTE_PX = 110; // place minimale par libellé d'axe
const TONS_VUS = ["positif", "neutre", "negatif"];
const TONS_CLASSES = [
  ["positif", "fond-ton-positif"],
  ["neutre", "fond-ton-neutre"],
  ["negatif", "fond-ton-negatif"],
];
// Graduations « rondes » par pas : une graduation tous les `s` tranches.
const GRADUATIONS = {
  60: [1, 2, 3, 4, 6, 8, 12, 24],
  360: [1, 2, 4, 8, 16],
  1440: [1, 2, 3, 5, 7, 10, 14, 15, 30, 60, 90],
  10080: [1, 2, 4, 8, 13, 26, 52],
};

// Plus petit pas rond qui laisse la place à chaque libellé (sinon, le pas exact).
function pasGraduation(n, pas, largeur) {
  const max = Math.max(2, Math.floor(largeur / ETIQUETTE_PX));
  const minimum = Math.ceil(n / max);
  return (GRADUATIONS[pas] ?? []).find((s) => s >= minimum) ?? minimum;
}

export function GraphiqueTemps({ lignes, tranches, pas, maxVolume }) {
  const ref = useRef(null);
  const largeur = useLargeur(ref);
  const n = lignes.length;
  const enColonnes = n <= COLONNES_MAX;
  const s = pasGraduation(n, pas, largeur);
  const graduations = [];
  for (let i = 0; i < n; i += s) graduations.push(i);
  const position = (i) => (enColonnes ? ((i + 0.5) / n) * 100 : n > 1 ? (i / (n - 1)) * 100 : 50);

  // Surface : cumul des tons par tranche, du bas (positif) vers le haut (négatif).
  const W = 1000;
  const H = 120;
  const cumuls = lignes.map((l) => {
    let total = 0;
    return TONS_VUS.map((k) => (total += l[k] ?? 0));
  });
  const x = (i) => (n > 1 ? (i / (n - 1)) * W : W / 2);
  const y = (v) => H - (v / maxVolume) * H;
  const chemin = (j) => {
    const haut = cumuls.map((c, i) => `${x(i).toFixed(1)},${y(c[j]).toFixed(1)}`);
    const bas = cumuls.map((c, i) => `${x(i).toFixed(1)},${y(j ? c[j - 1] : 0).toFixed(1)}`).reverse();
    return `M${haut.join(" L")} L${bas.join(" L")} Z`;
  };

  return (
    <div ref={ref} role="img" aria-label="Ton par tranche de temps : voir le tableau ci-dessous">
      {enColonnes ? (
        <div className={`colonnes ${n > 40 ? "dense" : ""}`}>
          {lignes.map((l, i) => (
            <div key={tranches[i]} className="colonne">
              <div className="colonne-pile" style={{ height: `${(l.total / maxVolume) * 100}%` }}>
                {TONS_CLASSES.map(([k, cls]) => (
                  <span key={k} className={cls} style={{ height: `${l.total ? ((l[k] ?? 0) / l.total) * 100 : 0}%` }} />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <svg className="aire-temps" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true" focusable="false">
          {TONS_VUS.map((k, j) => (
            <path key={k} className={`aire-${k}`} d={chemin(j)} />
          ))}
          <line className="aire-base" x1="0" x2={W} y1={H} y2={H} />
        </svg>
      )}
      <div className="axe-temps" aria-hidden="true">
        {graduations.map((i) => {
          const p = position(i);
          const bord = p < 12 ? " bord-g" : p > 88 ? " bord-d" : "";
          return (
            <span key={i} className={`etiq${bord}`} style={{ left: `${p}%` }}>
              {libelleAxe(tranches[i], pas, i > 0 ? tranches[i - 1] : null)}
            </span>
          );
        })}
      </div>
      <p className="note">Hauteur : posts par tranche, échelle de 0 à {fmtNombre(maxVolume)}.</p>
    </div>
  );
}
