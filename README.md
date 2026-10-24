# Montage LV final

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
max_inserts: 2
duree_max_insert: 20
langue: ar
effets_sonores: non
fin: non
images_web: non
```

Le titre de ta release affiche l'état : **⏳ EN COURS** → **✅ TERMINÉ** (lien vers le résultat) ou **❌ ÉCHEC** (lien vers l'erreur).
Le résultat arrive dans la release **🎬 RÉSULTAT — Montage final** : la vidéo + **PLAN.md** (quoi, où, quand, et pourquoi).
Chaque nouveau montage **remplace** le précédent, et les anciennes vidéos déposées sont supprimées (le dépôt ne grossit pas).

Autre façon : *Actions → Montage final → Run workflow* (lien Drive de la vidéo, liens des pièces jointes, consignes, réglages).

## 🎬 Ce que fait le montage

| | |
|---|---|
| **Au bon moment** | L'IA lit ta transcription phrase par phrase et rattache chaque élément à un **mot déclencheur** : la photo de Macron apparaît quand tu dis « Macron », le chiffre quand tu le prononces. Jamais parachuté. |
| **Photos, articles, chiffres à côté de toi** | Partage d'écran élégant : toi dans un cadre arrondi avec ombre, le média qui glisse à côté (lent travelling sur les photos). Fond = ton image floutée teintée bleu nuit. Alterné gauche/droite (en vertical : toi en haut, média en bas). |
| **Vidéos pendant tes silences** | Une vidéo (la tienne ou un extrait officiel trouvé) est insérée **entre deux phrases** : tu disparais le temps de l'extrait, transition glissée, puis tu reviens. Coupée sur une **phrase complète**, sous-titrée, **traduite** si elle n'est pas dans ta langue, avec le crédit (qui parle, média, date). |
| **Tes photos jointes** | L'IA regarde chaque image, comprend ce qu'elle montre et la place quand tu en parles. Les captures d'écran / documents ne sont jamais rognés. |
| **Photos libres de droits** | Personnes, lieux, institutions cités : photo de **Wikimedia Commons** (licences libres uniquement, crédit affiché). |
| **Presse** | Ton dépôt **Vid-o-presse-finder** cherche les déclarations officielles et articles qui appuient ce que tu dis : extrait vidéo inséré + carte « article » (média, date, titre). |
| **Rythme / rétention** | Accroche écrite pendant les 3 premières secondes, silences raccourcis (« doux » par défaut), zooms de relance qui changent à chaque coupe (les coupes deviennent invisibles), titres de chapitres, chiffres clés et citations fortes en cartes, sous-titres phrase par phrase avec les mots clés en or. |
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
