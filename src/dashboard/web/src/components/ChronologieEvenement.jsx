// Chronologie d'une semaine autour d'un fait : petits multiples alignés sur le même axe du temps.
// Ligne 1 : posts scorés par tranche. Lignes 2 à 4 : un camp par ligne, évaluations « pour » au-dessus
// de l'axe et « contre » en dessous, même échelle pour les trois camps (on compare leurs réactions).
// Le fait est un trait vertical (heure connue) ou une bande sur son jour (heure inconnue).
// Seuls calculs : positions et hauteurs d'affichage. Les nombres viennent de `volume` et `serie_camps`.
import { useRef } from "react";
import { useLargeur } from "../hooks/useLargeur.js";
import { decalerJour, instantParis } from "../lib/dates.js";
import { fmtNombre, MOINS } from "../lib/format.js";
import { CAMPS } from "../constantes.js";

const GOUTTIERE = 112; // libellés des lignes, à gauche
const HAUT = 30; // bandeau « Avant / Après » et libellé du fait
const H_VOLUME = 60;
const H_CAMP = 92; // moitié pour, moitié contre
const ECART = 16;
const AXE = 40; // libellés des jours
const jourCourt = new Intl.DateTimeFormat("fr-FR", { timeZone: "Europe/Paris", weekday: "short", day: "numeric", month: "short" });

/**
 * @param {object} p
 * @param {object} p.donnees  réponse `tableau` de la fenêtre (tranches, volume, serie_camps, periode)
 * @param {string} p.jour  jour J (AAAA-MM-JJ, Paris)
 * @param {string|null} p.heure  heure du fait (HH:MM, Paris) ou null
 */
export function ChronologieEvenement({ donnees, jour, heure }) {
  const ref = useRef(null);
  const L = Math.max(560, useLargeur(ref, 1100));
  const { tranches, volume, serie_camps: series, periode } = donnees;
  const t0 = Date.parse(periode.debut);
  const t1 = Date.parse(periode.fin);
  const traceW = L - GOUTTIERE - 8;
  const x = (t) => GOUTTIERE + ((t - t0) / (t1 - t0)) * traceW;
  const debuts = tranches.map((t) => Date.parse(t));
  const fins = [...debuts.slice(1), t1];
  const largeurBarre = (i) => {
    const w = x(fins[i]) - x(debuts[i]);
    return { x0: x(debuts[i]) + Math.max(1, w * 0.14), w: Math.max(1, w * 0.72) };
  };

  const maxVolume = Math.max(1, ...volume);
  const maxCamp = Math.max(1, ...series.flatMap((s) => Object.keys(CAMPS).flatMap((c) => [s[c].pour, s[c].contre])));
  const yVolume = HAUT;
  const yCamp = (k) => HAUT + H_VOLUME + ECART + k * (H_CAMP + ECART);
  const H = yCamp(3) + AXE;

  // Jour J : début et fin du jour de Paris ; le fait lui-même si son heure est connue.
  const debutJ = instantParis(jour).getTime();
  const finJ = instantParis(decalerJour(jour, 1)).getTime();
  const fait = heure ? instantParis(jour, heure).getTime() : null;

  // Minuits de Paris dans la fenêtre : graduations, avec le décalage en jours par rapport à J.
  const minuits = [];
  for (let k = -10; k <= 10; k += 1) {
    const j = decalerJour(jour, k);
    const t = instantParis(j).getTime();
    if (t >= t0 && t < t1) minuits.push({ t, j, k });
  }

  const resume = `Évaluations pour et contre par camp, par tranche de ${periode.pas_min / 60} h, du ${jourCourt.format(t0)} au ${jourCourt.format(t1 - 1)}. Le fait est marqué le ${jourCourt.format(debutJ)}${heure ? ` à ${heure}` : ""}. Valeurs dans le tableau qui suit.`;

  return (
    <div ref={ref} className="chrono-cadre">
      <svg className="chrono" width={L} height={H} viewBox={`0 0 ${L} ${H}`} role="img" aria-label={resume}>
        {/* Avant / après : deux fonds, séparés au début du jour J. */}
        <rect className="zone-avant" x={GOUTTIERE} y={HAUT - 6} width={Math.max(0, x(debutJ) - GOUTTIERE)} height={H - AXE - HAUT + 6} />
        <text className="zone-libelle" x={GOUTTIERE + 6} y={HAUT - 12}>Avant</text>
        <text className="zone-libelle" x={Math.min(x(finJ), L - 8) + 6} y={HAUT - 12}>Après</text>

        {minuits.map((m) => (
          <g key={m.j}>
            <line className="minuit" x1={x(m.t)} x2={x(m.t)} y1={HAUT - 6} y2={H - AXE + 4} />
            <text className="jour-j" x={x(m.t) + 4} y={H - AXE + 18}>
              {m.k === 0 ? "J" : `J${m.k > 0 ? "+" : MOINS}${Math.abs(m.k)}`}
            </text>
            <text className="jour-date" x={x(m.t) + 4} y={H - AXE + 32}>
              {jourCourt.format(m.t)}
            </text>
          </g>
        ))}

        {/* Ligne du volume */}
        <text className="ligne-libelle" x={0} y={yVolume + H_VOLUME / 2}>Posts scorés</text>
        <text className="ligne-echelle" x={0} y={yVolume + H_VOLUME / 2 + 15}>max {fmtNombre(maxVolume)}</text>
        <line className="axe" x1={GOUTTIERE} x2={L - 8} y1={yVolume + H_VOLUME} y2={yVolume + H_VOLUME} />
        {volume.map((v, i) => {
          const { x0, w } = largeurBarre(i);
          const h = (v / maxVolume) * (H_VOLUME - 4);
          return <rect key={tranches[i]} className="barre-chrono volume" x={x0} y={yVolume + H_VOLUME - h} width={w} height={h} />;
        })}

        {/* Une ligne par camp : pour au-dessus, contre en dessous */}
        {Object.entries(CAMPS).map(([camp, libelle], k) => {
          const y0 = yCamp(k);
          const milieu = y0 + H_CAMP / 2;
          const demi = H_CAMP / 2 - 2;
          return (
            <g key={camp} className={`camp-${camp}`}>
              <use href={`#i-${camp}`} x={0} y={milieu - 20} width={12} height={12} className="forme-camp" />
              <text className="ligne-libelle" x={18} y={milieu - 10}>{libelle}</text>
              <text className="ligne-echelle" x={0} y={milieu + 8}>pour ↑</text>
              <text className="ligne-echelle" x={0} y={milieu + 22}>contre ↓</text>
              <line className="axe" x1={GOUTTIERE} x2={L - 8} y1={milieu} y2={milieu} />
              {series.map((s, i) => {
                const { x0, w } = largeurBarre(i);
                const hp = (s[camp].pour / maxCamp) * demi;
                const hc = (s[camp].contre / maxCamp) * demi;
                return (
                  <g key={tranches[i]}>
                    {hp > 0 && <rect className="barre-chrono pour" x={x0} y={milieu - hp} width={w} height={hp} />}
                    {hc > 0 && <rect className="barre-chrono contre" x={x0} y={milieu} width={w} height={hc} />}
                  </g>
                );
              })}
            </g>
          );
        })}

        {/* Le fait : trait à son heure, ou bande sur son jour */}
        {fait != null ? (
          <g className="marqueur">
            <line x1={x(fait)} x2={x(fait)} y1={HAUT - 6} y2={H - AXE + 4} />
            <text x={x(fait) + 5} y={HAUT + 6}>Fait, {heure}</text>
          </g>
        ) : (
          <g className="marqueur">
            <rect x={x(debutJ)} y={HAUT - 6} width={Math.max(0, x(Math.min(finJ, t1)) - x(debutJ))} height={H - AXE - HAUT + 10} />
            <text x={x(debutJ) + 5} y={HAUT + 6}>Jour du fait</text>
          </g>
        )}
      </svg>
      <p className="note">
        Échelle commune aux trois camps : de 0 à {fmtNombre(maxCamp)} évaluations par tranche, vers le haut (pour) et vers
        le bas (contre). Seuls les candidats rattachés à un camp comptent, comme dans la barre d'opinion.
      </p>
    </div>
  );
}

/** Tableau des valeurs de la chronologie : une ligne par tranche. */
export function TableChronologie({ donnees, libelleTranche }) {
  return (
    <details className="details-donnees">
      <summary>Voir les valeurs par tranche</summary>
      <table className="table-donnees">
        <caption className="sr-only">Posts scorés et évaluations pour et contre par camp, par tranche</caption>
        <thead>
          <tr>
            <th scope="col">Tranche</th>
            <th scope="col">Posts</th>
            {Object.values(CAMPS).flatMap((l) => [
              <th scope="col" key={`${l}-p`}>{l} pour</th>,
              <th scope="col" key={`${l}-c`}>{l} contre</th>,
            ])}
          </tr>
        </thead>
        <tbody>
          {donnees.tranches.map((t, i) => (
            <tr key={t}>
              <td>{libelleTranche(t)}</td>
              <td>{fmtNombre(donnees.volume[i])}</td>
              {Object.keys(CAMPS).flatMap((c) => [
                <td key={`${c}-p`}>{fmtNombre(donnees.serie_camps[i][c].pour)}</td>,
                <td key={`${c}-c`}>{fmtNombre(donnees.serie_camps[i][c].contre)}</td>,
              ])}
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
