# Camps des candidats

## 1. Objet

Le Livrable 1 annonce que « chaque candidat est rattaché à un camp, selon une table publique et documentée ». Le dashboard colore les candidats en rouge (gauche), gris (centre) et bleu (droite) ([`contrats-poc.md`](contrats-poc.md), contrat du dashboard). Ce document est la table : pour chacune des 68 entités de [`entites.yaml`](../../ressources/lexique/entites.yaml), la formation d'appartenance, le camp et les sources.

**État au 14/10/2026.** Toutes les sources ont été consultées ce jour. Le rattachement est une **proposition** de l'équipe technique : l'équipe la valide, en particulier les cas de la section « Cas litigieux ».

Résultat : 28 entités à gauche, 10 au centre, 22 à droite, 8 sans camp (`null`).

## 2. Méthode et règle de décision

**Sources.** Seules les sources ouvertes lues le jour de la consultation sont citées (« Registre des sources », dans « Contester ou mettre à jour ») : articles de Wikipédia en français (position des partis et appartenance des personnes, avec leurs références), nuances du ministère de l'Intérieur lorsqu'un article les mentionne. Le Chapel Hill Expert Survey (CHES 2024) et le Manifesto Project n'ont pas été exploités : leurs fichiers de données n'ont pas été lus. Aucune affiliation n'est tirée de la mémoire de l'agent.

**Règle (appliquée partout).**

1. **Le camp est celui de la formation d'appartenance actuelle.** Une personne prend le camp de son parti, même si elle l'a rejoint récemment : une personne en transition de parti suit le parti d'aujourd'hui, pas celui d'hier (ex. Valls : Renaissance, pas PS).
2. **Une personne sans parti** prend le camp qu'elle revendique elle-même, seulement si une source lue le rapporte. Sinon `null`.
3. **Un parti** prend le camp que la source ouverte lui attribue (infobox ou introduction, nuance du ministère). Si elle donne une fourchette (du centre gauche à la gauche), le camp est le côté de l'axe où le parti se range lui-même dans ses alliances.
4. **`gauche`** couvre le centre gauche, la gauche radicale et l'extrême gauche. **`droite`** couvre le centre droit conservateur (LR), la droite radicale et l'extrême droite. L'intensité (« extrême ») figure dans la colonne remarque : le dashboard n'a que trois couleurs.
5. **`centre`** recouvre les formations de la coalition présidentielle (Renaissance, Horizons, MoDem) que le ministère classe au centre, y compris leurs personnalités ex-PS ou ex-LR. Le centre n'est pas une moyenne gauche-droite.
6. **`null`** : parti qui se déclare hors du clivage (UPR), parti transpartisan (animaliste), personnalité non partisane, ou aucune source lue.
7. **Parti et personne sont distincts** ([`lexique-regex.md`](lexique-regex.md)) : chaque entité a sa ligne, et une ligne ne se déduit pas d'une autre sans règle 1.
8. **Le camp désigne la personne publique d'après ses déclarations et sa formation**, jamais l'opinion qu'un internaute exprime sur elle (voir « Limites et point juridique »).

## 3. Table des entités

Les clés `id` sont celles de `entites.yaml`. Les sources renvoient au « Registre des sources ».

| id | nom | formation | camp | sources | remarque |
| --- | --- | --- | --- | --- | --- |
| `le pen` | Marine Le Pen | Rassemblement national (RN) | droite | W1, W2 | Extrême droite (repliée sur « droite »). L'alias vise aussi Jean-Marie et Marion Maréchal Le Pen, même camp. |
| `bardella` | Jordan Bardella | Rassemblement national (président) | droite | W3, W2 | Extrême droite. |
| `melenchon` | Jean-Luc Mélenchon | La France insoumise (LFI) | gauche | W4, W5 | Gauche radicale, parfois classée extrême gauche. |
| `glucksmann` | Raphaël Glucksmann | Place publique, désigné par la primaire socialiste du 11/10/2026 | gauche | W6, W7 | Centre gauche à gauche selon les sources. |
| `edouard philippe` | Édouard Philippe | Horizons | centre | W8, W9 | Wikipédia : centre droit, « aile droite de la majorité présidentielle » ; nuance du ministère : centre. Litigieux (voir « Cas litigieux »). |
| `attal` | Gabriel Attal | Renaissance (secrétaire général) | centre | W10 | Discours à « marqueurs traditionnels de la droite » (Wikipédia). |
| `retailleau` | Bruno Retailleau | Les Républicains (président), candidat désigné le 19/04/2026 | droite | W11, W12 | Droite conservatrice et libérale. |
| `roussel` | Fabien Roussel | Parti communiste français (secrétaire national), candidat désigné le 06/09/2026 | gauche | W13, W14 | Gauche radicale. |
| `ruffin` | François Ruffin | Debout ! (président), groupe EcoS | gauche | W15 | Se dit social-démocrate ; candidat à la primaire de la gauche (26/01/2026). |
| `zemmour` | Éric Zemmour | Reconquête (président) | droite | W16, W17 | Extrême droite ; candidature annoncée en septembre 2026. |
| `tondelier` | Marine Tondelier | Les Écologistes (secrétaire nationale) | gauche | W18, W19 | Candidature à confirmer après l'échec de la primaire de gauche (juillet 2026). |
| `batho` | Delphine Batho | Génération écologie (présidente) | gauche | W20, W21 | Écologie intégrale : elle récuse l'axe gauche-droite (« terriens » contre « destructeurs »). Ex-PS, élue sous l'étiquette NFP. Litigieux (voir « Cas litigieux »). |
| `lisnard` | David Lisnard | Nouvelle Énergie (président) ; a quitté LR le 31/03/2026 | droite | W22 | Orientation économique libérale ; demande une primaire à droite. Le parti n'affiche aucun positionnement explicite. Litigieux (voir « Cas litigieux »). |
| `bertrand` | Xavier Bertrand | Nous France (parti associé à LR) ; LR selon Wikipédia | droite | W23, W24 | « Gaulliste social, droite sociale et populaire ». Fiche signalée pour contributions non déclarées. Litigieux (voir « Cas litigieux »). |
| `olivier faure` | Olivier Faure | Parti socialiste (premier secrétaire) | gauche | W25, W7 | Éliminé de la primaire socialiste (14,46 %), soutient Glucksmann. |
| `guedj` | Jérôme Guedj | Parti socialiste | gauche | W26 | Aile droite du PS, « gauche républicaine ». |
| `segolene royal` | Ségolène Royal | Parti socialiste (adhésion depuis 2024) | gauche | W27 | Troisième de la primaire socialiste de 2026. |
| `maurel` | Emmanuel Maurel | Gauche républicaine et socialiste (animateur national) | gauche | W28, W29 | Quatrième de la primaire socialiste (5,92 %). |
| `hollande` | François Hollande | Parti socialiste | gauche | W30 | Social-libéral depuis 2014 selon Wikipédia. |
| `villepin` | Dominique de Villepin | La France humaniste (fondée en 2025) | null | W31 | Gaulliste ; le parti n'affiche aucun positionnement gauche-droite dans la source lue. Litigieux (voir « Cas litigieux »). |
| `cazeneuve` | Bernard Cazeneuve | La Convention (quitte le PS en 2022) | gauche | W32 | Se réclame d'une « gauche sociale-démocrate, républicaine, humaniste et écologique » ; refuse LFI et RN ; hors primaire socialiste. Litigieux (voir « Cas litigieux »). |
| `bouamrane` | Karim Bouamrane | Parti socialiste ; mouvement La France humaine et forte | gauche | W33 | Critique des alliances PS-LFI. |
| `bruno le maire` | Bruno Le Maire | Renaissance (infobox) | centre | W34 | Ex-LR, famille néogaulliste, rallié à LREM en 2017. Litigieux (voir « Cas litigieux »). |
| `pecresse` | Valérie Pécresse | Soyons libres ; Les Républicains (depuis 2021) | droite | W35 | Droite libérale-conservatrice et europhile. |
| `ciotti` | Éric Ciotti | Union des droites pour la République (président) | droite | W36, W37 | Parti classé extrême droite, allié du RN. |
| `barnier` | Michel Barnier | Les Républicains | droite | W38, W12 | Gaulliste ; porte le projet de coalition « Bâtir ensemble ». |
| `darmanin` | Gérald Darmanin | Renaissance (texte) ; infobox sans parti en cours | centre | W39 | Soutient Édouard Philippe (août 2026). Étiqueté droitier par la presse ; la source lue ne donne que son parti. Litigieux (voir « Cas litigieux »). |
| `elisabeth borne` | Élisabeth Borne | Renaissance ; apparentée EPR ; « Bâtissons ensemble » (2026) | centre | W40 | Ex-PS, rallie Macron en 2017. |
| `braun-pivet` | Yaël Braun-Pivet | Renaissance (groupe EPR) | centre | W41 | Prône le dépassement des clivages. |
| `wauquiez` | Laurent Wauquiez | Les Républicains (président du groupe DR à l'Assemblée) | droite | W42, W12 | Favorable à une primaire à droite. |
| `autain` | Clémentine Autain | L'Après (cofondatrice) | gauche | W43 | Ex-LFI ; unitaire, « au service du NFP ». |
| `taubira` | Christiane Taubira | Walwari | gauche | W44 | Wikipédia : « pas très marquée à gauche » (2002) ; soutien à la primaire de gauche et à Mélenchon (2022), liste LFI (2024). Litigieux (voir « Cas litigieux »). |
| `poutou` | Philippe Poutou | NPA – L'Anticapitaliste | gauche | W45, W46 | Extrême gauche. Le NPA-A soutient Mélenchon en 2027. |
| `arthaud` | Nathalie Arthaud | Lutte ouvrière (porte-parole) | gauche | W47, W48 | Extrême gauche, trotskiste. |
| `asselineau` | François Asselineau | Union populaire républicaine (UPR) | null | W49 | Le parti se dit hors du clivage droite-gauche ; nuance « divers » du ministère ; la presse le situe à droite voire extrême droite. Litigieux (voir « Cas litigieux »). |
| `dupont-aignan` | Nicolas Dupont-Aignan | Debout la France (président) | droite | W50, W51 | Gaulliste souverainiste ; classé à droite, parfois extrême droite. Candidat officialisé le 19/09/2026. |
| `philippot` | Florian Philippot | Les Patriotes (président) | null | W52 | « Sociale-souverainiste », ex-Front national ; aucune source lue ne le classe à droite ou à gauche. Litigieux (voir « Cas litigieux »). |
| `thouy` | Hélène Thouy | Parti animaliste (coprésidente) | null | W53, W54 | Parti transpartisan. |
| `lassalle` | Jean Lassalle | Résistons ! (président) | null | W55 | Placé « entre le centre et le centre droit » par les médias, mais à une extrémité de l'axe selon une étude de 2017. Litigieux (voir « Cas litigieux »). |
| `aliot` | Louis Aliot | Rassemblement national (vice-président) | droite | W56 | Ligne nationale-populiste. |
| `knafo` | Sarah Knafo | Reconquête | droite | W57, W17 | Extrême droite. |
| `bellamy` | François-Xavier Bellamy | Les Républicains (vice-président) | droite | W58, W12 | Droite conservatrice. |
| `pradie` | Aurélien Pradié | Les Bâtisseurs (2025) ; non-inscrit ; ex-LR | droite | W59 | « Droite sociale », proche de Xavier Bertrand ; lié à Régions et peuples solidaires. Litigieux (voir « Cas litigieux »). |
| `hidalgo` | Anne Hidalgo | Parti socialiste | gauche | W60 | N'exerce plus de fonction élective depuis mars 2026. |
| `valls` | Manuel Valls | Renaissance (depuis 2021) ; ex-PS | centre | W61 | Courant rocardien et social-libéral du PS ; a quitté le PS en 2017. Litigieux (voir « Cas litigieux »). |
| `brossat` | Ian Brossat | Parti communiste français (porte-parole) | gauche | W62, W14 | Sénateur de Paris. |
| `bayrou` | François Bayrou | MoDem (président) | centre | W63, W64 | « S'ancre progressivement au centre ». |
| `tibo inshape` | Tibo InShape | Aucune (youtubeur, pas de parti) | null | W65 | Se dit « de droite » en 2024 comme chef d'entreprise, mais refuse de prendre parti et déclare « du bon et du mauvais dans chaque camp ». Litigieux (voir « Cas litigieux »). |
| `macron` | Emmanuel Macron | Renaissance | centre | à sourcer | Président de la République ; ne peut pas briguer un troisième mandat consécutif. |
| `sarkozy` | Nicolas Sarkozy | Les Républicains | droite | à sourcer | |
| `juppe` | Alain Juppé | Aucune (membre du Conseil constitutionnel) | null | à sourcer | Fonction non partisane. |
| `fabius` | Laurent Fabius | Parti socialiste (historique) | gauche | à sourcer | |
| `ayrault` | Jean-Marc Ayrault | Parti socialiste | gauche | à sourcer | |
| `castex` | Jean Castex | Aucune (PDG de la RATP) | null | à sourcer | Fonction non partisane. |
| `lecornu` | Sébastien Lecornu | Renaissance | centre | à sourcer | |
| `montebourg` | Arnaud Montebourg | Ex-Parti socialiste | gauche | à sourcer | |
| `duflot` | Cécile Duflot | Ex-EELV | gauche | à sourcer | |
| `jadot` | Yannick Jadot | Les Écologistes | gauche | à sourcer | |
| `piolle` | Éric Piolle | Les Écologistes | gauche | à sourcer | |
| `sandrine rousseau` | Sandrine Rousseau | Les Écologistes | gauche | à sourcer | |
| `clemence guette` | Clémence Guetté | La France insoumise | gauche | à sourcer | |
| `mathilde panot` | Mathilde Panot | La France insoumise | gauche | à sourcer | |
| `manon aubry` | Manon Aubry | La France insoumise | gauche | à sourcer | |
| `rima hassan` | Rima Hassan | La France insoumise | gauche | à sourcer | |
| `louis boyard` | Louis Boyard | La France insoumise | gauche | à sourcer | |
| `corbiere` | Alexis Corbière | Ex-LFI, groupe écologiste | gauche | à sourcer | |
| `vallaud` | Boris Vallaud | Parti socialiste | gauche | à sourcer | |
| `carole delga` | Carole Delga | Parti socialiste | gauche | à sourcer | |
| `rachida dati` | Rachida Dati | Les Républicains | droite | à sourcer | |
| `marion marechal` | Marion Maréchal | Identité-Libertés | droite | à sourcer | Extrême droite (repliée sur « droite »). |
| `aurore berge` | Aurore Bergé | Renaissance | centre | à sourcer | |
| `sebastien chenu` | Sébastien Chenu | Rassemblement national | droite | à sourcer | Extrême droite (repliée sur « droite »). |
| `larcher` | Gérard Larcher | Les Républicains | droite | à sourcer | |
| `ferrand` | Richard Ferrand | Aucune (président du Conseil constitutionnel) | null | à sourcer | Fonction non partisane. L'alias déclenche aussi sur « Clermont-Ferrand ». |
| `blanquer` | Jean-Michel Blanquer | Aucune | null | à sourcer | |
| `collomb` | Gérard Collomb | Aucune (mort en 2024) | null | à sourcer | |
| `sejourne` | Stéphane Séjourné | Renaissance (commissaire européen) | centre | à sourcer | |
| `rassemblement national` | Rassemblement national | Rassemblement national | droite | W2 | Extrême droite. |
| `lfi` | La France insoumise | La France insoumise | gauche | W5 | Gauche radicale. |
| `les republicains` | Les Républicains | Les Républicains | droite | W12 | Droite ; a quitté la coalition « socle commun » avec le premier gouvernement Lecornu. |
| `parti socialiste` | Parti socialiste | Parti socialiste | gauche | W7 | De la gauche au centre gauche. |
| `parti communiste` | Parti communiste français | Parti communiste français | gauche | W14 | Gauche radicale. |
| `place publique` | Place publique | Place publique | gauche | W6, W7 | Cofondé par Glucksmann ; membre du pôle socialiste de la primaire. |
| `generation ecologie` | Génération écologie | Génération écologie | gauche | W21 | Centre gauche selon Wikipédia. |
| `debout la france` | Debout la France | Debout la France | droite | W51 | Droite, parfois extrême droite. |
| `reconquete` | Reconquête | Reconquête | droite | W17 | Extrême droite. |
| `nouvelle energie` | Nouvelle Énergie | Nouvelle Énergie | droite | W22 | Parti de Lisnard ; aucun positionnement affiché dans la source lue. Litigieux (voir « Cas litigieux »). |
| `nous france` | Nous France | Nous France | droite | W24, W23 | Parti associé à LR ; « droite sociale ». |
| `modem` | MoDem | Mouvement démocrate | centre | W64 | Parti de centre. |
| `en marche` | Renaissance (ex-En Marche) | Renaissance | centre | W66 | Wikipédia : du centre gauche au centre droit, « centre-droit » en introduction ; nuance du ministère : REN. |
| `eelv` | Les Écologistes (ex-EELV) | Les Écologistes | gauche | W19 | Du centre gauche à la gauche radicale. |
| `grs` | Gauche républicaine et socialiste | GRS | gauche | W29 | Membre du NFP en 2024. |
| `npa` | NPA | NPA – L'Anticapitaliste et NPA – Révolutionnaires | gauche | W46 | Extrême gauche. Scission en 2024 en deux partis. |
| `lutte ouvriere` | Lutte ouvrière | Lutte ouvrière | gauche | W48 | Extrême gauche. |
| `upr` | Union populaire républicaine | UPR | null | W49 | Hors clivage droite-gauche selon le parti ; nuance « divers ». Litigieux (voir « Cas litigieux »). |
| `animaliste` | Parti animaliste | Parti animaliste | null | W54 | Se dit transpartisan. Litigieux (voir « Cas litigieux »). |
| `udr` | Union des droites pour la République | UDR | droite | W37 | Extrême droite, allié du RN. |
| `udi` | Union des démocrates et indépendants | UDI | centre | à sourcer | |
| `horizons` | Horizons | Horizons | centre | à sourcer | Le mot a un sens courant. |
| `nupes` | Nupes | Coalition de 2022 | gauche | à sourcer | |
| `nouveau front populaire` | Nouveau Front populaire | Coalition de 2024 | gauche | à sourcer | |
| `parti radical de gauche` | Parti radical de gauche | PRG | gauche | à sourcer | |
| `printemps republicain` | Printemps républicain | Printemps républicain | null | à sourcer | Positionnement contesté. |

## 4. Effets pour le pipeline

- Le champ `camp` de `entites.yaml` est la seule source du camp. Le dashboard n'en porte pas d'autre.
- Le rendu de `null` à l'écran reste à fixer dans le contrat du dashboard (`contrats-poc.md`, contrat du dashboard).
- Un score par camp agrège les scores des candidats du camp ; `null` n'entre dans aucun camp.

## 5. Cas litigieux

Chaque cas ci-dessous a une proposition et l'argument du camp opposé. La décision appartient à l'équipe. Le choix est repris dans `entites.yaml`.

### Édouard Philippe (`edouard philippe`)

Proposition : **centre**.

- Pour **centre** : Horizons est classé au centre par le ministère ; Philippe est dans la majorité présidentielle depuis 2017.
- Pour **droite** : Wikipédia le place à « l'aile droite de la majorité » ; il propose en septembre 2026 un parti unique de la droite et du centre ; il s'est éloigné de Macron.

### Delphine Batho (`batho`)

Proposition : **gauche**.

- Pour **gauche** : Ex-PS, élue sous l'étiquette NFP ; Wikipédia classe GE au centre gauche.
- Pour **null** : Elle récuse l'axe gauche-droite au profit de « terriens » contre « destructeurs ».

### David Lisnard (`lisnard`)

Proposition : **droite**.

- Pour **droite** : Libéral, ex-vice-président de LR, favorable à une primaire à droite.
- Pour **null** : Nouvelle Énergie n'affiche aucun positionnement dans la source lue.

### Xavier Bertrand (`bertrand`)

Proposition : **droite**.

- Pour **droite** : « Gaulliste social, droite sociale et populaire » ; Nous France est associé à LR.
- Pour **centre** : Il refuse la primaire de la droite et s'oppose à l'alliance LR-RN ; sa « droite sociale » est parfois dite centriste. Aucune source lue ne le place au centre : argument à documenter.

### Dominique de Villepin (`villepin`)

Proposition : **null**.

- Pour **null** : Le parti ne se positionne pas ; il se dit gaulliste.
- Pour **droite** : Gaulliste, Premier ministre de Chirac.

### Bernard Cazeneuve (`cazeneuve`)

Proposition : **gauche**.

- Pour **gauche** : Il se réclame d'une « gauche sociale-démocrate » et a quitté le PS en 2022.
- Pour **centre** : Il renvoie LFI et RN dos à dos ; il refuse la primaire socialiste ; sa candidature est hors du pôle socialiste.

### Bruno Le Maire (`bruno le maire`)

Proposition : **centre**.

- Pour **centre** : Renaissance dans l'infobox depuis 2017.
- Pour **droite** : Ex-LR, famille néogaulliste ; la source ne donne aucune prise de position récente.

### Gérald Darmanin (`darmanin`)

Proposition : **centre**.

- Pour **centre** : Il reste membre de Renaissance selon le texte de sa fiche ; il soutient Philippe.
- Pour **droite** : Son discours et ses positions (moratoire sur l'immigration légale) sont classés à droite ; l'infobox ne lui donne plus de parti en cours (« Populaires », 2024-2025).

### Christiane Taubira (`taubira`)

Proposition : **gauche**.

- Pour **gauche** : Ex-PRG, soutien de la primaire de gauche, de Mélenchon (2022) et de la liste LFI (2024).
- Pour **null** : Walwari est un parti guyanais sans positionnement affiché ; Wikipédia cite un historien : « pas très marquée à gauche ».

### François Asselineau (`asselineau`)

Proposition : **null**.

- Pour **null** : L'UPR se dit hors du clivage ; nuance « divers » du ministère.
- Pour **droite** : La presse le situe à droite voire à l'extrême droite.

### Florian Philippot (`philippot`)

Proposition : **null**.

- Pour **null** : « Sociale-souverainiste » ; aucune source lue ne le classe.
- Pour **droite** : Ex-vice-président du Front national, Wikipédia cite un politologue : « europhobie » comme conviction centrale ; il serait prêt à s'effacer pour un candidat de droite souverainiste.

### Jean Lassalle (`lassalle`)

Proposition : **null**.

- Pour **null** : Placé « entre le centre et le centre droit » par les médias, mais à une extrémité de l'axe en 2017.
- Pour **centre** : Ancien du MoDem.

### Aurélien Pradié (`pradie`)

Proposition : **droite**.

- Pour **droite** : Ex-LR, « droite sociale », proche de Bertrand.
- Pour **null** : Les Bâtisseurs sont liés à Régions et peuples solidaires (régionalistes, écologistes) ; non-inscrit à l'Assemblée.

### Manuel Valls (`valls`)

Proposition : **centre**.

- Pour **centre** : Membre de Renaissance depuis 2021.
- Pour **gauche** : Issu du PS, courant rocardien ; ministre d'État de gouvernements du « socle commun » jusqu'en octobre 2025.

### Tibo InShape (`tibo inshape`)

Proposition : **null**.

- Pour **null** : Personnalité non partisane ; il refuse de prendre parti.
- Pour **droite** : Il se déclare « de droite » en 2024 (entretien Brut) et dit avoir voté Renaissance au second tour des législatives.

### Nouvelle Énergie (`nouvelle energie`)

Proposition : **droite**.

- Pour **droite** : Parti de Lisnard, libéral, issu de LR.
- Pour **null** : Aucun positionnement affiché dans la source lue ; même raisonnement que pour David Lisnard.

### Union populaire républicaine (`upr`)

Proposition : **null**.

- Pour **null** : Même raisonnement que pour François Asselineau.
- Pour **droite** : Voir Asselineau.

### Parti animaliste (`animaliste`)

Proposition : **null**.

- Pour **null** : Parti transpartisan, mono-thématique.
- Pour **gauche** : Aucune source lue ne le dit ; argument à documenter (positions sur la chasse et la corrida souvent rapprochées de la gauche).

**Question structurelle.** Les extrêmes sont repliés sur `gauche` et `droite` (règle 4). Un quatrième camp ou une teinte pour l'extrême est une alternative : le contrat du dashboard devrait alors changer.

## 6. Limites et point juridique

**Limites.**

- Simplification : un axe unique à trois valeurs. Les écologistes, les souverainistes et les mono-thématiques s'y rangent mal.
- Daté du 14/10/2026. Les partis bougent (ex. la désignation de Glucksmann date du 11/10/2026 ; le départ de Lisnard de LR du 31/03/2026).
- Sources de qualité inégale : Wikipédia est ouvert à l'édition (la fiche de Xavier Bertrand porte un bandeau de contributions non déclarées) ; plusieurs fiches lues sont tronquées. Les fiches de l'infobox n'ont pas de champ « position » pour les personnes.
- Les 68 entités ne sont pas toutes candidates : plusieurs sont des personnalités ou des partis sans candidature déclarée.
- Une entité = un camp. L'alias `le pen` recouvre trois personnes d'un même camp.

**Point juridique.** La [question 8](questions_ethique_livrable1.md) (le rattachement est-il une donnée sensible, art. 9.2(e) du RGPD ?) reste ouverte. Garde-fous : le camp est celui d'une **personne publique**, déduit de ses déclarations et de sa formation publiques ; il n'est jamais déduit des posts d'un internaute ; la table ne contient aucune donnée sur les auteurs de posts.

## 7. Contester ou mettre à jour

1. Ouvrir une demande de modification : l'entité, la source ouverte (URL, date), le camp proposé.
2. Modifier `camp` dans `entites.yaml` **et** la ligne de la « Table des entités » dans le même commit ; `tests/test_analyse_lexique.py` vérifie la cohérence des deux.
3. Dater la modification dans le message de commit. Mettre à jour la date d'état en tête de « Objet ».

### Registre des sources

Wikipédia en français, consulté le **2026-10-14**. Les pages portent leur propre bibliographie.

| Réf. | Page | URL |
| --- | --- | --- |
| W1 | Marine Le Pen | https://fr.wikipedia.org/wiki/Marine_Le_Pen |
| W2 | Rassemblement national | https://fr.wikipedia.org/wiki/Rassemblement_national |
| W3 | Jordan Bardella | https://fr.wikipedia.org/wiki/Jordan_Bardella |
| W4 | Jean-Luc Mélenchon | https://fr.wikipedia.org/wiki/Jean-Luc_M%C3%A9lenchon |
| W5 | La France insoumise | https://fr.wikipedia.org/wiki/La_France_insoumise |
| W6 | Raphaël Glucksmann | https://fr.wikipedia.org/wiki/Rapha%C3%ABl_Glucksmann |
| W7 | Parti socialiste (France) | https://fr.wikipedia.org/wiki/Parti_socialiste_(France) |
| W8 | Édouard Philippe | https://fr.wikipedia.org/wiki/%C3%89douard_Philippe |
| W9 | Horizons (parti politique) | https://fr.wikipedia.org/wiki/Horizons_(parti_politique) |
| W10 | Gabriel Attal | https://fr.wikipedia.org/wiki/Gabriel_Attal |
| W11 | Bruno Retailleau | https://fr.wikipedia.org/wiki/Bruno_Retailleau |
| W12 | Les Républicains | https://fr.wikipedia.org/wiki/Les_R%C3%A9publicains |
| W13 | Fabien Roussel | https://fr.wikipedia.org/wiki/Fabien_Roussel |
| W14 | Parti communiste français | https://fr.wikipedia.org/wiki/Parti_communiste_fran%C3%A7ais |
| W15 | François Ruffin | https://fr.wikipedia.org/wiki/Fran%C3%A7ois_Ruffin |
| W16 | Éric Zemmour | https://fr.wikipedia.org/wiki/%C3%89ric_Zemmour |
| W17 | Reconquête (parti politique) | https://fr.wikipedia.org/wiki/Reconqu%C3%AAte_(parti_politique) |
| W18 | Marine Tondelier | https://fr.wikipedia.org/wiki/Marine_Tondelier |
| W19 | Les Écologistes | https://fr.wikipedia.org/wiki/Les_%C3%89cologistes |
| W20 | Delphine Batho | https://fr.wikipedia.org/wiki/Delphine_Batho |
| W21 | Génération écologie | https://fr.wikipedia.org/wiki/G%C3%A9n%C3%A9ration_%C3%A9cologie |
| W22 | David Lisnard | https://fr.wikipedia.org/wiki/David_Lisnard |
| W23 | Xavier Bertrand | https://fr.wikipedia.org/wiki/Xavier_Bertrand |
| W24 | Nous France | https://fr.wikipedia.org/wiki/Nous_France |
| W25 | Olivier Faure | https://fr.wikipedia.org/wiki/Olivier_Faure |
| W26 | Jérôme Guedj | https://fr.wikipedia.org/wiki/J%C3%A9r%C3%B4me_Guedj |
| W27 | Ségolène Royal | https://fr.wikipedia.org/wiki/S%C3%A9gol%C3%A8ne_Royal |
| W28 | Emmanuel Maurel | https://fr.wikipedia.org/wiki/Emmanuel_Maurel |
| W29 | Gauche républicaine et socialiste | https://fr.wikipedia.org/wiki/Gauche_r%C3%A9publicaine_et_socialiste |
| W30 | François Hollande | https://fr.wikipedia.org/wiki/Fran%C3%A7ois_Hollande |
| W31 | Dominique de Villepin | https://fr.wikipedia.org/wiki/Dominique_de_Villepin |
| W32 | Bernard Cazeneuve | https://fr.wikipedia.org/wiki/Bernard_Cazeneuve |
| W33 | Karim Bouamrane | https://fr.wikipedia.org/wiki/Karim_Bouamrane |
| W34 | Bruno Le Maire | https://fr.wikipedia.org/wiki/Bruno_Le_Maire |
| W35 | Valérie Pécresse | https://fr.wikipedia.org/wiki/Val%C3%A9rie_P%C3%A9cresse |
| W36 | Éric Ciotti | https://fr.wikipedia.org/wiki/%C3%89ric_Ciotti |
| W37 | Union des droites pour la République | https://fr.wikipedia.org/wiki/Union_des_droites_pour_la_R%C3%A9publique |
| W38 | Michel Barnier | https://fr.wikipedia.org/wiki/Michel_Barnier |
| W39 | Gérald Darmanin | https://fr.wikipedia.org/wiki/G%C3%A9rald_Darmanin |
| W40 | Élisabeth Borne | https://fr.wikipedia.org/wiki/%C3%89lisabeth_Borne |
| W41 | Yaël Braun-Pivet | https://fr.wikipedia.org/wiki/Ya%C3%ABl_Braun-Pivet |
| W42 | Laurent Wauquiez | https://fr.wikipedia.org/wiki/Laurent_Wauquiez |
| W43 | Clémentine Autain | https://fr.wikipedia.org/wiki/Cl%C3%A9mentine_Autain |
| W44 | Christiane Taubira | https://fr.wikipedia.org/wiki/Christiane_Taubira |
| W45 | Philippe Poutou | https://fr.wikipedia.org/wiki/Philippe_Poutou |
| W46 | Nouveau Parti anticapitaliste | https://fr.wikipedia.org/wiki/Nouveau_Parti_anticapitaliste |
| W47 | Nathalie Arthaud | https://fr.wikipedia.org/wiki/Nathalie_Arthaud |
| W48 | Lutte ouvrière | https://fr.wikipedia.org/wiki/Lutte_ouvri%C3%A8re |
| W49 | François Asselineau | https://fr.wikipedia.org/wiki/Fran%C3%A7ois_Asselineau |
| W50 | Nicolas Dupont-Aignan | https://fr.wikipedia.org/wiki/Nicolas_Dupont-Aignan |
| W51 | Debout la France | https://fr.wikipedia.org/wiki/Debout_la_France |
| W52 | Florian Philippot | https://fr.wikipedia.org/wiki/Florian_Philippot |
| W53 | Hélène Thouy | https://fr.wikipedia.org/wiki/H%C3%A9l%C3%A8ne_Thouy |
| W54 | Parti animaliste | https://fr.wikipedia.org/wiki/Parti_animaliste |
| W55 | Jean Lassalle | https://fr.wikipedia.org/wiki/Jean_Lassalle |
| W56 | Louis Aliot | https://fr.wikipedia.org/wiki/Louis_Aliot |
| W57 | Sarah Knafo | https://fr.wikipedia.org/wiki/Sarah_Knafo |
| W58 | François-Xavier Bellamy | https://fr.wikipedia.org/wiki/Fran%C3%A7ois-Xavier_Bellamy |
| W59 | Aurélien Pradié | https://fr.wikipedia.org/wiki/Aur%C3%A9lien_Pradi%C3%A9 |
| W60 | Anne Hidalgo | https://fr.wikipedia.org/wiki/Anne_Hidalgo |
| W61 | Manuel Valls | https://fr.wikipedia.org/wiki/Manuel_Valls |
| W62 | Ian Brossat | https://fr.wikipedia.org/wiki/Ian_Brossat |
| W63 | François Bayrou | https://fr.wikipedia.org/wiki/Fran%C3%A7ois_Bayrou |
| W64 | Mouvement démocrate (France) | https://fr.wikipedia.org/wiki/Mouvement_d%C3%A9mocrate_(France) |
| W65 | Tibo InShape | https://fr.wikipedia.org/wiki/Tibo_InShape |
| W66 | Renaissance (parti politique) | https://fr.wikipedia.org/wiki/Renaissance_(parti_politique) |

Autres sources lues le 2026-10-14 :

- Banque des Territoires, « Législatives : le nuancier politique et son mode d'emploi enfin mis en ligne » : <https://www.banquedesterritoires.fr/legislatives-le-nuancier-politique-et-son-mode-demploi-enfin-mis-en-ligne> (grille de 24 nuances du ministère de l'Intérieur, 2024 ; codes de sensibilité EXG, DVC, DVD).
- Wikipédia, « Élection présidentielle française de 2027 » : <https://fr.wikipedia.org/wiki/%C3%89lection_pr%C3%A9sidentielle_fran%C3%A7aise_de_2027> (liste des candidatures, état du 14/10/2026).
