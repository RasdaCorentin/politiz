# Bibliothèque d'opinion politique (lexique et regex)

Ressource de données partagée. Deux usages : l'étape « règles » avant le modèle (inférence en
flux) et la pré-annotation. Méthode, chiffres et limites : [`docs/technique/lexique-regex.md`](../../docs/technique/lexique-regex.md).

## Fichiers

| Fichier | Contenu |
| --- | --- |
| `entites.yaml` | alias → entité canonique (candidat ou parti), nom d'usage, camp, drapeau `ambigu` |
| `stance.yaml` | marqueurs d'opinion → cible, stance, confiance, motif regex, exemples inventés |
| `themes.yaml` | termes → thème |
| `emotions.yaml` | quelques émojis et mots d'émotion fiables (volontairement court) |
| `adjectifs.yaml` | lexique fermé de 200 adjectifs évaluatifs, avec leurs formes fléchies : seuls ces mots sont comptés par cible et stance (table `adjectifs_fenetre`) |

## Règles de format

- Tout est **normalisé** : minuscules, sans accents (comme `normalize()` de `src/ingestion/ingestion.py`).
  Les motifs s'appliquent au texte normalisé, après retrait des `@handles`.
- `confiance` : `haute` (la règle peut décider seule), `moyenne` (à confirmer), `basse` (indice pour le modèle).
- `freq` : nombre de posts du corpus du 2026-10-12 (3151 posts) où le motif se déclenche.
- `precision_lue` : hits bien classés sur hits lus à la main (échantillon petit, ordre de grandeur).
- Les exemples sont **inventés**. Aucun post réel n'est stocké ici.

### `entites.yaml`

```yaml
- id: melenchon            # nom canonique = premier alias de keywords.txt
  type: candidat           # candidat | parti
  nom: "Jean-Luc Mélenchon" # nom d'usage affiché (avec accents)
  camp: gauche             # gauche | centre | droite | null (aucune source solide ou non partisan)
  alias:
    - {forme: "meluche", ambigu: false, dans_keywords: true, freq: 32}
```

`camp` : rattachement de la personne publique d'après sa formation actuelle. Règle, sources et cas litigieux : [`camps-candidats.md`](../../docs/technique/camps-candidats.md). Il ne qualifie jamais l'opinion d'un internaute.

`ambigu: true` : l'alias a un autre sens courant (`lr`, `bertrand`, `modem`…). Il ne suffit pas à fixer une cible.

### `stance.yaml`

```yaml
- id: rejet-jamais-voter
  cible: entite_capturee   # entite_capturee | co_mentionnee | camp | groupe-politique | <id d'entité>
  stance: contre           # pour | contre | neutre | mention | ambigu
  confiance: haute         # haute | moyenne | basse
  motif: "...(?P<cible>{ENTITE})\\b"
  exemples: {positifs: [...], negatifs: [...]}
  limites: [...]
```

- `{ENTITE}` est remplacé au chargement par tous les alias de `entites.yaml`.
- `entite_capturee` : le groupe nommé `cible` donne l'alias, donc l'entité.
- `co_mentionnee` : la cible est toute entité citée dans le post.
- `camp` : la cible est un camp (champ `camp_vise`), pas une entité. L'étiquette finale est `groupe-politique`.
- `mention` : cité sans jugement (sondage, fait, agenda). `neutre` : jugement équilibré, sans règle. Refuser son soutien = `contre`.
- Personne et parti sont distincts : `le pen` ≠ `rassemblement national`.

### `themes.yaml`, `emotions.yaml`

Valeurs autorisées : `themes` = economie, social-retraites, immigration, securite, ecologie,
europe-international, institutions, sante-education, campagne-sondages (`autre` = résiduel, sans terme) ;
`emotion` = joie, colere, peur, tristesse, surprise, degout, neutre.

## Charger et vérifier

```bash
uv run --with pyyaml --with pytest pytest tests/test_analyse_lexique.py
uv run --with pyyaml python scripts/analyse_lexique.py --db CORPUS.db --sections regles
```

`load_lexique()` dans `scripts/analyse_lexique.py` valide le schéma et lève `LexiqueError` au premier défaut.

### `adjectifs.yaml`

```yaml
- {adjectif: "dangereux", origine: corpus, formes: [dangereuse, dangereuses, dangereux]}
- {adjectif: "juste", origine: corpus, formes: [juste, justes], ambigu: true, raison: "adverbe (« c'est juste nul »)"}
```

- `adjectif` : forme affichée (masculin singulier, avec accents). C'est la valeur écrite dans
  `adjectifs_fenetre.adjectif`.
- `formes` : formes cherchées dans le texte normalisé, en mots entiers (masculin, féminin,
  singulier, pluriel ; minuscules sans accents). Une forme appartient à un seul adjectif.
- `origine` : `corpus` (48 adjectifs vus dans au moins 5 posts du corpus silver, comptage hors ligne de
  `src/training/adjectifs/`) ou `lexique` (152 adjectifs évaluatifs courants ajoutés à la main).
- `ambigu: true` : le mot sert souvent de nom, d'adverbe, de verbe ou d'interjection (`raison`).
  Le scoreur l'ignore : sans analyse grammaticale, il compterait « juste » dans « c'est juste nul ».
- **Participes.** Sans accents, le masculin singulier d'un participe est aussi une forme du verbe
  (« complique », « engage ») : seules les autres formes sont cherchées. « risques » et
  « equilibres » (noms courants) ne le sont pas non plus.
- **Pourquoi un lexique fermé.** Un mot hors liste n'atteint jamais ClickHouse ni l'écran : aucun mot
  rare, donc proche d'un post précis, ne sort du job (slide 5).
- Limites : pas de lien grammatical entre l'adjectif et la cible (tous les adjectifs d'un post
  vont à chacune de ses cibles) ; un adjectif nié (« pas sérieux ») compte comme l'adjectif.
