// Coquille de l'interface : barre latérale (titre, fraîcheur, pages, mention M10), en-tête de la page
// (lecture de la base, avertissements, titre, période) et pied de page. La période est un petit
// sélecteur dans l'en-tête, absent de la page « événement » qui a sa propre fenêtre de dates.
// Sous 900 px, la barre latérale passe au-dessus du contenu (CSS).
import { MENTION_M10, PAGES, PERIODES, TITRE_APP } from "../constantes.js";
import { ageSecondes, fmtHeure, libelleFenetre, libelleFraicheur } from "../lib/format.js";
import { construireQuery } from "../lib/url.js";
import { CreditsPhotos } from "./CreditsPhotos.jsx";
import { Sprite, Statut } from "./Statut.jsx";

// Période : quatre boutons radio compacts, à droite du titre de la page.
function SelecteurPeriode({ periode, onPeriode }) {
  return (
    <fieldset className="controle selecteur-periode">
      <legend className="sr-only">Période</legend>
      <div className="segments compact" role="radiogroup" aria-label="Période">
        {PERIODES.map((x) => (
          <label key={x.valeur} title={x.libelle}>
            <input
              type="radio"
              name="periode"
              value={x.valeur}
              aria-label={x.libelle}
              checked={periode === x.valeur}
              onChange={() => onPeriode(x.valeur)}
            />
            <span aria-hidden="true">{x.court}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function Shell({ etat, page, donnees, erreur, onNavigation, onPeriode, children }) {
  const age = donnees?.etat ? ageSecondes(donnees.etat, donnees.generated_at) : null;
  const texteStatut = donnees?.etat ? libelleFraicheur(donnees.etat, age) : erreur ? "Données indisponibles" : "Chargement des données";
  // Les liens gardent l'état (période, dates, seuil) : changer de page ne le perd pas.
  const lien = (vue) => `?${construireQuery({ ...etat, vue })}`;

  return (
    <>
      <Sprite />
      <a className="lien-evitement" href="#contenu">
        Aller au contenu
      </a>

      <aside className="barre-laterale" aria-label="Pages et état des données">
        <div className="marque">
          <h1 id="titre">{TITRE_APP}</h1>
          <Statut fraicheur={donnees?.etat?.fraicheur}>{texteStatut}</Statut>
        </div>
        <nav aria-label="Pages">
          <ul className="navigation">
            {PAGES.map((p) => (
              <li key={p.valeur}>
                <a
                  href={lien(p.valeur)}
                  aria-current={p.valeur === page.valeur ? "page" : undefined}
                  onClick={(e) => {
                    e.preventDefault();
                    onNavigation(p.valeur);
                  }}
                >
                  {p.libelle}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <p className="pied-mention">{MENTION_M10}</p>
      </aside>

      <main id="contenu" className="principal" aria-labelledby="titre-page">
        <div className="entete-page">
          {donnees?.bandeau && <p className="bandeau">{donnees.bandeau}</p>}
          {donnees && (
            <p className="sec tnum">
              Lecture de la base à {fmtHeure(donnees.generated_at)} (heure de Paris)
              {donnees.periode && page.valeur !== "evenement" ? ` · ${libelleFenetre(donnees.periode)}` : ""}
            </p>
          )}
          {erreur && donnees && (
            <p className="bandeau" role="status">
              Affichage périmé. {erreur} Les chiffres sont ceux du dernier chargement réussi.
            </p>
          )}
          {donnees?.etat?.avertissements?.length > 0 && (
            <section className="etat" aria-label="Avertissements">
              {donnees.etat.avertissements.map((a, i) => (
                <p key={i}>{a}</p>
              ))}
            </section>
          )}
          {donnees && !donnees.etat.lexique_charge && (
            <p className="note">Le fichier des entités n'est pas chargé : noms et camps sont absents.</p>
          )}
        </div>

        <header className="titre-page">
          <div className="titre-ligne">
            <h2 id="titre-page">{page.titre}</h2>
            {page.valeur !== "evenement" && <SelecteurPeriode periode={etat.periode} onPeriode={onPeriode} />}
          </div>
          <p className="note">{page.intro}</p>
        </header>

        {children}

        <footer className="pied-page">
          <CreditsPhotos entites={(donnees?.candidats ?? []).map((e) => e.entite)} />
        </footer>
      </main>
    </>
  );
}
