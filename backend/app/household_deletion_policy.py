"""Was beim endgültigen Ausräumen eines aufgelösten Haushalts mit jeder Tabelle geschieht.

Art. 17 DSGVO, KONZEPT §5.1, ADR-0085 §7 und ADR-0086. Zusammengestellt am Composition Root — der
Kernel kennt keine Modul-Tabellen (E2, ADR-0039), wie bei ``deletion_policy`` und ``export_policy``.

**Der Ausgangsbefund, gegen die echte Datenbank gemessen (2026-08-02).** **41** Tabellen tragen
``household_id``, und **kein einziger** Fremdschlüssel zeigt auf ``households.id``. Das Löschen der
Haushaltszeile kaskadiert nichts und wird von nichts blockiert: **die Datenbank kann eine vergessene
Tabelle nie melden.** Beim Konto-Purge blockiert wenigstens ``memberships.user_id``; hier gibt es
kein solches Netz.

**Deshalb wird die Menge abgeleitet, nicht gepflegt** (ADR-0085 §7). Zur Laufzeit fragt
``kernel/deletion/household`` den Katalog nach allen Tabellen mit ``household_id``. Eine
handgeschriebene Liste wäre exakt ``_RETENTION_TABLES`` (BUGLOG 2026-07-31), nur mit 41 statt 3
Einträgen — eine Behauptung über die Datenbank, die niemand prüft.

**Gepflegt wird nur diese Datei: die Einordnung je Tabelle.** Das ist eine DSGVO-Entscheidung,
keine Schema-Tatsache. Und sie fällt **geschlossen aus**: eine abgeleitete Tabelle, die hier fehlt,
lässt den Lauf scheitern (``UnclassifiedTableError``). Beide möglichen Vermutungen wären falsch —
löschen zerstörte Daten, über die niemand entschieden hat; überspringen ließe personenbezogene
Zeilen liegen und meldete trotzdem Erfolg.

**Zwei Einordnungen sind Entscheidungen, keine Ableitungen** (Betreiber, 2026-08-02, ADR-0086):

* ``points_ledger`` wird **gelöscht**, obwohl ``CLAUDE.md`` ihn „append-only" nennt. Append-only
  regelt **Korrekturen im lebenden Ledger** — eine Buchung wird nie überschrieben, sondern
  gegengebucht. 11-S1b lässt Restpunkte deshalb als *Buchung* verfallen statt sie zu löschen: weil
  jede Buchung zwei Konten hat und ein Löschen die Salden **anderer** verschöbe. Nach der Auflösung
  gibt es keine anderen Salden mehr, die stimmen müssten. Der Ledger trägt ``member_id``, ist also
  personenbezogen, und keine Aufbewahrungspflicht steht dagegen (Punkte sind kein Geld).
* Die ``households``-Zeile selbst wird **gelöscht**, nicht anonymisiert. Ihr Fehlen *ist* die
  Markierung „ausgeräumt" — es braucht keine zweite Spalte, die dasselbe behauptet, und damit keine
  Migration. Der Unterschied zur ``users``-Zeile (die anonymisiert stehen bleibt) ist kein
  Widerspruch, sondern folgt aus derselben Frage: dort halten 27 Verweise ohne Fremdschlüssel die
  Zeile am Leben, hier zeigt **nichts** auf sie.

**Es braucht keine Grant-Migration.** Ein Trockenlauf als ``custode_app`` unter gesetztem Scope
(2026-08-02) zeigt: 40 von 42 Zielen lassen ein ``DELETE`` zu; genau ``audit_log`` und ``consents``
scheitern mit ``42501`` — und beide bleiben ohnehin. Der Trockenlauf steht trotzdem als Gate in
``tests/test_household_purge.py``: Postgres prüft Rechte beim **Planen**, nicht beim Treffer, und
genau daran sind Reaper (BUGLOG 2026-07-31) und Konto-Purge beinahe gestorben.
"""

from __future__ import annotations

from app.kernel.deletion.household import HouseholdPurgeSpec

# --------------------------------------------------------------------------------- gelöscht
# Alles, was der aufgelöste Haushalt besaß. Gruppiert wie die Module, damit ein neues Modul beim
# Lesen auffällt — die Wirkung hängt aber an der Menge, nicht an der Gruppierung (der Konto-Purge
# hat gelernt, was passiert, wenn man aus der Gruppierung ableitet statt aus der Bedeutung).

_DELETE: dict[str, str] = {
    # accounts
    "memberships": "Die Mitgliedschaften des Haushalts; ohne ihn haben sie keinen Gegenstand.",
    "invites": "Einladungen in einen Haushalt, den es nicht mehr gibt.",
    # economy
    "points_ledger": (
        "Punkte-Buchungen. Personenbezug ueber die Kontostrings `member:<uuid>` und `created_by` "
        "(die Tabelle hat keine `member_id`-Spalte). Append-only regelt Korrekturen im lebenden "
        "Ledger, nicht das Ende des Mandanten (ADR-0086 §6)."
    ),
    "rewards": "Belohnungskatalog des Haushalts.",
    "redemptions": "Einlösungen; personenbezogen über member_id.",
    "market_listings": "Marktplatz-Angebote samt Escrow-Bezug; der Markt endet mit dem Haushalt.",
    # tasks
    "rooms": "Räume des Haushalts.",
    "task_templates": "Aufgaben-Vorlagen des Haushalts.",
    "task_instances": "Aufgaben-Instanzen; tragen assignee_id, also einen Personenbezug.",
    "auto_accept_rules": "Übernahme-Regeln einzelner Mitglieder.",
    # shopping
    "shopping_lists": "Einkaufslisten des Haushalts.",
    "shopping_items": "Posten; tragen added_by/checked_by.",
    "shopping_basics": "Basics-Liste des Haushalts.",
    "sync_client_ops": "Idempotenz-Marker des Sync-Batch — Transport, kein Fachbestand.",
    # recipes
    "recipes": "Rezepte des Haushalts, inklusive importierter Fremdrezepte.",
    "recipe_ingredients": "Zutatenzeilen; hängen an den Rezepten.",
    # calendar
    "calendar_events": "Termine, auch persönliche (ADR-0040) und gespiegelte CalDAV-Ereignisse.",
    "calendar_feeds": "ICS-Feed-Token; sie sind die einzige Zugangskontrolle dieser Route.",
    "external_calendar_subscriptions": (
        "CalDAV-Abos samt verschlüsselten Zugangsdaten zu Fremdsystemen."
    ),
    # mealplanner
    "meal_plans": "Wochenpläne des Haushalts.",
    "meal_slots": "Slots; hängen an den Wochenplänen und tragen cook_id.",
    # weather
    "weather_locations": "Grober Standort des Haushalts.",
    # notes / guides / messaging / comments / links
    "notes": "Notizen des Haushalts.",
    "note_versions": "Versions-Historie der Notizen.",
    "guides": "Anleitungen des Haushalts.",
    "guide_attachments": "Anhänge der Anleitungen (Blob-Schlüssel; die Bytes räumt der Storage).",
    "letters": "Briefe zwischen Mitgliedern — Inhalt, nicht Nachweis.",
    "letter_reads": "Gelesen-Status je Brief und Person.",
    "comments": "Kommentare an Objekten des Haushalts.",
    "object_links": "Verknüpfungen zwischen Objekten des Haushalts.",
    # vault
    "vault_items": "Tresor-Einträge; der Server hält nur Ciphertext, gelöscht wird er trotzdem.",
    "vault_key_envelopes": "Schlüssel-Umschläge je Mitglied.",
    # capture
    "captures": "Zuruf-Eingänge samt Freitext.",
    # wearables (Art. 9 — mitglieds-gescopte RLS, s. ADR-0081)
    "wearable_connections": "Verbindung zu einem Gesundheits-Anbieter, Art. 9.",
    "wearable_daily": "Gesundheits-Messwerte, Art. 9.",
    # feedback
    "feedback": (
        "Rückmeldungen an den Betreiber samt Freitext. Der Konto-Purge räumt sie ebenfalls "
        "(deletion_policy: feedback.author_id -> delete); zwei verschiedene Antworten wären ein "
        "Widerspruch, den der Export-nach-Löschung-Test findet."
    ),
    # events / infrastruktur
    "events_outbox": "Transactional Outbox — Transport, kein Fachbestand.",
    "events_dlq": "Dead-Letter-Queue derselben Ereignisse.",
    "tenancy_probe": "Prüftabelle der RLS-Negativtests; hält nur Testzeilen.",
}

# ---------------------------------------------------------------------------------- behalten
# Zwei Tabellen bleiben — und beide sind für ``custode_app`` ohnehin gesperrt, die Einordnung ist
# also nicht nur eine Zusage, sondern von der Datenbank gedeckt.

_KEEP: dict[str, str] = {
    "audit_log": (
        "Betreiber-Audit. ADR-0084: bei Löschung wird pseudonymisiert statt gelöscht, und "
        "household_id bleibt ausdrücklich stehen, weil sie den Haushalt bezeichnet und nicht die "
        "Person. custode_app hat darauf seit Migration 0057 weder SELECT noch DELETE."
    ),
    "consents": (
        "Einwilligungs-Ledger, Art. 7 Abs. 1: der Verantwortliche muss nachweisen können, dass "
        "eingewilligt wurde — gerade für die Art.-9-Verarbeitung, die hier gerade endet. Löschte "
        "man ihn mit, verschwände der Beleg für die Rechtmäßigkeit dessen, was vorher geschah. "
        "Der Personenbezug wird beim KONTO-Purge entschieden, nicht hier. custode_app darf auf "
        "consents nur SELECT und INSERT (Migration 0013) — append-only ist dort DB-erzwungen."
    ),
}


def _assert_disjoint() -> None:
    overlap = sorted(set(_DELETE) & set(_KEEP))
    if overlap:  # pragma: no cover - Konstruktionsfehler, beim Import laut
        raise ValueError(f"Tabelle doppelt eingeordnet: {', '.join(overlap)}")


_assert_disjoint()

DELETE_REASONS: dict[str, str] = dict(_DELETE)
KEEP_REASONS: dict[str, str] = dict(_KEEP)

POLICY = HouseholdPurgeSpec(
    delete_tables=frozenset(_DELETE),
    keep_tables=frozenset(_KEEP),
)
