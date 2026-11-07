// Icône et libellé : jamais la couleur seule (DESIGN.md §4). Le sprite des symboles est rendu une
// fois, par le shell ; les autres composants le référencent par `<use href="#…">`.
import { CAMPS } from "../constantes.js";

export function Sprite() {
  return (
    <svg className="sprite" aria-hidden="true" focusable="false">
      <symbol id="i-ok" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.5" /><path d="M5 8.2l2 2 4-4.4" /></symbol>
      <symbol id="i-warn" viewBox="0 0 16 16"><path d="M8 2l6.5 11.5h-13z" /><path d="M8 6.5v3.2M8 11.6v.1" /></symbol>
      <symbol id="i-critical" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.5" /><path d="M5.5 5.5l5 5M10.5 5.5l-5 5" /></symbol>
      <symbol id="i-unknown" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.5" /><path d="M6.3 6.3a1.8 1.8 0 1 1 2.5 1.6c-.5.3-.8.7-.8 1.3M8 11.6v.1" /></symbol>
      <symbol id="i-gauche" viewBox="0 0 12 12"><rect x="1.5" y="1.5" width="9" height="9" fill="currentColor" stroke="none" /></symbol>
      <symbol id="i-centre" viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.5" fill="currentColor" stroke="none" /></symbol>
      <symbol id="i-droite" viewBox="0 0 12 12"><path d="M6 1l5 5-5 5-5-5z" fill="currentColor" stroke="none" /></symbol>
      <symbol id="i-sans-camp" viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeDasharray="2 1.5" /></symbol>
    </svg>
  );
}

// Statut de fraîcheur : point coloré, icône et libellé.
export function Statut({ fraicheur, children }) {
  const sym = { ok: "i-ok", warn: "i-warn", critical: "i-critical", unknown: "i-unknown" }[fraicheur] ?? "i-unknown";
  return (
    <p className={`statut statut-${fraicheur ?? "unknown"}`}>
      <svg className="icone" aria-hidden="true" focusable="false">
        <use href={`#${sym}`} />
      </svg>
      <span>{children}</span>
    </p>
  );
}

// Étiquette de camp : forme + libellé (jamais la couleur seule).
export function EtiquetteCamp({ camp }) {
  const libelle = CAMPS[camp] ?? "Sans camp";
  const forme = camp ? `i-${camp}` : "i-sans-camp";
  return (
    <span className={`camp-etiquette camp-${camp ?? "sans-camp"}`}>
      <svg className="icone" aria-hidden="true" focusable="false">
        <use href={`#${forme}`} />
      </svg>
      {libelle}
    </span>
  );
}
