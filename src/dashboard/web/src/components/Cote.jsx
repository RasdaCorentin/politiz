// Cote de popularité : classement par indice net (candidats ou partis), bandeau repliable pour les
// entités sous le seuil, courbes par candidat. Les barres divergent de zéro ; la couleur suit le camp.
import { useMemo } from "react";
import { CIBLES } from "../constantes.js";
import { fmtNombre, fmtPourcent, fmtSigne, MOINS } from "../lib/format.js";
import { Courbes } from "./Courbes.jsx";
import { Pastille } from "./Pastille.jsx";
import { EtiquetteCamp } from "./Statut.jsx";

// Une ligne de classement : rang, avatar et nom, camp, barre divergente, indice écrit, décompte.
// Sans rang (sous le seuil) : ni indice ni barre, seulement le décompte.
export function LigneCote({ e, nomPar, seuil }) {
  const classe = e.camp ? `camp-${e.camp}` : "sans-camp";
  const classee = e.rang != null && e.indice != null;
  const largeur = classee ? (Math.abs(e.indice) / 2) * 100 : 0;
  const gauche = classee && e.indice < 0 ? 50 - largeur : 50;
  const nom = nomPar(e);
  return (
    <li>
      <span className={`rang ${classee ? "" : "nc"}`}>
        {e.rang ?? (
          <>
            <span className="sr-only">Non classé</span>—
          </>
        )}
      </span>
      <span className="nom-cote">
        <Pastille entite={e.entite} nom={nom} camp={e.camp} taille={40} />
        <span className="nom">{nom}</span>
        <EtiquetteCamp camp={e.camp} />
      </span>
      <span className="valeur-indice">{classee ? fmtSigne(e.indice) : "n/d"}</span>
      {classee ? (
        <span className="indice-diverge" aria-hidden="true">
          <span className={`barre-indice ${classe}`} style={{ left: `${gauche}%`, width: `${largeur}%` }} />
        </span>
      ) : null}
      <span className="detail-ligne">
        {!classee ? `Sous le seuil de ${fmtNombre(seuil)} évaluations · ` : ""}
        {fmtNombre(e.evalues)} évalué{e.evalues > 1 ? "s" : ""} sur {fmtNombre(e.cites)} cité{e.cites > 1 ? "s" : ""}
        {" · "}couverture {fmtPourcent(e.couverture)}
      </span>
    </li>
  );
}

export function Cote({ data, cible, onCible }) {
  const nomPar = useMemo(() => {
    const noms = new Map([...data.candidats, ...data.partis].map((e) => [e.entite, e.nom]));
    return (e) => noms.get(e.entite) ?? e.entite;
  }, [data]);
  const seuil = data.periode.seuil;
  const liste = cible === "partis" ? data.partis : data.candidats;
  const libelleEntite = cible === "partis" ? "parti" : "candidat";
  const classees = liste.filter((e) => e.rang != null).sort((a, b) => a.rang - b.rang);
  const sousSeuil = liste.filter((e) => e.rang == null);

  return (
    <section className="section" aria-labelledby="t-cote">
      <h3 id="t-cote">Cote de popularité</h3>
      <p className="note">
        Indice net : (posts pour − posts contre) / (pour + contre), entre {MOINS}1 et +1. « Évalués » : posts dont la stance est
        pour ou contre ; « cités » : tous les posts qui nomment la cible. Un post qui cite deux candidats compte deux fois.
      </p>

      <fieldset className="controle commutateur">
        <legend>Entités</legend>
        <div className="segments" role="radiogroup">
          {CIBLES.map((x) => (
            <label key={x.valeur}>
              <input type="radio" name="cible" value={x.valeur} checked={cible === x.valeur} onChange={() => onCible(x.valeur)} />
              <span>{x.libelle}</span>
            </label>
          ))}
        </div>
      </fieldset>

      {liste.length === 0 ? (
        <p className="sec">Aucun {libelleEntite} cité sur cette période.</p>
      ) : (
        <>
          {classees.length > 0 ? (
            <ol className="classement">
              {classees.map((e) => (
                <LigneCote key={e.entite} e={e} nomPar={nomPar} seuil={seuil} />
              ))}
            </ol>
          ) : (
            <p className="sec">Aucun {libelleEntite} au-dessus du seuil de {fmtNombre(seuil)} évaluations.</p>
          )}
          {sousSeuil.length > 0 && (
            <details className="bandeau-repliable">
              <summary>
                Sous le seuil de {fmtNombre(seuil)} évaluations : {fmtNombre(sousSeuil.length)} sans indice
              </summary>
              <ol className="classement">
                {sousSeuil.map((e) => (
                  <LigneCote key={e.entite} e={e} nomPar={nomPar} seuil={seuil} />
                ))}
              </ol>
            </details>
          )}
        </>
      )}

      <Courbes data={data} nomPar={nomPar} />
    </section>
  );
}
