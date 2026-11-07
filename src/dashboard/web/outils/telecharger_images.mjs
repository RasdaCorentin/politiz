// Télécharge, au build Docker, les miniatures LIBRES des candidats listées dans
// images/candidats-images.json, et écrit le manifeste lu par la page.
//
// Pourquoi au build : la page reste sur sa propre origine (CSP `img-src 'self'`), le navigateur
// du visiteur ne contacte jamais Wikimedia, et la démonstration marche hors ligne. Le dépôt ne
// contient aucune image : seulement les métadonnées (auteur, licence, lien).
//
// Une miniature absente (réseau coupé, fichier déplacé) ne fait pas échouer le build : la page
// affiche alors les initiales. Une image dont `etat` n'est pas `libre` n'est jamais téléchargée.
//
// Usage : node outils/telecharger_images.mjs <candidats-images.json> <dossier de sortie>
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

const [source, sortie] = process.argv.slice(2);
if (!source || !sortie) {
  console.error("usage : node telecharger_images.mjs <candidats-images.json> <dossier>");
  process.exit(2);
}

// Politique de Wikimedia : un User-Agent qui dit qui appelle.
const UA = "sae-data-dashboard/1.0 (projet etudiant; build Docker du tableau de bord)";
const DELAI_MS = 15_000;
const TAILLE_MAX = 2_000_000;

// Types acceptés et leur extension.
const EXTENSIONS = { "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp" };
// Nom de fichier stable et sûr : « le pen » -> « le-pen.jpg » (accents retirés après NFD).
const fichierDe = (id, ext) =>
  `${id.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}.${ext}`;

async function telecharger(url) {
  const propre = url.split("?")[0]; // sans les paramètres de suivi (utm_*)
  const res = await fetch(propre, { headers: { "User-Agent": UA }, signal: AbortSignal.timeout(DELAI_MS) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const type = (res.headers.get("content-type") ?? "").split(";")[0].trim();
  const ext = EXTENSIONS[type];
  if (!ext) throw new Error(`type ${type}`);
  const octets = Buffer.from(await res.arrayBuffer());
  if (octets.length > TAILLE_MAX) throw new Error(`${octets.length} octets`);
  return { octets, ext };
}

const { candidats } = JSON.parse(await readFile(source, "utf8"));
await mkdir(sortie, { recursive: true });

const manifeste = {};
let absentes = 0;
for (const c of candidats) {
  const img = c.image;
  if (!img || img.etat !== "libre" || !img.miniature_url) continue;
  try {
    const { octets, ext } = await telecharger(img.miniature_url);
    const fichier = fichierDe(c.id, ext);
    await writeFile(join(sortie, fichier), octets);
    manifeste[c.id] = {
      fichier,
      nom: c.nom ?? c.id,
      auteur: img.auteur ?? null,
      licence: img.licence ?? null,
      licence_url: img.licence_url ?? null,
      page_commons: img.page_commons ?? null,
    };
  } catch (err) {
    absentes += 1;
    console.warn(`image absente pour « ${c.id} » : ${err.message}`);
  }
}

await writeFile(join(sortie, "index.json"), JSON.stringify({ schema: "images-candidats v1", images: manifeste }, null, 1));
console.log(`images de candidats : ${Object.keys(manifeste).length} téléchargées, ${absentes} absentes`);
