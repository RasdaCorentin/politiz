// Couche données : lit le JSON `tableau` (format du contrat) et le remet à la page.
// Le hook connaît le contrat (schema_version, generated_at, paramètres d'URL), pas le domaine :
// App.jsx décide de l'affichage.
//
// Règles appliquées ici :
//  - interrogation à `pollMs` (la page choisit), seulement onglet visible ; au retour sur l'onglet,
//    une requête seulement si l'intervalle est écoulé ;
//  - If-None-Match : une base inchangée répond 304, la page ne reparse rien ;
//  - les données précédentes restent à l'écran pendant un rafraîchissement et en cas d'erreur.
import { useCallback, useEffect, useRef, useState } from "react";

// Affiche l'état « mise à jour » seulement si la requête dure : un aller-retour rapide ne clignote pas.
const RAFRAICHISSEMENT_DELAI_MS = 400;

export class ContractError extends Error {}

// Traduit un code HTTP en phrase qui dit quel service vérifier.
async function erreurHttp(res) {
  if (res.status === 502 || res.status === 504) {
    return "le service dashboard-api ne répond pas (vérifier le conteneur dashboard-api).";
  }
  if (res.status === 503) {
    return "la base ClickHouse est injoignable (vérifier le conteneur clickhouse).";
  }
  if (res.status === 400) {
    try {
      const corps = await res.json();
      if (corps.erreur) return `paramètre refusé : ${corps.erreur}`;
    } catch {
      // Corps non JSON : message générique ci-dessous.
    }
  }
  return `réponse HTTP ${res.status}.`;
}

/**
 * @param {object} opts
 * @param {string|null} opts.endpoint  route relative avec ses paramètres (« api/tableau?periode=7j »), ou null : hook inactif.
 * @param {number} opts.schema    `schema_version` que cette page comprend.
 * @param {number} opts.pollMs    période d'interrogation, 0 = aucune.
 * @returns {{data, generatedAt, loading, refreshing, error, url, refresh}}  url : adresse qui a produit `data`
 *          (elle diffère de `endpoint` pendant un changement d'adresse ou après une erreur).
 */
export function useContractData({ endpoint, schema, pollMs }) {
  const [state, setState] = useState({ data: null, generatedAt: null, loading: true, refreshing: false, error: null, url: null });
  // ETag gardé avec l'URL qui l'a produit : un changement de période ne reçoit jamais un 304.
  const cache = useRef({ url: null, etag: null });
  const controleur = useRef(null);
  const derniereRequete = useRef(0);
  const opts = useRef({ endpoint, schema });
  opts.current = { endpoint, schema };

  const refresh = useCallback(async (force = false) => {
    if (controleur.current && !force) return;
    controleur.current?.abort();
    const ctrl = new AbortController();
    controleur.current = ctrl;
    derniereRequete.current = Date.now();
    const lent = setTimeout(() => setState((s) => ({ ...s, refreshing: !s.loading })), RAFRAICHISSEMENT_DELAI_MS);
    try {
      const { endpoint, schema } = opts.current;
      const entetes = cache.current.url === endpoint && cache.current.etag ? { "If-None-Match": cache.current.etag } : {};
      const res = await fetch(endpoint, { headers: entetes, signal: ctrl.signal });

      if (res.status === 304) {
        // Rien n'a changé : on garde le même objet. L'heure de lecture avance (badge de fraîcheur).
        const stamp = res.headers.get("X-Generated-At");
        setState((s) => ({ ...s, generatedAt: stamp ?? s.generatedAt, loading: false, refreshing: false, error: null }));
        return;
      }
      if (!res.ok) throw new ContractError(await erreurHttp(res));

      const payload = await res.json();
      if (payload.schema_version !== schema) {
        throw new ContractError(`format v${payload.schema_version} non pris en charge (attendu : v${schema}).`);
      }
      cache.current = { url: endpoint, etag: res.headers.get("ETag") };
      setState({
        data: Object.freeze(payload),
        generatedAt: payload.generated_at ?? null,
        loading: false,
        refreshing: false,
        error: null,
        url: endpoint,
      });
    } catch (err) {
      if (ctrl.signal.aborted) return; // requête remplacée par une autre période
      const message = err instanceof ContractError ? err.message : "réseau indisponible.";
      // Les données déjà chargées restent : des chiffres périmés valent mieux qu'une page vide.
      setState((s) => ({ ...s, loading: false, refreshing: false, error: `Impossible de charger les données : ${message}` }));
    } finally {
      clearTimeout(lent);
      if (controleur.current === ctrl) controleur.current = null;
    }
  }, []);

  useEffect(() => {
    // Pas d'adresse (plage non saisie) : aucun appel, et la requête en cours est annulée.
    if (!endpoint) {
      controleur.current?.abort();
      return undefined;
    }
    refresh(true);
    const tick = pollMs > 0 ? setInterval(() => document.visibilityState === "visible" && refresh(), pollMs) : null;
    // Retour sur l'onglet : on ne refait la requête que si l'intervalle est écoulé.
    const auRetour = () => {
      if (document.visibilityState === "visible" && Date.now() - derniereRequete.current >= pollMs) refresh();
    };
    document.addEventListener("visibilitychange", auRetour);
    return () => {
      clearInterval(tick);
      document.removeEventListener("visibilitychange", auRetour);
    };
  }, [endpoint, pollMs, refresh]);

  // Sans adresse : rien à lire, donc rien à afficher ni à signaler.
  if (!endpoint) return { data: null, generatedAt: null, loading: false, refreshing: false, error: null, url: null, refresh: () => {} };
  return { ...state, refresh: () => refresh(true) };
}
