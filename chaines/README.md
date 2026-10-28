# Chaînes : logo, nom, couleurs

Un dossier par chaîne. Le montage choisit tout seul la chaîne d'après la **langue de la vidéo**.

```
chaines/fr/logo.png      ← ton logo (PNG à fond transparent, 512 px ou plus)
chaines/fr/chaine.json   ← {"nom": "Le Journal du NON", "langues": ["fr"], "defaut": true}
chaines/ar/…
```

- **Changer de logo** : remplace `logo.png` (même nom). **Changer de nom** : modifie `"nom"` dans `chaine.json`.
- **Nouvelle chaîne (italien, anglais…)** : crée `chaines/it/` avec `logo.png` et
  `chaine.json` → `{"nom": "…", "langues": ["it"]}`. Rien d'autre à faire.
- **Forcer une chaîne** : réglage `chaine: ar` dans la description (ou menu *chaine* du formulaire).
  `chaine: non` = aucun habillage. `logo: non` = pas de logo.
- **Couleurs** : tirées du logo automatiquement (bleu nuit, or, rouge), assombries si besoin pour rester lisibles.
  Pour imposer une couleur : `"couleurs": {"GOLD": "#E8A536"}` (clés : NAVY, NAVY_DEEP, GOLD, RED).
  Pour garder la palette maison : `"couleurs_auto": false`.
- Une chaîne sans dossier dans sa langue utilise la chaîne marquée `"defaut": true`.

Habillage : petit logo en haut à droite (jamais sur ton visage ni sur les cadres) + grand logo sur la carte de fin
(vidéos horizontales). Tout problème (logo absent, abîmé, sans transparence…) est écrit dans **PLAN.md** ;
le montage n'échoue jamais à cause du logo.
