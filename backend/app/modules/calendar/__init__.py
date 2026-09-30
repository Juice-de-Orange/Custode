"""calendar — persönlicher + Haushaltskalender (KONZEPT §5.11, Phase 5).

Importiert nur kernel/*, nie ein anderes Modul. Events sind household-scoped (RLS); die
Layer-Trennung (``household`` für alle Mitglieder, ``personal`` nur für den Ersteller) wird
query-seitig erzwungen (ADR-0040), RLS bleibt tenant-only. Schreibpfad = PATCH+If-Match (ADR-0034).
RRULE-Serien, ICS-Im/Export und die Scheduling-Engine bauen in späteren Slices darauf auf."""
