// Pastille d'une entité. Avec une photo libre (manifeste du build) : portrait rond, bordure de la
// couleur du camp. Sans photo : initiales dans une forme de camp (carré, rond, losange) ; sans camp,
// cercle en pointillés, encre --data. La couleur ne porte jamais seule le camp : l'étiquette de camp
// voisine dit aussi la forme et le libellé (DESIGN.md §5). Le crédit de la photo est dans son
// infobulle et dans « Crédits des photos ».
import { cheminImage, useImages } from "../hooks/useImages.js";
import { initiales } from "../lib/format.js";

export function Pastille({ entite, nom, camp, taille = 28 }) {
  const images = useImages();
  const photo = entite ? images[entite] : null;
  const classeCamp = `camp-${camp ?? "sans-camp"}`;

  if (photo) {
    const credit = [photo.auteur, photo.licence].filter(Boolean).join(", ");
    return (
      <span className={`portrait ${classeCamp}`} style={{ width: taille, height: taille }} title={credit ? `Photo : ${credit}` : undefined}>
        <img src={cheminImage(photo)} alt="" width={taille} height={taille} loading="lazy" decoding="async" />
      </span>
    );
  }

  return (
    <svg
      className={`pastille-candidat ${classeCamp}`}
      width={taille}
      height={taille}
      viewBox="0 0 28 28"
      aria-hidden="true"
      focusable="false"
    >
      {camp === "gauche" && <rect x="2" y="2" width="24" height="24" rx="3" />}
      {camp === "centre" && <circle cx="14" cy="14" r="12" />}
      {camp === "droite" && <path d="M14 2 L26 14 L14 26 L2 14 Z" />}
      {!camp && <circle cx="14" cy="14" r="12" className="sans-camp-trait" />}
      <text x="14" y="18" textAnchor="middle">
        {initiales(nom)}
      </text>
    </svg>
  );
}
