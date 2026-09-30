"""``wearables`` — Wearable-Anbindung (KONZEPT §5.15), Phase 9.

Grenzen: importiert nur ``kernel/*`` und die Naht ``modules/accounts/api`` (Consent-Ledger +
Rollenprüfung). Liest nie fremde Tabellen, publiziert keine haushaltsweiten Events.

Art. 9 DSGVO: Gesundheitsdaten sind mitglieds-privat, nicht haushalts-privat — die RLS in
Migration 0069 erzwingt ``member_id``, nicht nur ``household_id`` (N-2, ADR-0081).
"""
