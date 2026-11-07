// Page « événement » : relier un fait daté à la réaction des discussions.
// 1. Choisir le fait : dans le catalogue (`api/evenements`, recherche par texte et catégorie) ou à la main.
// 2. Isoler la semaine autour du jour J (J−3 à J+3) : une réponse `tableau` pour la chronologie.
// 3. Comparer avant (J−3 à J−1) et après (J à J+2), trois jours chacun : deux réponses, valeurs reçues
//    côte à côte. La page ne calcule aucun écart : elle montre, elle ne conclut pas.
import { useMemo, useState } from "react";
import { useContractData } from "../hooks/useContractData.js";
import {
  CAMPS,
  CATEGORIES_EVENEMENT,
  JOURS_AUTOUR,
  LIBELLE_CATEGORIE,
  POLL_LONG_MS,
  SCHEMA_EVENEMENTS,
  SCHEMA_VERSION,
} from "../constantes.js";
import { ChronologieEvenement, TableChronologie } from "../components/ChronologieEvenement.jsx";
import { Chargement } from "../components/Etats.jsx";
import { EtiquetteCamp } from "../components/Statut.jsx";
import { dateValide, decalerJour, heureParis, heureValide, jourParis } from "../lib/dates.js";
import { fmtNombre, fmtSigne, libelleTranche } from "../lib/format.js";
import { LIBELLE_EVENEMENT_MAX } from "../lib/url.js";

const RESULTATS_MAX = 40;
const dateLongue = new Intl.DateTimeFormat("fr-FR", { timeZone: "Europe/Paris", weekday: "long", day: "numeric", month: "long", year: "numeric" });
const dateCatalogue = new Intl.DateTimeFormat("fr-FR", { timeZone: "Europe/Paris", day: "numeric", month: "short", year: "numeric" });
const sansAccents = (s) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

function adresse(debut, fin, seuil) {
  return `api/tableau?debut=${debut}&fin=${fin}${seuil ? `&seuil=${seuil}` : ""}`;
}

// Bornes des trois lectures autour du jour J ; aucune date au-delà d'aujourd'hui (l'API la refuse).
function plages(jour, aujourdhui) {
  const borne = (j) => (j > aujourdhui ? aujourdhui : j);
  return {
    fenetre: { debut: decalerJour(jour, -JOURS_AUTOUR), fin: borne(decalerJour(jour, JOURS_AUTOUR)) },
    avant: { debut: decalerJour(jour, -JOURS_AUTOUR), fin: decalerJour(jour, -1) },
    apres: { debut: jour, fin: borne(decalerJour(jour, JOURS_AUTOUR - 1)) },
  };
}

function Catalogue({ etatCatalogue, choisi, minDate, aujourdhui, onChoisir }) {
  const [texte, setTexte] = useState("");
  const [categorie, setCategorie] = useState("toutes");
  const liste = etatCatalogue.data?.evenements ?? [];
  const filtres = useMemo(() => {
    const motif = sansAccents(texte.trim());
    return liste.filter(
      (e) =>
        (categorie === "toutes" || e.categorie === categorie) &&
        (!motif || sansAccents(`${e.titre} ${e.source}`).includes(motif)),
    );
  }, [liste, texte, categorie]);

  if (etatCatalogue.loading && !etatCatalogue.data) return <p className="sec">Chargement du catalogue…</p>;
  if (etatCatalogue.error && !etatCatalogue.data) return <p className="erreur-saisie">{etatCatalogue.error}</p>;
  if (!etatCatalogue.data?.disponible) {
    return (
      <p className="note">
        Catalogue indisponible : la collecte des faits datés (flux RSS de presse) n'est pas installée sur cette base.
        Saisir le fait à la main.
      </p>
    );
  }
  return (
    <>
      <label className="champ-recherche">
        Rechercher un fait
        <input type="search" value={texte} placeholder="grève, 49.3, carburant…" onChange={(e) => setTexte(e.target.value)} />
      </label>
      <div className="filtres" role="radiogroup" aria-label="Catégorie">
        {[{ valeur: "toutes", libelle: "Toutes" }, ...CATEGORIES_EVENEMENT].map((c) => (
          <label key={c.valeur} className="filtre">
            <input type="radio" name="categorie" value={c.valeur} checked={categorie === c.valeur} onChange={() => setCategorie(c.valeur)} />
            <span>{c.libelle}</span>
          </label>
        ))}
      </div>
      <p className="sec tnum">
        {fmtNombre(filtres.length)} fait{filtres.length > 1 ? "s" : ""} sur {fmtNombre(liste.length)}
        {filtres.length > RESULTATS_MAX ? ` · ${RESULTATS_MAX} premiers affichés` : ""}
      </p>
      <ul className="liste-faits">
        {filtres.slice(0, RESULTATS_MAX).map((e) => {
          const jour = jourParis(new Date(e.date));
          const hors = (minDate && jour < minDate) || jour > aujourdhui;
          return (
            <li key={e.id}>
              <button
                type="button"
                className="fait"
                aria-pressed={choisi === e.id}
                onClick={() => onChoisir(e)}
              >
                <span className="fait-date tnum">{dateCatalogue.format(new Date(e.date))}</span>
                <span className={`fait-categorie categorie-${e.categorie}`}>{LIBELLE_CATEGORIE[e.categorie] ?? e.categorie}</span>
                <span className="fait-titre">{e.titre}</span>
                <span className="fait-source">
                  {e.source}
                  {hors ? " · hors des données collectées" : ""}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );
}

function SaisieManuelle({ evenement, minDate, aujourdhui, onSaisir }) {
  return (
    <div className="champs-evenement">
      <label>
        Libellé du fait
        <input
          type="text"
          maxLength={LIBELLE_EVENEMENT_MAX}
          value={evenement.id ? "" : evenement.libelle}
          placeholder="ex. annonce d'une réforme"
          onChange={(e) => onSaisir({ libelle: e.target.value })}
        />
      </label>
      <label>
        Jour J
        <input
          type="date"
          min={minDate ?? undefined}
          max={aujourdhui}
          value={evenement.id ? "" : (evenement.date ?? "")}
          onChange={(e) => dateValide(e.target.value) && onSaisir({ date: e.target.value })}
        />
      </label>
      <label>
        Heure (facultative)
        <input
          type="time"
          value={evenement.id ? "" : (evenement.heure ?? "")}
          onChange={(e) => onSaisir({ heure: heureValide(e.target.value) ? e.target.value : null })}
        />
      </label>
    </div>
  );
}

// Tableau avant / après : valeurs reçues des deux réponses, côte à côte, sans écart calculé.
function AvantApres({ avant, apres, bornes }) {
  const colonnes = [
    ["avant", "Avant", `du ${bornes.avant.debut} au ${bornes.avant.fin}`, avant],
    ["apres", "Après", `du ${bornes.apres.debut} au ${bornes.apres.fin}`, apres],
  ];
  const valeur = (d, f) => (d ? f(d) : "…");
  const lignesCamp = (camp) => [
    ["contre", "Évaluations contre", (d) => fmtNombre(d.barre.camps[camp].contre)],
    ["pour", "Évaluations pour", (d) => fmtNombre(d.barre.camps[camp].pour)],
    ["indice", "Indice net", (d) => fmtSigne(d.barre.camps[camp].indice)],
  ];
  return (
    <table className="table-donnees table-avant-apres">
      <caption className="sr-only">Valeurs reçues pour les trois jours avant et les trois jours après le fait</caption>
      <thead>
        <tr>
          <th scope="col">Indicateur</th>
          {colonnes.map(([k, titre, dates]) => (
            <th scope="col" key={k}>
              {titre}
              <span className="sous-entete">{dates}</span>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        <tr>
          <th scope="row">Posts scorés</th>
          {colonnes.map(([k, , , d]) => (
            <td key={k}>{valeur(d, (x) => fmtNombre(x.pipeline.posts))}</td>
          ))}
        </tr>
        {Object.keys(CAMPS).map((camp) => [
          <tr key={camp} className="ligne-groupe">
            <th scope="colgroup" colSpan={3}>
              <EtiquetteCamp camp={camp} />
            </th>
          </tr>,
          ...lignesCamp(camp).map(([cle, libelle, f]) => (
            <tr key={`${camp}-${cle}`}>
              <th scope="row">{libelle}</th>
              {colonnes.map(([k, , , d]) => (
                <td key={k}>{valeur(d, f)}</td>
              ))}
            </tr>
          )),
        ])}
      </tbody>
    </table>
  );
}

export function Evenement({ etat, onEtat, minDate }) {
  const { evenement, seuil } = etat;
  const aujourdhui = jourParis(new Date());
  const catalogue = useContractData({ endpoint: "api/evenements", schema: SCHEMA_EVENEMENTS, pollMs: POLL_LONG_MS });
  const jour = evenement.date && evenement.date <= aujourdhui ? evenement.date : null;
  const bornes = jour ? plages(jour, aujourdhui) : null;
  const adresses = bornes
    ? {
        fenetre: adresse(bornes.fenetre.debut, bornes.fenetre.fin, seuil),
        avant: adresse(bornes.avant.debut, bornes.avant.fin, seuil),
        apres: adresse(bornes.apres.debut, bornes.apres.fin, seuil),
      }
    : { fenetre: null, avant: null, apres: null };
  const fenetre = useContractData({ endpoint: adresses.fenetre, schema: SCHEMA_VERSION, pollMs: POLL_LONG_MS });
  const avant = useContractData({ endpoint: adresses.avant, schema: SCHEMA_VERSION, pollMs: POLL_LONG_MS });
  const apres = useContractData({ endpoint: adresses.apres, schema: SCHEMA_VERSION, pollMs: POLL_LONG_MS });
  // Une réponse ne compte que si elle vient des dates actuelles (changement de fait en cours).
  const recu = (r, k) => (adresses[k] && r.url === adresses[k] ? r.data : null);
  const dFenetre = recu(fenetre, "fenetre");

  const fait = evenement.id ? (catalogue.data?.evenements ?? []).find((e) => e.id === evenement.id) : null;
  const choisir = (e) => {
    const d = new Date(e.date);
    onEtat((s) => ({ ...s, evenement: { id: e.id, libelle: e.titre, date: jourParis(d), heure: heureParis(d) } }));
  };
  const saisir = (partiel) =>
    onEtat((s) => {
      const base = s.evenement.id ? { id: null, libelle: "", date: null, heure: null } : s.evenement;
      return { ...s, evenement: { ...base, ...partiel, id: null } };
    });

  const avantTronque = minDate && bornes && bornes.avant.debut < minDate;
  const apresTronque = bornes && bornes.apres.fin < decalerJour(jour, JOURS_AUTOUR - 1);
  // Dernier micro-lot reçu : au-delà, la base n'a plus rien (flux arrêté).
  const finDonnees = dFenetre?.etat?.derniere_maj ? jourParis(new Date(dFenetre.etat.derniere_maj)) : null;
  const apresSansDonnees = bornes && finDonnees && finDonnees < bornes.apres.fin;

  return (
    <>
      <div className="evenement-choix">
        <section className="bloc" aria-labelledby="t-evt-catalogue">
          <h3 id="t-evt-catalogue">Chercher un fait</h3>
          <Catalogue etatCatalogue={catalogue} choisi={evenement.id} minDate={minDate} aujourdhui={aujourdhui} onChoisir={choisir} />
        </section>
        <section className="bloc" aria-labelledby="t-evt-saisie">
          <h3 id="t-evt-saisie">Ou le saisir à la main</h3>
          <SaisieManuelle evenement={evenement} minDate={minDate} aujourdhui={aujourdhui} onSaisir={saisir} />
          <p className="note">
            Sans heure, le jour entier est marqué. Le jour J compte dans « après » : la page découpe par jours de Paris.
          </p>
        </section>
      </div>

      {!jour ? (
        <section className="etat" aria-live="polite">
          <h3>Aucun fait choisi</h3>
          <p>Choisir un fait dans le catalogue, ou saisir son jour : la page isole les trois jours avant et les trois jours après.</p>
        </section>
      ) : (
        <section className="section" aria-labelledby="t-evt-reaction">
          <header className="fait-entete">
            <p className="fait-surtitre">
              {fait ? `${LIBELLE_CATEGORIE[fait.categorie] ?? fait.categorie} · ${fait.source}` : "Fait saisi à la main"}
            </p>
            <h3 id="t-evt-reaction">{evenement.libelle || "Fait sans libellé"}</h3>
            <p className="sec">
              {dateLongue.format(new Date(`${jour}T12:00:00Z`))}
              {evenement.heure ? `, ${evenement.heure} (heure de Paris)` : ""}
              {fait?.lien && (
                <>
                  {" · "}
                  <a href={fait.lien} rel="noreferrer noopener" target="_blank">
                    lire l'article
                  </a>
                </>
              )}
            </p>
          </header>

          <h4>Réaction autour du fait, de J−{JOURS_AUTOUR} à J+{JOURS_AUTOUR}</h4>
          {!dFenetre ? (
            fenetre.error ? <p className="erreur-saisie">{fenetre.error}</p> : <Chargement />
          ) : dFenetre.etat.base_vide || dFenetre.etat.periode_vide ? (
            <p className="note">
              Aucune donnée dans cette semaine{minDate ? ` : la base commence le ${minDate}` : ""}. Choisir un fait plus récent.
            </p>
          ) : (
            <>
              <ChronologieEvenement donnees={dFenetre} jour={jour} heure={evenement.heure} />
              <TableChronologie donnees={dFenetre} libelleTranche={(t) => libelleTranche(t, dFenetre.periode.pas_min)} />
            </>
          )}

          <h4 className="titre-avant-apres">Avant et après : trois jours de chaque côté</h4>
          <AvantApres avant={recu(avant, "avant")} apres={recu(apres, "apres")} bornes={bornes} />
          {(avantTronque || apresTronque || apresSansDonnees) && (
            <p className="note">
              {avantTronque ? `La base commence le ${minDate} : « avant » compte moins de trois jours de données. ` : ""}
              {apresTronque ? "« Après » s'arrête aujourd'hui : il compte moins de trois jours. " : ""}
              {apresSansDonnees ? `La base s'arrête le ${finDonnees} : « après » compte moins de trois jours de données. ` : ""}
              Comparer alors les indices, pas les nombres.
            </p>
          )}
          {[avant, apres].some((r) => r.error) && <p className="erreur-saisie">{avant.error ?? apres.error}</p>}
          <p className="note">
            Un écart entre avant et après ne prouve pas que ce fait en est la cause : d'autres faits ont pu arriver la même
            semaine, et les posts Bluesky ne représentent pas l'électorat. Mesure non représentative, ce n'est pas un sondage.
          </p>
        </section>
      )}
    </>
  );
}
