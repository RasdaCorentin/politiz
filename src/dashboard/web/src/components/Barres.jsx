import { fmtNombre } from "../lib/format.js";

// Barres horizontales, dans l'ordre reçu de l'appelant (déjà trié). Une teinte : la longueur porte
// la valeur, écrite au bout de la barre.
export function Barres({ items, petites = false, titre }) {
  const max = Math.max(...items.map((i) => i.valeur), 1);
  return (
    <ul className={petites ? "barres petites" : "barres"} aria-label={titre}>
      {items.map((i) => (
        <li key={i.cle}>
          <span>{i.libelle}</span>
          <span className="piste">
            <span className="rempli" style={{ width: `${(i.valeur / max) * 100}%` }} />
          </span>
          <span className="valeur tnum">{fmtNombre(i.valeur)}</span>
        </li>
      ))}
    </ul>
  );
}
