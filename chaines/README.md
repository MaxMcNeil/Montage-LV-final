# Chaînes : logo, nom, couleurs

Un dossier par chaîne. Le montage choisit tout seul la chaîne d'après la **langue de la vidéo**.

```
chaines/fr/logo.png      ← ton logo (PNG à fond transparent, 512 px ou plus)
chaines/fr/chaine.json   ← {"nom": "Le Journal du NON", "langues": ["fr"]}
chaines/ar/…
```

- **Changer de logo** : remplace `logo.png` (même nom). **Changer de nom** : modifie `"nom"` dans `chaine.json`.
- **Nouvelle chaîne (italien, anglais…)** : crée `chaines/it/` avec `logo.png` et
  `chaine.json` → `{"nom": "…", "langues": ["it"]}`. Rien d'autre à faire.
- **Règle stricte langue = chaîne** : le logo français n'apparaît QUE sur une vidéo en français, le logo arabe QUE sur
  une vidéo en arabe, etc. Vidéo dans une langue sans dossier (ex. italien avant que tu crées `chaines/it/`) →
  **aucun logo** (écrit dans PLAN.md), jamais celui d'une autre chaîne.
- **Forcer une chaîne** : réglage `chaine: ar` (ou menu *chaine* du formulaire) — refusé si la vidéo n'est pas dans
  la langue de cette chaîne. `chaine: non` = aucun habillage. `logo: non` = pas de logo.
- **Couleurs** : tirées du logo automatiquement (bleu nuit, or, rouge), assombries si besoin pour rester lisibles.
  Pour imposer une couleur : `"couleurs": {"GOLD": "#E8A536"}` (clés : NAVY, NAVY_DEEP, GOLD, RED).
  Pour garder la palette maison : `"couleurs_auto": false`.

Habillage : petit logo en haut à droite (jamais sur ton visage ni sur les cadres) + grand logo sur la carte de fin
(vidéos horizontales). Tout problème (logo absent, abîmé, sans transparence…) est écrit dans **PLAN.md** ;
le montage n'échoue jamais à cause du logo.

## Pack d'animations (`chaines/<code>/habillage/`)

Si ce dossier existe et est complet, le Montage pose tout seul, sur la vidéo **horizontale** de cette chaîne :
transition au changement de chapitre (3 au plus), raccord discret sur quelques coupes (3 au plus, espacés d'au moins
1 min 30), invitation like / abonnement **une fois, sans son**, au-dessus des sous-titres, et l'écran de fin de 20 s
collé après la vidéo. Jamais sur un extrait ni sur une carte. Le style et les moments changent d'une vidéo à l'autre.
Sons graves et bas, aigus coupés au-dessus de 3,5 kHz. Vidéo verticale, Shorts, autre chaîne : rien ne change.
Désactiver : réglage `pack: non`. Au moindre problème, la vidéo normale est gardée et PLAN.md le dit.
