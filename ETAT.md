# État — Montage-LV-final

Ce qui bloque, pourquoi, quand ça se débloque et quoi faire.

<!-- workflows:start -->
## Workflows

_Vérifié le 29/10/2026 à 22:18 (heure italienne), automatiquement à la fin de chacun de tes lancements (aucune exécution planifiée)._

- ❌ **Montage final** : dernier lancement en échec (29/10 à 22:17, failure) — dernier succès le 27/10 à 18:19 · [voir](https://github.com/MaxMcNeil/Montage-LV-final/actions/runs/40952371400)
  - **Cause** : clé ou jeton refusé par Google Drive (invalide, expiré ou supprimé) (étape « 🔗 Chaîne — lancer les Shorts → Lancer Video to Shorts (Push-overlay) puis vider montage-joints »)
  - **Quoi faire** : vérifie / renouvelle le secret de Google Drive dans Settings → Secrets
  - Message : `status: '401'`

<!-- workflows:end -->
