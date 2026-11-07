// États communs (DESIGN.md §9) : chargement, erreur bloquante, vide.

export function Chargement() {
  return (
    <div aria-busy="true" aria-live="polite" className="section">
      <p className="sec">Chargement des données…</p>
      <div className="grille">
        <div className="squelette" />
        <div className="squelette" />
      </div>
    </div>
  );
}

export function EtatBloquant({ titre, children, onReessayer }) {
  return (
    <section className="etat etat-erreur" role="alert">
      <h3>{titre}</h3>
      {children}
      {onReessayer && (
        <button type="button" className="bouton" onClick={onReessayer}>
          Réessayer
        </button>
      )}
    </section>
  );
}

export function EtatVide({ titre, children, action }) {
  return (
    <section className="etat" aria-live="polite">
      <h3>{titre}</h3>
      {children}
      {action}
    </section>
  );
}
