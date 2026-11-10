# État — Montage-LV-final

Ce qui bloque, pourquoi, quand ça se débloque et quoi faire.

<!-- workflows:start -->
## Workflows

_Vérifié le 10/11/2026 à 09:40 (heure italienne), automatiquement à la fin de chacun de tes lancements (aucune exécution planifiée)._

- ✅ **Diagnostic** : dernier lancement réussi (10/11 à 07:38) · [voir](https://github.com/MaxMcNeil/Montage-LV-final/actions/runs/42769858800)
- ℹ️ **📥 Préparer les médias — avant le Montage** : jamais lancé (ou en cours)
- ❌ **Montage final** : dernier lancement en échec (10/11 à 09:40, failure) — dernier succès le 09/11 à 21:35 · [voir](https://github.com/MaxMcNeil/Montage-LV-final/actions/runs/42782435254)
  - **Cause** : erreur dans le programme (pas un problème de quota ni de clé) (étape « montage → Montage (transcription, plan, médias, rendu) »)
  - **Quoi faire** : à corriger dans le code : transmets la ligne d'erreur ci-dessous
  - Message : `NameError: name 'R' is not defined`

<!-- workflows:end -->
