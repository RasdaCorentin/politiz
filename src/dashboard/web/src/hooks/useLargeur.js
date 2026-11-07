import { useEffect, useState } from "react";

// Largeur d'un élément (mesurée, pas devinée) : elle fixe le nombre de graduations possibles.
export function useLargeur(ref, parDefaut = 800) {
  const [largeur, setLargeur] = useState(parDefaut);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    // Mesure immédiate : sans elle, la largeur par défaut reste tant qu'aucun redimensionnement n'arrive.
    const mesure = el.getBoundingClientRect().width;
    if (mesure > 0) setLargeur(mesure);
    if (typeof ResizeObserver === "undefined") return undefined;
    const observateur = new ResizeObserver(([entree]) => setLargeur(entree.contentRect.width));
    observateur.observe(el);
    return () => observateur.disconnect();
  }, [ref]);
  return largeur;
}
