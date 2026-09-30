"""capture — Quick-Capture „Zuruf" (KONZEPT §5.17), der offline Basispfad ohne LLM.

Ein Freitext-Zuruf wird vom deterministischen Regel-Parser in einen Vorschlag zerlegt und landet als
``capture`` in der Inbox; per 1-Tap-Triage wird er bestätigt (legt einen Posten/Task an) oder
verworfen. Importiert nur kernel/* und die PUBLIC api.py von shopping (Posten über den Sync-Batch)
und tasks (persönlichen Task anlegen) — nie deren Interna, nie ein anderes Modul. Kein Modul
importiert capture (einseitige Abhängigkeit, kein Zyklus). LLM-Anreicherung = Phase 7."""
