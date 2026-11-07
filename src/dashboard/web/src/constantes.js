// Constantes de l'interface : version du contrat, périodes, pages, camps, émotions et tons.
// Aucune donnée ici : des libellés et des bornes.

export const SCHEMA_VERSION = 4;
export const SCHEMA_EVENEMENTS = 1; // catalogue `GET api/evenements`

// Une opinion sur plusieurs jours ne bouge pas à la minute : 60 s seulement sur 24 h.
export const POLL_24H_MS = 60_000;
export const POLL_LONG_MS = 300_000;

// `court` : libellé du sélecteur compact de l'en-tête ; `libelle` : nom complet (lecteur d'écran, infobulle).
export const PERIODES = [
  { valeur: "24h", libelle: "24 heures", court: "24 h" },
  { valeur: "7j", libelle: "7 jours", court: "7 j" },
  { valeur: "30j", libelle: "30 jours", court: "30 j" },
  { valeur: "tout", libelle: "Depuis le début", court: "Tout" },
];
export const PERIODE_DEFAUT = "7j";

export const SEUIL_MIN = 1;
export const SEUIL_MAX = 10_000;

export const CAMPS = { gauche: "Gauche", centre: "Centre", droite: "Droite" };

export const EMOTIONS = [
  ["joie", "Joie"],
  ["colere", "Colère"],
  ["peur", "Peur"],
  ["tristesse", "Tristesse"],
  ["surprise", "Surprise"],
  ["degout", "Dégoût"],
  ["neutre", "Neutre"],
];
export const LIBELLE_EMOTION = Object.fromEntries(EMOTIONS);

// Ton : clé du contrat, libellé, classe de fond (jetons de style.css).
export const TONS = [
  ["positif", "Positif", "fond-ton-positif"],
  ["neutre", "Neutre", "fond-ton-neutre"],
  ["negatif", "Négatif", "fond-ton-negatif"],
];

export const PAGES = [
  {
    valeur: "contraste",
    libelle: "Contraste",
    titre: "Ton des posts",
    intro: "Positif, négatif et neutre, émotions, délai de traitement.",
  },
  {
    valeur: "popularite",
    libelle: "Popularité",
    titre: "Popularité",
    intro: "Barre d'opinion gauche et droite, puis cote des candidats et des partis.",
  },
  {
    valeur: "top3",
    libelle: "Top 3",
    titre: "Top 3 : thèmes, adjectifs et émotions",
    intro: "Les trois premiers de la cote. La surface d'une bulle suit son nombre de posts.",
  },
  {
    valeur: "evenement",
    libelle: "Événement",
    titre: "Événement : la réaction dans la semaine",
    intro: "Choisir un fait daté : la page isole les trois jours avant et les trois jours après, camp par camp.",
  },
];
export const PAGE_DEFAUT = "contraste";

// Cible de la cote : candidats ou partis (paramètre d'URL `cible`).
export const CIBLES = [
  { valeur: "candidats", libelle: "Candidats" },
  { valeur: "partis", libelle: "Partis" },
];
export const CIBLE_DEFAUT = "candidats";

export const TITRE_APP = "Présidentielle 2027 : sentiments des discussions";
export const MENTION_M10 = "Mesure non représentative, ce n'est pas un sondage.";

// Catégories du catalogue d'événements (contrat `evenements` v1), dans l'ordre des filtres.
export const CATEGORIES_EVENEMENT = [
  { valeur: "manifestation", libelle: "Manifestation" },
  { valeur: "loi", libelle: "Loi" },
  { valeur: "prix", libelle: "Prix" },
  { valeur: "bourse", libelle: "Bourse" },
  { valeur: "greve", libelle: "Grève" },
  { valeur: "autre", libelle: "Autre" },
];
export const LIBELLE_CATEGORIE = Object.fromEntries(CATEGORIES_EVENEMENT.map((c) => [c.valeur, c.libelle]));
// Fenêtre isolée autour d'un fait : trois jours de Paris de chaque côté du jour J.
export const JOURS_AUTOUR = 3;
