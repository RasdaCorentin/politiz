// Page de restitution : routage par `vue`, état de l'URL, lecture du contrat `tableau` v4 (hook).
// La coquille (Shell) porte la navigation et le bandeau ; chaque page est un fichier de pages/.
import { useEffect, useState } from "react";
import { useContractData } from "./hooks/useContractData.js";
import { PAGE_DEFAUT, PAGES, POLL_24H_MS, POLL_LONG_MS, SCHEMA_VERSION } from "./constantes.js";
import { construireQuery, lireUrl } from "./lib/url.js";
import { jourParis } from "./lib/dates.js";
import { Shell } from "./components/Shell.jsx";
import { Chargement, EtatBloquant, EtatVide } from "./components/Etats.jsx";
import { Contraste } from "./pages/Contraste.jsx";
import { Popularite } from "./pages/Popularite.jsx";
import { Top3 } from "./pages/Top3.jsx";
import { Evenement } from "./pages/Evenement.jsx";

const PAGES_RENDUES = { contraste: Contraste, popularite: Popularite, top3: Top3 };

export default function App() {
  const [etat, setEtat] = useState(lireUrl);
  const { periode, debut, fin, seuil } = etat;
  const requete = debut && fin ? `debut=${debut}&fin=${fin}` : `periode=${periode}`;
  const endpoint = `api/tableau?${requete}${seuil ? `&seuil=${seuil}` : ""}`;
  // Pas de polling 24 h : 60 s ; au-delà, 5 min (le hook garde ETag/304 et la pause onglet caché).
  const pollMs = periode === "24h" ? POLL_24H_MS : POLL_LONG_MS;
  const { data, generatedAt, loading, error, refresh } = useContractData({ endpoint, schema: SCHEMA_VERSION, pollMs });

  // L'URL porte l'état : rechargement et signet sans perte.
  useEffect(() => {
    try {
      history.replaceState(null, "", `?${construireQuery(etat)}`);
    } catch {
      // Historique indisponible : l'état reste en mémoire.
    }
  }, [etat]);

  // Ce que la page sait de la lecture : les données du contrat, avec l'heure de lecture à jour.
  const donnees = data ? { ...data, generated_at: generatedAt ?? data.generated_at } : null;
  const page = PAGES.find((p) => p.valeur === etat.vue) ?? PAGES.find((p) => p.valeur === PAGE_DEFAUT);
  const Page = PAGES_RENDUES[page.valeur];
  const minDate = donnees?.periode?.premiere_donnee ? jourParis(new Date(donnees.periode.premiere_donnee)) : null;

  let corps;
  if (page.valeur === "evenement") {
    // La page événement a ses propres appels, un par plage : les états de la période générale ne la concernent pas.
    corps = <Evenement etat={etat} onEtat={setEtat} minDate={minDate} />;
  } else if (!donnees && loading) {
    corps = <Chargement />;
  } else if (!donnees) {
    corps = (
      <EtatBloquant titre="Données indisponibles" onReessayer={refresh}>
        <p>{error}</p>
      </EtatBloquant>
    );
  } else if (donnees.etat.base_vide) {
    corps = (
      <EtatVide titre="Aucune donnée dans la base">
        <p>Le flux n'a pas encore écrit. Démarrer le producteur et le job Spark, puis attendre le premier micro-lot (environ une minute).</p>
      </EtatVide>
    );
  } else if (donnees.etat.periode_vide) {
    corps = (
      <EtatVide
        titre="Aucune donnée sur cette période"
        action={
          periode !== "24h" ? (
            <button
              type="button"
              className="bouton secondaire"
              onClick={() => setEtat((e) => ({ ...e, periode: "24h", debut: null, fin: null }))}
            >
              Afficher 24 h
            </button>
          ) : null
        }
      >
        <p>Choisir une période plus longue ou attendre le prochain micro-lot.</p>
      </EtatVide>
    );
  } else {
    corps = <Page data={donnees} etat={etat} onEtat={setEtat} />;
  }

  return (
    <Shell
      etat={etat}
      page={page}
      donnees={donnees}
      erreur={error}
      onNavigation={(v) => setEtat((e) => ({ ...e, vue: v }))}
      onPeriode={(p) => setEtat((e) => ({ ...e, periode: p, debut: null, fin: null }))}
    >
      {corps}
    </Shell>
  );
}
