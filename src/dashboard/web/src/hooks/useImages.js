// Manifeste des photos de candidats (images/candidats/index.json), écrit au build Docker par
// outils/telecharger_images.mjs. Lu une seule fois pour toute la page ; absent : aucune photo,
// la pastille garde les initiales. Même origine : la CSP (`img-src 'self'`) reste inchangée.
import { useEffect, useState } from "react";

const URL_MANIFESTE = "images/candidats/index.json";
let promesse = null;

function charger() {
  promesse ??= fetch(URL_MANIFESTE)
    .then((r) => (r.ok ? r.json() : { images: {} }))
    .then((m) => m.images ?? {})
    .catch(() => ({}));
  return promesse;
}

/** @returns {Record<string, {fichier, auteur, licence, licence_url, page_commons}>} id d'entité -> photo */
export function useImages() {
  const [images, setImages] = useState({});
  useEffect(() => {
    let actif = true;
    charger().then((m) => actif && setImages(m));
    return () => {
      actif = false;
    };
  }, []);
  return images;
}

export const cheminImage = (photo) => `images/candidats/${photo.fichier}`;
