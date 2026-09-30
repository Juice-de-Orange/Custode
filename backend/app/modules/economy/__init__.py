"""economy — Punkte-Ökonomie des Haushalts (KONZEPT §5.9): append-only Doppelbuchungs-Ledger.

Importiert nur kernel/*. Andere Module buchen via economy.api (synchron, ADR-0035); economy liest
nie fremde Tabellen und importiert nie ein anderes Modul."""
