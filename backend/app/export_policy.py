"""Which tables a subject-rights export contains — assembled at the composition root.

The kernel mechanism (``kernel/export``) knows no table names; this module supplies them, exactly
as ``worker.py`` supplies the retention reaper's list (ADR-0039: cross-module wiring lives at the
composition root, never inside a module).

Every table in ``Base.metadata`` must appear either in :data:`EXPORTED` or in :data:`EXCLUDED`
**with a reason**. ``tests/test_export_policy.py`` walks the metadata and fails on anything
unclassified — a new table therefore cannot slip silently out of (or into) a person's export.

Three rules decide where a table goes:

1. **Betreiber-Ebene ist kein Haushaltsdatum.** Operator accounts, banners, global flags and the
   audit log describe *us*, not the household. (``audit_log`` additionally revokes SELECT from
   ``custode_app`` entirely, migration 0057 — the app role could not read it if it wanted to.)
2. **Transport ist kein Inhalt.** Outbox, dead letters, processed-event markers and sync
   idempotency rows are how data moved, not the data. They hold no statement about a person that
   is not already in the fact tables.
3. **Referenzdaten gehören niemandem.** The shared ingredient catalogue is the same for every
   household; exporting it would pad the file without telling the subject anything about
   themselves.
"""

from __future__ import annotations

from app.kernel.export import ExportPolicy, TableSpec

# --- Withheld values ---------------------------------------------------------------------------
# Four groups, and the reason differs per group — which is why this is a table→columns map and not
# a single "looks secret" pattern:
#   authenticators      a password/PIN/TOTP/recovery hash proves identity; handing it out invites
#                       offline cracking against an account that is still live
#   session credentials the refresh hash and the ICS feed token ARE the credential — the feed URL
#                       is an unauthenticated route whose only protection is the secret in it
#   third-party creds   creds_enc/tokens_enc are secrets the SERVER can use against someone else's
#                       system (a Nextcloud login, an Oura token). They are not the subject's data
#                       to receive in a ZIP; they are our decrypted liability
#   key material        the vault wrapping key. The vault ciphertext IS exported — it is the
#                       subject's data — but the key stays where it is decrypted: in the app
_REDACT: dict[str, frozenset[str]] = {
    "users": frozenset({"password_hash", "pin_hash", "totp_secret"}),
    "auth_recovery_codes": frozenset({"code_hash"}),
    "auth_sessions": frozenset({"refresh_hash"}),
    "calendar_feeds": frozenset({"token"}),
    "invites": frozenset({"code"}),
    "external_calendar_subscriptions": frozenset({"creds_enc"}),
    "wearable_connections": frozenset({"tokens_enc"}),
    "vault_key_envelopes": frozenset({"wrapped_key", "wrap_meta"}),
}

# --- The allow-list ----------------------------------------------------------------------------
# ``personal_columns`` ties a row to a person. Empty = the row belongs to the shared household and
# says nothing about one member, so it appears only in the household export. That distinction is
# the honest reading of Art. 15 ("data concerning him or her"): a shopping list is not a statement
# about whoever happened to add the milk.
EXPORTED: tuple[TableSpec, ...] = (
    # --- Konto & Haushalt ---
    TableSpec("households", shared=True),
    # Die Mitgliederliste IST Haushaltsdatum — wer dazugehört, sieht die App ohnehin.
    TableSpec("memberships", ("user_id",), shared=True),
    # Die users-Zeile dagegen nicht: E-Mail und settings_json sind die Sache der Person, und keine
    # API-Route zeigt sie einem Mitbewohner. Wer im Haushalt ist, sagt `memberships`.
    TableSpec("users", ("id",)),
    TableSpec("invites", shared=True),
    # Consent-Typen heißen `wearable_heartrate` — die blosse EXISTENZ der Zeile ist eine Aussage
    # über die Gesundheit dieser Person. ADR-0081 §6 hat genau das als Domain-Event abgelehnt.
    TableSpec("consents", ("subject_user_id",)),
    # --- Anmeldung & Geräte (RLS ist user-scoped; hier nochmal ausdrücklich) ---
    TableSpec("auth_sessions", ("user_id",)),
    TableSpec("auth_passkeys", ("user_id",)),
    TableSpec("auth_recovery_codes", ("user_id",)),
    TableSpec("auth_login_events", ("user_id",)),
    # --- Rezepte & Ernährung: der geteilte Bestand des Haushalts ---
    TableSpec("recipes", shared=True),
    TableSpec("recipe_ingredients", shared=True),
    TableSpec("meal_plans", shared=True),
    TableSpec("meal_slots", ("cook_id",), shared=True),
    # --- Einkauf: eine gemeinsame Liste, sonst wäre sie sinnlos ---
    TableSpec("shopping_lists", shared=True),
    TableSpec("shopping_items", ("created_by",), shared=True),
    TableSpec("shopping_basics", ("created_by",), shared=True),
    # --- Aufgaben & Ökonomie: der Haushalt sieht Aufgaben und Ledger, das ist der Sinn ---
    TableSpec("rooms", shared=True),
    TableSpec("task_templates", shared=True),
    TableSpec("task_instances", ("assigned_to", "done_by"), shared=True),
    # Ein Ledger-Eintrag betrifft die Person über SEINE KONTEN, nicht über `created_by` — wer die
    # Buchung angelegt hat, ist eine Nebensache; wem sie gutgeschrieben wurde, die Hauptsache.
    # Der Ledger ist Haushaltssache (das ist der Sinn der Ökonomie). Persönlich betrifft eine
    # Buchung aber die KONTEN, die sie berührt — nicht, wer sie angelegt hat: `created_by` ist bei
    # einer Gutschrift meist der Admin, die betroffene Person steht in `to_account`. Konten sind
    # Strings `member:<uuid>` (ADR-0035), deshalb der Textvergleich.
    TableSpec(
        "points_ledger",
        shared=True,
        personal_text_columns=("from_account", "to_account"),
        personal_text_prefix="member:",
    ),
    TableSpec("rewards", shared=True),
    TableSpec("redemptions", ("member_id",), shared=True),
    TableSpec("market_listings", ("seller_id", "buyer_id"), shared=True),
    # Persönliche Automatik-Regel, keine Haushaltsangelegenheit.
    TableSpec("auto_accept_rules", ("member_id",)),
    # --- Kalender ---
    # Zur Hälfte geteilt: die `household`-Ebene gehört allen, die `personal`-Ebene ihrem Owner.
    # Die RLS ist rein haushaltsweit (Migration 0032); die personal-Grenze zieht ADR-0040
    # ausschliesslich app-seitig (`_visible`, 404 in `get_event`). Ohne `shared_when` wäre der
    # Export der einzige Pfad im System, der daran vorbeigeht — und CalDAV-Spiegel landen als
    # `personal`, es ginge also um komplette Privatkalender.
    TableSpec("calendar_events", ("owner_id",), shared_when=("layer", "household")),
    # Das Feed-Token ist die Credential einer Person (redigiert), das Abo gehört ihr.
    TableSpec("calendar_feeds", ("member_id",)),
    # Das Modell sagt woertlich zu, dass auch ein ADMIN diese Zeile nie sieht. `creds_enc` ist
    # redigiert — aber die `caldav_url` traegt bei den ueblichen Anbietern den Fremdsystem-
    # Benutzernamen im Pfad, also genau die PII, die im Ciphertext bleiben sollte.
    TableSpec("external_calendar_subscriptions", ("member_id",)),
    TableSpec("weather_locations", shared=True),
    # --- Notizen, Nachrichten, Anleitungen ---
    TableSpec("notes", ("author_id",), shared=True),
    TableSpec("note_versions", shared=True),
    # Ein Brief geht an benannte Empfänger. `to_ids` ist ein Array — das Prädikat unten deckt nur
    # den Absender ab; die Empfänger-Seite kommt über `letter_reads`. Ein Admin, der nicht
    # adressiert ist, hat hier nichts zu lesen.
    TableSpec("letters", ("from_id",)),
    TableSpec("letter_reads", ("user_id",)),
    TableSpec("guides", ("author_id",), shared=True),
    TableSpec("guide_attachments", shared=True),
    TableSpec("comments", ("author_id",), shared=True),
    TableSpec("object_links", ("created_by",), shared=True),
    # --- Zuruf & Feedback: beides persönliche Posteingänge ---
    # Die Zuruf-Inbox ist Freitext, den jemand sich selbst diktiert hat.
    TableSpec("captures", ("member_id",)),
    # Der Meldekanal richtet sich womöglich GEGEN den Admin — ihn dort mitlesen zu lassen,
    # zerstört den Kanal. `diagnostics` haengt ausserdem am Geraet des Melders.
    TableSpec("feedback", ("author_id",)),
    # --- Vault: Ciphertext ja, wrappender Schlüssel nein (s. _REDACT) ---
    # Der Tresor gehört dem Haushalt (ein gemeinsamer Schlüssel, ADR-0067).
    TableSpec("vault_items", ("author_id",), shared=True),
    TableSpec("vault_key_envelopes", ("member_id",), shared=True),
    # --- Wearables (Art. 9): mitglieds-gescopte RLS haelt fremde Zeilen ohnehin fern ---
    TableSpec("wearable_connections", ("member_id",)),
    TableSpec("wearable_daily", ("member_id",)),
)

# --- Deliberately absent, with the reason -------------------------------------------------------
EXCLUDED: dict[str, str] = {
    "audit_log": (
        "Betreiber-Audit; custode_app hat darauf gar kein SELECT (Migration 0057) — beschreibt "
        "Betreiber-Zugriffe, nicht die Daten des Haushalts."
    ),
    "operators": "Betreiber-Konten — beschreiben uns, nicht den Haushalt.",
    "operator_passkeys": "Betreiber-Authentifikatoren.",
    "ops_banners": "Betreiber-Ansagen, kein Haushaltsdatum.",
    "global_flags": "Betreiber-Schalter, kein Haushaltsdatum.",
    "events_outbox": "Transport, kein Inhalt — die Fachzeile selbst ist enthalten.",
    "events_dlq": "Transport (nicht zustellbare Ereignisse), kein Inhalt.",
    "processed_events": "Idempotenz-Marker des Dispatchers, kein Inhalt.",
    "sync_client_ops": "Idempotenz-Marker des Sync-Batch, kein Inhalt.",
    "ingredients": "Geteilter Referenzkatalog — für jeden Haushalt identisch.",
    "ingredient_nutrition": "Geteilte Nährwert-Referenz — für jeden Haushalt identisch.",
    "tenancy_probe": (
        "Infrastruktur-Sonde aus Migration 0001: prüft die RLS-Maschinerie und dient als "
        "Spaltenvorlage für mandantengebundene Tabellen. Die Anwendung schreibt dort nie hinein, "
        "nur `tests/test_rls_probe.py`. Kein Nutzerdatum — aber `custode_app` DARF sie lesen, "
        "deshalb steht sie hier statt gar nicht (das Schema-Gate würde sie sonst melden)."
    ),
}

# --- Blob-Referenzen ----------------------------------------------------------------------------
# Welche exportierte Spalte auf eine Datei im Blob-Speicher zeigt. Der Router zieht daraus die
# Anhänge; ohne diesen Eintrag beschriebe der Export die Datei nur, ohne sie mitzugeben.
# ``tests/test_export_policy.py`` koppelt diese Tabelle an die Freigabeliste dort: eine Spalte,
# die dort als "Blob-Referenz" durchgewinkt wurde, MUSS hier stehen — sonst wäre sie stillschweigend
# als harmlos eingestuft und zugleich beim Export vergessen worden.
ATTACHMENT_COLUMNS: dict[str, str] = {
    "recipes": "photo_key",
    "guide_attachments": "storage_key",
}

POLICY = ExportPolicy(tables=EXPORTED, redact=_REDACT)
