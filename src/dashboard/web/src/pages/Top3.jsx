// Page « top 3 » : deux panneaux l'un sous l'autre (candidats, partis), trois entités côte à côte.
// Pour chaque entité classée au top 3 : des bulles de thèmes (surface = posts), des bulles d'adjectifs
// par stance (surface = posts), des barres d'émotions triées (occurrences), des tableaux sous le panneau.
// Les données viennent de `croisements` et `adjectifs` (contrat `tableau`) ; les entités, de `candidats` et `partis`.
import { LIBELLE_EMOTION } from "../constantes.js";
import { Barres } from "../components/Barres.jsx";
import { Bulles } from "../components/Bulles.jsx";
import { BullesMots } from "../components/BullesMots.jsx";
import { Pastille } from "../components/Pastille.jsx";
import { EtiquetteCamp } from "../components/Statut.jsx";
import { fmtDateHeure, fmtNombre, fmtPourcent } from "../lib/format.js";

const MAX_BULLES = 9; // au plus 9 bulles ; « autre » reste la dernière
const AUTRE = "autre";

// Thèmes d'une entité, par posts décroissants, « autre » en dernier. Le tableau garde tous les thèmes.
function themesDe(themes, entite) {
  const liste = themes.filter((t) => t.entite === entite && t.posts > 0);
  const autres = liste.filter((t) => t.theme === AUTRE);
  const reste = liste.filter((t) => t.theme !== AUTRE).sort((a, b) => b.posts - a.posts);
  return { tous: [...reste, ...autres], bulles: [...reste.slice(0, autres.length ? MAX_BULLES - 1 : MAX_BULLES), ...autres] };
}

// Émotions d'une entité, par occurrences décroissantes : barres et tableau lisent le même ordre.
// La valeur est `occurrences` (contrat `tableau`), et non `posts`.
function emotionsDe(emotions, entite) {
  return emotions
    .filter((x) => x.entite === entite)
    .sort((a, b) => b.occurrences - a.occurrences)
    .map((x) => ({ cle: x.emotion, libelle: LIBELLE_EMOTION[x.emotion] ?? x.emotion, valeur: x.occurrences }));
}

// Adjectifs d'une entité pour une stance, déjà triés et bornés par l'API (section `adjectifs`).
function adjectifsDe(adjectifs, entite, stance) {
  return (adjectifs?.lignes ?? [])
    .filter((a) => a.entite === entite && a.stance === stance)
    .map((a) => ({ cle: a.adjectif, mot: a.adjectif, posts: a.posts }));
}

const STANCES_ADJECTIFS = [
  ["pour", "Dans les posts favorables"],
  ["contre", "Dans les posts défavorables"],
];

function Adjectifs({ adjectifs, e, nom }) {
  if (adjectifs == null) return null; // section absente : une seule note pour toute la page
  const groupes = STANCES_ADJECTIFS.map(([stance, titre]) => [stance, titre, adjectifsDe(adjectifs, e.entite, stance)]);
  return (
    <>
      <p className="legende-titre">Adjectifs</p>
      {groupes.every(([, , items]) => !items.length) ? (
        <p className="sec">Aucun adjectif vu dans au moins 3 posts sur la période.</p>
      ) : (
        <div className="adjectifs-groupes">
          {groupes.map(([stance, titre, items]) => (
            <div key={stance} className="adjectifs-groupe">
              <p className={`adjectifs-titre stance-${stance}`}>{titre}</p>
              {items.length ? (
                <BullesMots items={items} stance={stance} titre={`Adjectifs associés à ${nom}, ${titre.toLowerCase()}`} />
              ) : (
                <p className="sec">Aucun.</p>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

// Une note pour toute la page : d'où viennent les adjectifs et les dates qu'ils couvrent (section `adjectifs.couverture`).
function NoteAdjectifs({ adjectifs }) {
  if (adjectifs == null) {
    return <p className="note">Adjectifs non comptés sur ces données : la base n'a pas de table d'adjectifs.</p>;
  }
  const c = adjectifs.couverture;
  return (
    <p className="note">
      Adjectifs d'un lexique fermé, comptés une fois par post et par entité évaluée pour ou contre, sans lien
      grammatical avec l'entité.{" "}
      {c == null
        ? "Aucun adjectif compté sur cette période : ses posts ont été scorés avant le comptage des adjectifs, ou n'en contiennent aucun."
        : c.posts_hors > 0
          ? `Comptés du ${fmtDateHeure(c.debut)} au ${fmtDateHeure(c.fin)} seulement : ${fmtNombre(c.posts_hors)} posts scorés de la période, hors de ces dates, n'en ont pas.`
          : ""}
    </p>
  );
}

function Entite({ e, themes, emotions, adjectifs }) {
  const nom = e.nom ?? e.entite;
  const { bulles } = themesDe(themes, e.entite);
  const items = bulles.map((t) => ({ cle: t.theme, libelle: t.libelle, posts: t.posts }));
  const emotionsItems = emotionsDe(emotions, e.entite);

  return (
    <article className="top-entite">
      <header className="top-entete">
        <span className="rang tnum">{e.rang}</span>
        <Pastille entite={e.entite} nom={nom} camp={e.camp} taille={64} />
        <h4 className="top-nom">{nom}</h4>
        <EtiquetteCamp camp={e.camp} />
      </header>
      <p className="note">
        Évalués {fmtNombre(e.evalues)} sur {fmtNombre(e.cites)} cités · couverture {fmtPourcent(e.couverture)}
      </p>
      <p className="legende-titre">Thèmes</p>
      {items.length ? (
        <Bulles items={items} nom={nom} camp={e.camp} />
      ) : (
        <p className="sec">Aucun thème pour cette entité sur la période.</p>
      )}
      <Adjectifs adjectifs={adjectifs} e={e} nom={nom} />
      {emotionsItems.length > 0 && (
        <>
          <p className="legende-titre">Émotions</p>
          <Barres items={emotionsItems} petites titre={`Émotions de ${nom} : occurrences par émotion`} />
          <p className="note">Nombre d'occurrences par émotion.</p>
        </>
      )}
    </article>
  );
}

function Panneau({ id, titre, entite, entites, themes, emotions, adjectifs }) {
  const libelle = entite === "partis" ? "parti" : "candidat";
  const lignes = entites.flatMap((e) =>
    themesDe(themes, e.entite).tous.map((t) => ({ cle: `${e.entite}-${t.theme}`, nom: e.nom ?? e.entite, libelle: t.libelle, posts: t.posts })),
  );
  const lignesEmotions = entites.flatMap((e) =>
    emotionsDe(emotions, e.entite).map((x) => ({
      cle: `${e.entite}-${x.cle}`,
      nom: e.nom ?? e.entite,
      libelle: x.libelle,
      occurrences: x.valeur,
    })),
  );
  const noms = new Map(entites.map((e) => [e.entite, e.nom ?? e.entite]));
  const lignesAdjectifs = (adjectifs?.lignes ?? [])
    .filter((a) => noms.has(a.entite))
    .map((a) => ({ cle: `${a.entite}-${a.stance}-${a.adjectif}`, nom: noms.get(a.entite), stance: a.stance, adjectif: a.adjectif, posts: a.posts }));
  return (
    <section className="panneau-top" aria-labelledby={id}>
      <h3 id={id}>{titre}</h3>
      {entites.length === 0 ? (
        <p className="sec">Aucun {libelle} au-dessus du seuil sur cette période.</p>
      ) : (
        <>
          <div className="entites-top">
            {entites.map((e) => (
              <Entite key={e.entite} e={e} themes={themes} emotions={emotions} adjectifs={adjectifs} />
            ))}
          </div>
          {lignes.length > 0 && (
            <details className="details-donnees">
              <summary>Voir les valeurs : posts par thème</summary>
              <table className="table-donnees">
                <caption className="sr-only">Posts par thème pour chaque {libelle} du panneau</caption>
                <thead>
                  <tr>
                    <th scope="col">Entité</th>
                    <th scope="col">Thème</th>
                    <th scope="col">Posts</th>
                  </tr>
                </thead>
                <tbody>
                  {lignes.map((l) => (
                    <tr key={l.cle}>
                      <td>{l.nom}</td>
                      <td>{l.libelle}</td>
                      <td>{fmtNombre(l.posts)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
          {lignesAdjectifs.length > 0 && (
            <details className="details-donnees">
              <summary>Voir les valeurs : posts par adjectif</summary>
              <table className="table-donnees">
                <caption className="sr-only">Posts par adjectif et par stance pour chaque {libelle} du panneau</caption>
                <thead>
                  <tr>
                    <th scope="col">Entité</th>
                    <th scope="col">Stance</th>
                    <th scope="col">Adjectif</th>
                    <th scope="col">Posts</th>
                  </tr>
                </thead>
                <tbody>
                  {lignesAdjectifs.map((l) => (
                    <tr key={l.cle}>
                      <td>{l.nom}</td>
                      <td>{l.stance}</td>
                      <td>{l.adjectif}</td>
                      <td>{fmtNombre(l.posts)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
          {lignesEmotions.length > 0 && (
            <details className="details-donnees">
              <summary>Voir les valeurs : occurrences par émotion</summary>
              <table className="table-donnees">
                <caption className="sr-only">Occurrences par émotion pour chaque {libelle} du panneau</caption>
                <thead>
                  <tr>
                    <th scope="col">Entité</th>
                    <th scope="col">Émotion</th>
                    <th scope="col">Occurrences</th>
                  </tr>
                </thead>
                <tbody>
                  {lignesEmotions.map((l) => (
                    <tr key={l.cle}>
                      <td>{l.nom}</td>
                      <td>{l.libelle}</td>
                      <td>{fmtNombre(l.occurrences)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
        </>
      )}
    </section>
  );
}

export function Top3({ data }) {
  const croisements = data.croisements ?? { scoreur: null, themes: [], emotions: [] };
  const themes = croisements.themes ?? [];
  const emotions = croisements.emotions ?? [];
  const adjectifs = data.adjectifs ?? null;
  const topTrois = (liste) => liste.filter((e) => e.rang != null && e.rang <= 3).sort((a, b) => a.rang - b.rang);

  return (
    <>
      {croisements.scoreur && <p className="note">Scoreur : {croisements.scoreur}.</p>}
      <NoteAdjectifs adjectifs={adjectifs} />
      <div className="top3-panneaux">
        <Panneau
          id="t-top-candidats"
          titre="Top 3 candidats"
          entite="candidats"
          entites={topTrois(data.candidats)}
          themes={themes}
          emotions={emotions}
          adjectifs={adjectifs}
        />
        <Panneau
          id="t-top-partis"
          titre="Top 3 partis"
          entite="partis"
          entites={topTrois(data.partis)}
          themes={themes}
          emotions={emotions}
          adjectifs={adjectifs}
        />
      </div>
    </>
  );
}
