// Barre d'opinion : position gauche/droite, marge d'erreur, période précédente (DESIGN.md §7).
import { CAMPS } from "../constantes.js";
import { fmtNombre, fmtSigne, libellePrecedente, MOINS } from "../lib/format.js";
import { EtiquetteCamp } from "./Statut.jsx";

export function Barre({ data }) {
  const { barre, candidats, periode } = data;
  const nomEntite = (id) => candidats.find((c) => c.entite === id)?.nom ?? id;
  const pct = (p) => ((p + 1) / 2) * 100;
  const prec = barre.precedente;
  const lectureOk = barre.etat === "ok";

  let texte = null;
  if (barre.etat === "insuffisant") {
    const manque = Object.entries(barre.manquants ?? {})
      .map(([camp, n]) => `${CAMPS[camp] ?? camp} ${fmtNombre(n)}`)
      .join(", ");
    texte = (
      <p>
        Pas assez de posts évalués : la barre s'affiche à partir de {fmtNombre(periode.seuil)} évaluations par camp.
        {manque && ` Il manque : ${manque}.`}
      </p>
    );
  } else if (barre.etat === "aucun_camp") {
    texte = (
      <p>
        Camps non renseignés : aucun candidat n'est rattaché à la gauche ni à la droite. Le rattachement se fait dans le fichier
        des entités.
      </p>
    );
  }

  let lecture = null;
  if (lectureOk) {
    lecture =
      barre.bas <= 0 && barre.haut >= 0
        ? "Écart non distinguable de zéro : l'intervalle contient zéro, les deux camps sont accueillis de façon comparable."
        : barre.valeur > 0
          ? "Les candidats de droite sont mieux accueillis que ceux de gauche."
          : "Les candidats de gauche sont mieux accueillis que ceux de droite.";
  }

  const aria = lectureOk
    ? `Position ${fmtSigne(barre.valeur)} sur une échelle de ${MOINS}1 (gauche) à +1 (droite), intervalle indicatif de ${fmtSigne(barre.bas)} à ${fmtSigne(barre.haut)}.`
    : texte
      ? "Barre non affichée : pas assez de posts évalués."
      : "Barre non affichée.";

  return (
    <section className="section" aria-labelledby="t-barre">
      <h3 id="t-barre">Barre d'opinion gauche et droite</h3>
      <div className="instrument">
        <p className="mention">Mesure non représentative, ce n'est pas un sondage.</p>
        <p className="note">
          Elle compare l'accueil reçu par les candidats de gauche et de droite. Elle ne compte que les candidats rattachés à un
          camp ; les partis et les candidats sans camp restent dans la cote.
        </p>

        {lectureOk ? (
          <>
            <div className="barre-piste" role="img" aria-label={aria}>
              <span className="barre-marge" style={{ left: `${pct(barre.bas)}%`, width: `${pct(barre.haut) - pct(barre.bas)}%` }} />
              <span className="graduation" style={{ left: "50%" }} />
              {prec?.etat === "ok" && <span className="barre-fantome" style={{ left: `${pct(prec.valeur)}%` }} />}
              <span className="barre-curseur" style={{ left: `${pct(barre.valeur)}%` }} />
            </div>
            <div className="barre-legende">
              <span>
                <strong>Gauche</strong> mieux accueillie
              </span>
              <span>
                Droite mieux accueillie <strong>→</strong>
              </span>
            </div>
          </>
        ) : (
          <>
            <div className="barre-piste vide" role="img" aria-label={aria} />
            <div className="barre-legende">
              <span>Gauche</span>
              <span>Droite</span>
            </div>
          </>
        )}

        {texte && <div className="barre-lecture">{texte}</div>}
        {lectureOk && (
          <div className="barre-lecture">
            <p>
              Position <span className="tnum">{fmtSigne(barre.valeur)}</span> · intervalle indicatif à 95 % de{" "}
              <span className="tnum">{fmtSigne(barre.bas)}</span> à <span className="tnum">{fmtSigne(barre.haut)}</span>.
            </p>
            <p>{lecture}</p>
            {prec?.etat === "ok" ? (
              <p className="sec">
                Trait en pointillés : {libellePrecedente(periode)}, position {fmtSigne(prec.valeur)}.
              </p>
            ) : null}
          </div>
        )}

        <table className="barre-chiffres">
          <caption className="sr-only">Décompte par camp de la barre d'opinion</caption>
          <thead>
            <tr>
              <th scope="col">Camp</th>
              <th scope="col">Pour</th>
              <th scope="col">Contre</th>
              <th scope="col">Évalués</th>
              <th scope="col">Indice</th>
            </tr>
          </thead>
          <tbody>
            {["gauche", "centre", "droite"].map((camp) => {
              const c = barre.camps?.[camp];
              return (
                <tr key={camp}>
                  <td>
                    <EtiquetteCamp camp={camp} />
                  </td>
                  <td>{fmtNombre(c?.pour ?? 0)}</td>
                  <td>{fmtNombre(c?.contre ?? 0)}</td>
                  <td>{fmtNombre(c?.evalues ?? 0)}</td>
                  <td>{c?.indice == null ? "n/d" : fmtSigne(c.indice)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="note">
          Candidats gauche : {(barre.camps?.gauche?.candidats ?? []).map(nomEntite).join(", ") || "aucun"}. Candidats droite :{" "}
          {(barre.camps?.droite?.candidats ?? []).map(nomEntite).join(", ") || "aucun"}. Centre affiché, hors calcul : il n'a pas
          de sens gauche ou droite.
        </p>
        <p className="barre-formule">
          Position = (indice droite − indice gauche) / 2, entre {MOINS}1 et +1 ; positif = droite mieux accueillie. Hors de la
          barre : {fmtNombre(data.non_classes_evalues)} évaluations de candidats sans camp et des partis.
        </p>
      </div>
    </section>
  );
}
