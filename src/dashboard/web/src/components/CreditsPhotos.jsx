// Crédits des photos affichées : auteur, licence (lien), page Commons (lien). Les licences CC BY et
// CC BY-SA exigent cette attribution. Les liens ne chargent rien avant le clic.
import { useImages } from "../hooks/useImages.js";

// `entites` : ids des entités de la réponse ; seules leurs photos sont créditées (celles qui peuvent s'afficher).
export function CreditsPhotos({ entites = [] }) {
  const images = useImages();
  const presentes = new Set(entites);
  const ids = Object.keys(images).filter((id) => presentes.has(id)).sort((a, b) => images[a].nom.localeCompare(images[b].nom, "fr"));
  if (!ids.length) return null;
  return (
    <details className="details-donnees credits-photos">
      <summary>Crédits des photos</summary>
      <p className="note">Photos libres de Wikimedia Commons, copiées au build et servies par ce site.</p>
      <ul>
        {ids.map((id) => {
          const p = images[id];
          return (
            <li key={id}>
              {p.nom} : {p.auteur ?? "auteur inconnu"},{" "}
              {p.licence_url ? (
                <a href={p.licence_url} rel="noreferrer noopener license" target="_blank">
                  {p.licence}
                </a>
              ) : (
                p.licence
              )}
              {p.page_commons && (
                <>
                  {" · "}
                  <a href={p.page_commons} rel="noreferrer noopener" target="_blank">
                    page Commons
                  </a>
                </>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
}
