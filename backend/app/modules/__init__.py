"""Domain modules (Phase 1+).

Each module is a Python package ``app/modules/<name>/`` with its own router,
service layer, models, tests and docs. Hard rules (CLAUDE.md / ARCHITECTURE §4),
enforced by import-linter:

- A module imports ONLY ``app.kernel.*`` — never another module.
- No cross-module DB joins, no reading another module's tables.
- Cross-module needs go through domain events or the target module's exported
  service interface (``app/modules/<x>/api.py``).

Phase 0 keeps this package empty on purpose."""
