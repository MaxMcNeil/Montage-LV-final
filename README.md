# Montage LV final

> 📌 **Ton réflexe après chaque montage** : le titre du résultat et la **1re ligne de PLAN.md** donnent le verdict.
> **✅ prêt à publier** → tu peux publier sans tout revisionner.
> **⚠ à vérifier** → la ligne « Contrôle qualité » de PLAN.md dit exactement quoi et à quel moment : regarde ce
> passage avant de publier. (Valable pour tous les montages : release, *Run workflow* et chaîne.)

Tu déposes ta vidéo face caméra (horizontale ou verticale) avec, si tu veux, des photos et des vidéos.
GitHub la **transcrit**, **comprend ce que tu dis**, puis **monte** la vidéo : photos, articles, chiffres et
extraits vidéo arrivent **au moment exact où tu en parles**. Tout est gratuit et tourne sur GitHub.

## 📥 Déposer une vidéo (depuis le téléphone)

*Releases → Draft a new release → Choose a tag* : tape `montage-001` (puis `montage-002`…) → *Create new tag*.
Joins **ta vidéo** + tes **photos / vidéos** (glisser ou « Attach binaries ») → *Publish release*.

- **Ta vidéo = le fichier dont le nom commence par « moi »** (`moi.mp4`, `Moi_interview.mov`…), qu'il soit joint à la
  release ou sur Google Drive. Sans fichier « moi… » : la plus grosse vidéo jointe. Tout le reste = pièces jointes à placer.
- **Vidéo trop lourde (> 2 Go) ou déjà sur Google Drive** : ne joins rien, colle le **lien Google Drive** dans la
  description. D'autres liens Drive (fichiers ou **dossier**) dans la description = pièces jointes.
- **Consignes** : écris-les librement dans la description, l'IA les lit
  (« la photo 2 c'est le ministre », « insiste sur les chiffres »…).
- **Réglages** (facultatifs), une ligne chacun dans la description :

```
sous_titres: non
couper_silences: dynamique
recherche_presse: non
max_inserts: auto
duree_max_insert: 20
langue: ar
effets_sonores: non
fin: non
images_web: non
```

**Passage imposé pour une de tes vidéos jointes** (facultatif) : une ligne par vidéo, nom du fichier = début-fin.
Sans cette ligne, l'IA choisit elle-même le passage utile (25 s max, coupé en fin de phrase).

```
discours.mp4 = 1:20-1:45
interview_ministre.mov = 0:05-0:32
reportage.mp4 = 1:02:10-1:02:40
```

Le passage est appliqué à la lettre (même au-delà de 25 s). Ça marche aussi dans le champ « consignes » du
formulaire *Run workflow*. Le nom doit être celui du fichier joint (majuscules sans importance ; l'extension peut
même différer).

**Tes extraits peuvent aussi être dans une autre release** (ex. tag `Video`, sans fichier « moi… ») : elle passe en
**📎 EN ATTENTE** et ses photos/vidéos sont ajoutées automatiquement au prochain montage lancé dans les 3 jours
(release « montage… » ou *Run workflow*), puis elle est supprimée. Tu peux aussi écrire son tag dans le champ
« pieces_jointes » du formulaire.

Le titre de ta release affiche l'état : **⏳ EN COURS** → **✅ TERMINÉ** (lien vers le résultat) ou **❌ ÉCHEC** (lien vers l'erreur).
Le résultat arrive dans la release **🎬 RÉSULTAT — Montage final** : la vidéo + **PLAN.md** (quoi, où, quand, et pourquoi).
Chaque nouveau montage **remplace** le précédent dans « 🎬 RÉSULTAT » ; tes releases déposées ne sont jamais supprimées automatiquement.

**Le plus simple, sans release** : dépose ta vidéo (nom commençant par « moi ») ET tes extraits dans le dossier
Drive **montage-joints**, puis *Actions → Montage final → Run workflow* en laissant « source » **vide**. Ta vidéo
« moi… » reste dans le dossier après le montage ; les extraits utilisés en sont retirés (montage réussi seulement).

Autre façon : *Actions → Montage final → Run workflow* (lien Drive de la vidéo, liens des pièces jointes, consignes, réglages).

## 🆕 Habillage, mise en scène, recherche par affirmation

- **Chaîne (logo, nom, couleurs)** : dossier [`chaines/`](chaines/README.md), une chaîne par langue (fr = Le Journal du
  NON, ar = Gulf think-tank, puis it, en…). **Règle stricte** : logo d'une chaîne seulement sur une vidéo dans sa
  langue ; langue sans chaîne → aucun logo. Les Shorts (Push-overlay) lisent ce même dossier.
- **Articles** : autant que la vidéo en porte (~1 par minute et demie, jusqu'à 30) — plusieurs cartes par affirmation.
- **« Écoutez ça » dans 4 langues** : *écoutez ça · écoutez ce qu'il dit…* / *ascoltate questo · ascoltate cosa dice…* /
  *listen to this · listen to what he says…* / *اسمعوا هذا · اسمعوا ماذا يقول…* → l'extrait de ta vidéo jointe juste après.
- **Mise en scène par ta voix** (`mise_en_scene: non` pour couper) : ton qui monte → plan serré (coupe au début de la
  phrase), ton posé → plan large, débit rapide → plans plus courts. Jamais deux fois le même plan de suite.
- **Recherche par affirmation** (`affirmations: auto` par défaut = selon la durée, ~1 par minute, de 4 à 30 ; ou un
  nombre ; `0` = aucune) : TOUTES les affirmations vérifiables de ta vidéo sont cherchées une par une (vidéos, presse, **Telegram**, **Reddit**), même si le lot Finder est utilisé (sans
  refaire ce qu'il couvre déjà). Vidéos, presse et Telegram/Reddit sont cherchés **en même temps** (chacun son temps
  réservé, ~12 min par affirmation, 3 à la fois) : plus rien n'est sauté faute de temps. Les **vidéos postées sur
  Telegram / Reddit** (et Dailymotion, Rumble, Odysee, archive.org, médias) servent d'extraits quand YouTube bloque
  GitHub. PLAN.md liste chaque affirmation (trouvé / rien / pourquoi) avec, ligne 🔍, ce qui a été vu source par source,
  et une section **🛡 Ce qui te contredit** : à anticiper dans ta vidéo.
- **Rythme** (`rythme: oui` par défaut) : extraits vidéo, articles et photos comptent pareil. 5 premières minutes →
  un élément au moins toutes les 60 s ; ensuite un environ toutes les 2 min (jamais plus de 2 min 15 sans rien), et
  pas d'ajout automatique à moins de 1 min 30 du précédent. Tes « écoutez ça » et tes pièces jointes passent toujours.
  Trou à remplir : passage de tes vidéos jointes, sinon article pas encore utilisé, sinon photo (la tienne, sinon photo
  libre) — toujours cohérent et vérifié. Le contrôle qualité signale ⚠ tout trou de plus de 2 min 30 après 5 min.
- **Limites automatiques** : nombre d'extraits (tes vidéos jointes, presse, Finder) dimensionné sur la durée de ta
  vidéo selon la règle du rythme (ex. 35 min → 20 éléments) — plus aucun chiffre fixe. `max_inserts: 10` force un
  nombre si tu veux. Tes « écoutez ça » passent toujours en plus.
- **Tes pièces jointes** : une vidéo jointe sans silence juste après le moment prévu est placée au silence d'une
  phrase voisine (jamais sur un mot). Une pièce jointe qui n'a pu être placée fait passer le verdict en **⚠** avec
  son nom et la raison.
- **« Écoutez ça » sans vidéo jointe qui convienne** : le montage fait entendre à la place une déclaration trouvée par
  le Finder ou la recherche par affirmation, si elle correspond EXACTEMENT à ce que tu annonces (choisie par l'IA, puis
  vérifiée par une 2e lecture). Sources qui se téléchargent bien (médias, Dailymotion…) essayées avant YouTube. Si
  aucune vidéo ne se télécharge : la VRAIE citation (qui, média, date) en carte plein écran pendant ton silence.
  Sinon rien, et PLAN.md dit pourquoi.
- **Voix studio chaude** (`voix_studio: oui`, **non** par défaut ; réglage « chaude max » choisi à l'écoute) :
  coupe des grondements, débruitage doux réglé sur le bruit de ta pièce, profondeur (graves de la voix), clarté
  et présence, dé-esseur, double compression façon radio, volume YouTube. Contrôlé : même durée à l'échantillon près,
  aucune saturation ; au moindre doute → ta voix normale, et c'est écrit dans PLAN.md (ligne 🎙). Aucune IA, aucune
  clé, le son des extraits n'est pas touché.
- **Telegram** : secrets `TG_API_ID`, `TG_API_HASH`, `TG_SESSION` — session **différente** de celle de
  Vid-o-presse-finder (Telegram détruit une session utilisée en même temps sur deux machines).

## 🔗 Synchro avec Vid-o-presse-finder

Ton enchaînement : tu lances **Vid-o-presse-finder** sur ton sujet → tu enregistres ta vidéo d'après ses résultats →
tu lances le montage. Par défaut (`finder: oui`), le montage reprend le **dernier lot** du Finder (extraits vidéo
horodatés + articles) ; l'IA garde ceux qui correspondent à ce que tu dis et les place au bon moment :
- déclaration en vidéo → insérée pendant ton silence, juste après la phrase où tu en parles (coupée sur ses
  timestamps, en fin de phrase, sous-titrée/traduite) ;
- si YouTube refuse le téléchargement depuis GitHub → la déclaration apparaît quand même en **carte** à côté de toi
  (vignette, citation traduite, qui, média, date) ;
- articles → cartes à côté de toi quand tu en parles.

Vidéo sans rapport avec ta dernière recherche (seules tes pièces jointes et les photos libres sont utilisées) :
- **Release** : tag `montage-solo-001`, `montage-solo-002`… (tag `montage-001` = avec le Finder) ;
- **Run workflow** : menu déroulant **finder** → `non`.
Un lot précis : `finder: 2026-10-24_2144_n16`.
Lots lancés **automatiquement par OSINT-teleprompter-** (après chaque script de live) : ils portent `ORIGINE.json`
(sujet, thèse, dossier du script). Le montage s'en sert pour choisir les extraits qui collent à ton live.
`finder: osint` = dernier lot lancé par OSINT ; `finder: suisse microsoft` = dernier lot OSINT dont le sujet contient ces mots.

Pour que les extraits YouTube passent vraiment en vidéo : secret `YT_COOKIES` (contenu d'un fichier cookies.txt
exporté depuis un navigateur connecté à YouTube) ou `YT_PROXY_URL`.

## 🔗 Chaîne depuis le fond vert (automatique)

Quand tu coches **enchainer** dans le dépôt fond vert, ce montage est lancé tout seul à la fin du fond vert
(synchro Finder `oui`, ou `non` = photos/vidéos du dossier Google Drive **`montage-joints`**), puis il lance les
Shorts dans Push-overlay. Résultat : release **`out-chaine-<id>`** (supprimée après 2 jours) — ta release
`out-montage` et tes montages manuels ne sont pas touchés. Il faut ici : `RCLONE_CONF` (même compte Google que le
fond vert) + variable `CHAINE_APP_ID` / secret `CHAINE_APP_KEY` (ou secret `CHAINE_TOKEN`). Guide complet : README
du dépôt vdo-BACKGROUND-replace-GREEN-, section « Chaîne ». En cas d'échec : **Re-run jobs** sur le run.

## 🎞️ Rythme des extraits (rétention, automatique)

Pour garder l'attention, tes vidéos jointes reviennent régulièrement à l'écran :
- **5 premières minutes : jamais plus de 60 s sans un extrait** ;
- **ensuite : jamais plus de 2 min** (vidéo de plus de 5 min).

Les extraits déjà prévus (plan de l'IA, « écoutez ça », Vid-o-presse-finder) comptent ; là où il en manque, un passage
de tes vidéos jointes est ajouté, **seulement s'il est cohérent avec ce que tu dis à ce moment-là** :
point d'insertion dans un vrai silence en fin de phrase (jamais pendant que tu parles), passage de 6 à 15 s en phrases
complètes choisi d'après ce que tu dis avant et après, puis **2e lecture indépendante** qui vérifie le lien ; au moins
25 s entre deux extraits ; **jamais deux fois le même passage** (celui de l'ouverture choc compris). Aucun passage
cohérent → pas d'extrait (mieux vaut un trou qu'un hors-sujet) : PLAN.md, ligne « Rythme des extraits », liste chaque
extrait ajouté et chaque trou avec la raison. Chaque extrait a sa **propre légende** (ce que montre ce passage).
Pour couper : `rythme: non` dans les consignes ou la description de la release.

## ⚡ Ouverture choc (facultatif)

**Activée par défaut** (release, *Run workflow* et chaîne automatique fond vert → montage → Shorts).
**Sans vidéo jointe**, l'ouverture est prise parmi les **déclarations vidéo trouvées par la recherche** (dernier lot
Vid-o-presse-finder + recherche selon ta vidéo) : l'IA classe les plus fortes **en rapport avec ton sujet**, la première
qui se télécharge vraiment est utilisée (4 à 12 s, sous-titrée, source affichée), jamais une vidéo déjà insérée ailleurs.
Rien de solide, ou vidéos bloquées → la vidéo commence normalement. PLAN.md dit toujours ce qui a été fait (ligne ⚡). Pour la couper : menu **ouverture_choc** → `non`, ou `ouverture_choc: non` dans la description
d'une release ou dans les consignes. La vidéo finale **commence** alors par le passage le plus fort / choquant
(4 à 12 s, phrases complètes, sous-titré) de ta **vidéo jointe** (release ou Drive), qui surgit du noir ; puis tu
apparais et l'accroche s'affiche. L'IA choisit le passage en lisant la transcription de l'extrait ; un passage imposé
(`fichier.mp4 = 1:20-1:45`) sert de repli sans IA.
La langue se règle désormais dans les consignes : `langue: ar` (sinon détectée automatiquement).

## 🎧 Mots-clés « écoutez… » (facultatif)

Activé par défaut (*Run workflow*, release et chaîne depuis le fond vert). Pour le couper : menu **mots_cles** → `non`, ou `mots_cles: non` dans la description d'une release ou dans les consignes.
Chaque fois que tu dis **exactement** : *écoutez ça · écoutez-moi ça · écoutez ce qu'il dit · écoutez ce qu'elle dit ·
écoutez ce qu'ils disent*, un passage de ta (tes) vidéo(s) jointe(s) est inséré **juste après**, dans ta pause :
- l'IA choisit le passage d'après ce que tu dis avant et après l'annonce (la personne, le propos, le fait), puis une
  2e lecture indépendante vérifie la cohérence et fait rechoisir si besoin ; phrases complètes, pas deux fois le même ;
- l'extrait n'est jamais posé sur ta voix : il faut une vraie pause juste après la phrase (pour « écoutez ça », dans
  la seconde qui suit — « écoutez ça va changer… » n'est pas une annonce et est ignoré) ;
- une formule voisine (« écoutez bien ça », « écoute ça », « écoutez ceci ») ne déclenche rien ;
- PLAN.md liste chaque annonce : passage inséré et vérification ✅, ou ⚠ la raison ; le contrôle qualité le vérifie.
Passage imposé pour une vidéo (`discours.mp4 = 1:20-1:45`) : seul ce passage de cette vidéo est utilisé.

## 🤫 Silences de plus de 2 s (automatique)

Tout silence de plus de 2 s est raccourci à une respiration naturelle (~0,6 s), en vertical comme en horizontal, dans
toutes les langues (seul le son compte, pas les mots). Le silence est mesuré par rapport au **bruit de fond réel de ta
pièce** (fiable même avec un fond vert remplacé ou un micro un peu bruyant) ; un mot dont l'horodatage « déborde »
sur la pause est corrigé. À la coupe, l'effet dépend de ta position :
- tu n'as presque pas bougé → **changement de plan** (zoom avant/arrière), comme une deuxième caméra ;
- tu as bougé → **fondu enchaîné doux** (0,24–0,32 s), fait avec les images du silence supprimé : la durée et la
  synchro du son ne changent pas ;
- la coupe tombe sur l'arrivée d'une photo ou d'un extrait → sa transition suffit.

PLAN.md indique le nombre de silences raccourcis et le temps gagné ; le contrôle qualité vérifie qu'il n'en reste
aucun. Pour garder tes longs silences : `silences_longs: non` (description de la release ou consignes).

## 📂 Google Drive (comme le dépôt fond vert)

- **Ta vidéo** peut être donnée par son chemin Drive dans le champ *source* : `gdrive:resultats/moi-ma-video.mp4`
  (ou un lien Google Drive, ou un tag de release).
- **Dossier `montage-joints`** : ses photos / vidéos sont **toujours** prises (manuel, release et chaîne). Après un
  montage déposé avec succès, seuls les fichiers pris par ce montage en sont retirés (corbeille Drive, 30 jours).
- **Autres pièces jointes** : champ *pieces_jointes* → `gdrive:un-dossier`, `gdrive:dossier/fichier.mp4`, liens Drive,
  ou tag d'une release (ex. `video`).
- **Résultat** : toujours copié sur Drive dans `resultats/montage-<nom>.mp4` (+ son PLAN), quelle que soit la taille ;
  et aussi dans la release « 🎬 RÉSULTAT » s'il fait moins de 1,9 Go. Autre dossier : variable `RCLONE_DEST`.
- **Tes releases déposées ne sont jamais supprimées automatiquement** (vidéos et pièces jointes) : seul leur titre
  change d'état (⏳ / ✅ / ❌ / 📎). Une release de pièces jointes est triée en quelques secondes (📎 EN ATTENTE).

## 🎬 Ce que fait le montage

| | |
|---|---|
| **Au bon moment** | L'IA lit ta transcription phrase par phrase et rattache chaque élément à un **mot déclencheur** : la photo de Macron apparaît quand tu dis « Macron », le chiffre quand tu le prononces. Jamais parachuté. |
| **Photos, articles, chiffres à côté de toi** | Partage d'écran élégant : toi dans un cadre arrondi avec ombre, le média qui glisse à côté (lent travelling sur les photos). Fond = ton image floutée teintée bleu nuit. Alterné gauche/droite (en vertical : toi en haut, média en bas). |
| **Vidéos pendant tes silences** | Une vidéo (la tienne ou un extrait officiel trouvé) est insérée **entre deux phrases** : tu disparais le temps de l'extrait, transition glissée, puis tu reviens. Coupée sur une **phrase complète**, sous-titrée, **traduite** si elle n'est pas dans ta langue, avec le crédit (qui parle, média, date). |
| **Tes photos jointes** | L'IA regarde chaque image, comprend ce qu'elle montre et la place quand tu en parles. Les captures d'écran / documents ne sont jamais rognés. |
| **Photos libres de droits** | Personnes, lieux, institutions cités : photo de **Wikimedia Commons** (licences libres uniquement, crédit affiché). |
| **Presse** | Ton dépôt **Vid-o-presse-finder** cherche les déclarations officielles et articles qui appuient ce que tu dis : extrait vidéo inséré + carte « article » (média, date, titre). |
| **Rythme / rétention** | Accroche écrite pendant les 3 premières secondes, silences raccourcis (« doux » par défaut), zooms de relance qui changent à chaque coupe (les coupes deviennent invisibles), titres de chapitres (dès 2 min de vidéo), chiffres clés et citations fortes en cartes ; sous-titres seulement si tu les demandes (`sous_titres: oui`). |
| **Lisibilité (malvoyants)** | Tout texte à l'écran est en grande police grasse, blanc ou or lumineux sur fond bleu nuit presque opaque (contraste > 12:1), 2 lignes au plus, coupées aux endroits naturels, et reste assez longtemps pour être lu ; l'arabe est agrandi. Titres de chapitres façon journal télévisé (bandeau qui glisse, « PARTIE 02 », filet or) avec un petit générique sonore synthétisé, discret. |
| **Sous-titres : non (défaut)** | **Aucun** sous-titre par défaut, partout (chaîne, release, *Run workflow*) — `sous_titres: oui` pour les remettre : ni ceux de ta voix, ni ceux des extraits insérés (le crédit « qui / source / date » reste). Le contrôle qualité le vérifie. Seul ce qui est déjà incrusté dans une vidéo d'origine (bandeau d'une chaîne TV) ne peut pas être retiré. |
| **Public 40 ans et +** | Style sobre (bleu nuit, crème, or), gros textes très lisibles, animations douces, **aucune musique**, aucun emoji. Petits souffles discrets aux transitions (désactivables). |
| **Langues** | Tous les textes sont écrits par l'IA **dans la langue de ta vidéo** (français, arabe, italien, anglais…), adaptés au sujet. L'arabe est écrit de droite à gauche avec des polices arabes. |
| **Pour YouTube** | PLAN.md donne aussi un titre conseillé, une description et les **chapitres horodatés** à coller. |

## ⚙️ Mise en place (une fois)

*Settings → Secrets and variables → Actions → New repository secret* — **les mêmes clés que Vid-o-presse-finder**
(plusieurs clés dans un secret : une par ligne) :

| Secret | Rôle | |
|---|---|---|
| `GEMINI_API_KEYS` | plan du montage, lecture des images, traductions (rotation des clés et des modèles gratuits) | indispensable |
| `GROQ_API_KEYS` | **transcription** gratuite (Whisper) + relais IA | fortement conseillé |
| `YOUTUBE_API_KEYS` | recherche presse | conseillé |
| `CEREBRAS_API_KEYS`, `OPENROUTER_API_KEYS`, `GUARDIAN_API_KEYS`, `NYT_API_KEYS` | relais / archives de presse | optionnels |
| `RCLONE_CONF` | Google Drive sans limite (grosses vidéos, dossiers, résultat > 1,9 Go) | optionnel |
| `YT_PROXY_URL` | si YouTube refuse les téléchargements depuis GitHub | optionnel |

Sans clé Groq, la transcription se fait quand même sur GitHub (plus lentement). Sans aucune IA, la vidéo est quand
même montée (silences, zooms, sous-titres, tes pièces jointes réparties) et PLAN.md le signale.

**Google Drive** : partage le fichier « Tous les utilisateurs disposant du lien → Lecteur ». Pour les très gros
fichiers (Google bloque parfois : « quota de téléchargement dépassé ») ou les dossiers privés, ajoute `RCLONE_CONF` :
sur un ordinateur, `rclone config` → nouveau remote de type `drive` → copie le contenu de `rclone.conf` dans le secret.

## 🛡️ Robuste et durable

- Chaque étape a un repli : Groq → transcription locale ; Gemini → Groq/Cerebras/OpenRouter → montage sans IA ;
  photo introuvable / extrait refusé → simplement ignoré ; effet en échec → plan simple. **Une vidéo est toujours livrée.**
- Rendu segment par segment (peu de mémoire), son monté à l'échantillon près (aucun décalage, aucun clic aux coupes).
- Versions des outils bornées, système figé (`ubuntu-24.04`), caches (paquets, modèle de transcription, réponses IA,
  état des quotas partagé avec la logique de Vid-o-presse-finder).
- Dépôt privé : 2 000 minutes GitHub gratuites par mois (une vidéo de 20 min ≈ 30 à 45 min de calcul).
  Dépôt public : illimité.

## Structure

```
.github/workflows/montage.yml   le workflow (release « montage… » ou Run workflow)
scripts/fetch_inputs.py         récupère vidéo, pièces jointes, consignes et réglages (Release, Drive, lien)
scripts/publish.sh              publie le résultat (release out-montage, ou Drive, ou Artifacts)
montage/transcribe.py           transcription mot à mot (Groq → faster-whisper)
montage/plan.py                 plan éditorial IA : quoi / où / quand
montage/assets.py               pièces jointes, Wikimedia Commons, Vid-o-presse-finder, extraits, traductions
montage/timeline.py             coupes, insertions dans les silences, placement des médias, zooms
montage/panels.py, ass.py       graphismes (cartes, cadre) et textes à l'écran
montage/render.py               rendu ffmpeg + son
montage/config.py               couleurs, géométrie, polices, textes par langue, réglages par défaut
```

Tests : `pip install pytest && PYTHONPATH=. python -m pytest -q`
