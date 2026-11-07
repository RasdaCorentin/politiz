// Page « contraste » : ton des posts, ton dans le temps, émotions triées, thèmes.
// Les parts affichées sont des proportions d'un total déjà reçu (aucune formule de l'API n'est refaite).
import { EMOTIONS, TONS } from "../constantes.js";
import { Barres } from "../components/Barres.jsx";
import { GraphiqueTemps } from "../components/GraphiqueTemps.jsx";
import { fmtDecimal, fmtHeure, fmtNombre, fmtPourcent, libellePas, libelleTranche, NBSP } from "../lib/format.js";

// Mini-courbe d'un volume : une seule série, pas d'axe (la valeur est écrite à côté).
function Sparkline({ valeurs }) {
  if (!valeurs.length) return null;
  const max = Math.max(...valeurs, 1);
  const n = valeurs.length;
  const pts = valeurs.map((v, i) => `${n > 1 ? (i / (n - 1)) * 100 : 50},${100 - (v / max) * 96 - 2}`);
  return (
    <svg className="spark" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Volume de posts par tranche sur la période">
      <path d={`M${pts.join(" L")}`} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function Contraste({ data }) {
  const { pipeline, volume = [], tranches = [], ton, serie_ton = [], emotions = {}, emotions_non_evaluees, themes = [], etat } = data;
  const evalues = ton.positif + ton.neutre + ton.negatif;
  const totalTon = evalues + ton.non_evalue;
  // La jauge ne porte que les posts polarisés (positif et négatif) : le neutre a sa propre barre.
  const polarises = ton.positif + ton.negatif;
  const partPositif = polarises ? ton.positif / polarises : null;
  const partNeutre = evalues ? ton.neutre / evalues : null;
  const maxVolume = Math.max(...volume, 1);
  const pas = data.periode.pas_min;
  const lignesTemps = tranches.map((t, i) => ({
    heure: libelleTranche(t, pas),
    total: volume[i] ?? 0,
    ...serie_ton[i],
  }));
  // Émotions triées par nombre de posts (le tri est stable : à égalité, l'ordre du contrat tient).
  const itemsEmotions = EMOTIONS.map(([k, l]) => ({ cle: k, libelle: l, valeur: emotions[k] ?? 0 })).sort(
    (a, b) => b.valeur - a.valeur,
  );
  const itemsThemes = themes.map((t) => ({ cle: t.theme, libelle: t.libelle, valeur: t.posts }));

  return (
    <>
      <div className="tuiles">
        <div className="bloc">
          <p className="tuile-t">Posts scorés</p>
          <p className="tuile-v tnum">{fmtNombre(pipeline.posts)}</p>
          <p className="tuile-s">sur la période, par tranche de {libellePas(pas)}</p>
          <Sparkline valeurs={volume} />
        </div>
        <div className="bloc">
          <p className="tuile-t">Dernière donnée</p>
          <p className="tuile-v">{fmtHeure(etat.derniere_maj)}</p>
          <p className="tuile-s">{etat.derniere_maj ? "heure de Paris" : "aucune donnée"}</p>
        </div>
        <div className="bloc">
          <p className="tuile-t">Délai moyen de traitement</p>
          <p className="tuile-v tnum">{pipeline.latence_moyenne_s == null ? "n/d" : `${fmtDecimal(pipeline.latence_moyenne_s)}${NBSP}s`}</p>
          <p className="tuile-s">moyenne sur la période</p>
        </div>
      </div>

      <div className="grille">
        <div className="bloc">
          <h4>Ton des posts</h4>
          {polarises ? (
            <>
              <p className="sec">Positif contre négatif, sur {fmtNombre(polarises)} posts polarisés</p>
              <div
                className="jauge"
                role="img"
                aria-label={`Posts polarisés : ${fmtPourcent(partPositif)} positifs, ${fmtPourcent(1 - partPositif)} négatifs.`}
              >
                <span className="fond-ton-positif" style={{ width: `${partPositif * 100}%` }} />
                <span className="fond-ton-negatif" style={{ width: `${(1 - partPositif) * 100}%` }} />
                <span className="jauge-repere" aria-hidden="true" />
              </div>
              <ul className="legende">
                <li>
                  <span className="pastille fond-ton-positif" aria-hidden="true" />
                  Positif {fmtNombre(ton.positif)} <span className="sec">({fmtPourcent(partPositif)})</span>
                </li>
                <li>
                  <span className="pastille fond-ton-negatif" aria-hidden="true" />
                  Négatif {fmtNombre(ton.negatif)} <span className="sec">({fmtPourcent(1 - partPositif)})</span>
                </li>
              </ul>
            </>
          ) : (
            <p className="sec">Aucun post polarisé sur la période.</p>
          )}

          <div className="neutre-bloc">
            <p className="legende-titre">Neutre (ni positif ni négatif)</p>
            <div className="pile" role="img" aria-label={`Neutre : ${fmtNombre(ton.neutre)} posts`}>
              <span className="fond-ton-neutre" style={{ width: `${(partNeutre ?? 0) * 100}%` }} />
            </div>
            <p className="note">
              {fmtNombre(ton.neutre)} posts, soit {fmtPourcent(partNeutre)} des posts évalués.
            </p>
          </div>

          <p className="note">
            Ton évalué sur {fmtNombre(evalues)} posts sur {fmtNombre(totalTon)} (couverture{" "}
            {fmtPourcent(totalTon ? evalues / totalTon : null)}). Les posts sans ton détecté ({fmtNombre(ton.non_evalue)}) ne sont
            pas représentés.
          </p>
        </div>

        <div className="bloc">
          <h4>Ton dans le temps</h4>
          <GraphiqueTemps lignes={lignesTemps} tranches={tranches} pas={pas} maxVolume={maxVolume} />
          <ul className="legende">
            {TONS.map(([k, l, cls]) => (
              <li key={k}>
                <span className={`pastille ${cls}`} aria-hidden="true" />
                {l}
              </li>
            ))}
          </ul>
          <details className="details-donnees">
            <summary>Voir les valeurs par tranche</summary>
            <table className="table-donnees">
              <caption className="sr-only">Posts par tranche de temps et ton</caption>
              <thead>
                <tr>
                  <th scope="col">Heure</th>
                  <th scope="col">Posts</th>
                  {TONS.map(([k, l]) => (
                    <th scope="col" key={k}>
                      {l}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {lignesTemps.map((l, i) => (
                  <tr key={tranches[i]}>
                    <td>{l.heure}</td>
                    <td>{fmtNombre(l.total)}</td>
                    {TONS.map(([k]) => (
                      <td key={k}>{fmtNombre(l[k] ?? 0)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>

        <div className="bloc">
          <h4>Émotions</h4>
          <Barres items={itemsEmotions} titre="Émotions : posts par émotion, du plus au moins fréquent" />
          <p className="note">{fmtNombre(emotions_non_evaluees)} posts sans émotion détectée.</p>
        </div>

        <div className="bloc">
          <h4>Thèmes</h4>
          <Barres items={itemsThemes} titre="Thèmes : posts par thème" />
          <p className="note">Un post compte dans chacun de ses thèmes : la somme peut dépasser le nombre de posts.</p>
        </div>
      </div>
    </>
  );
}
