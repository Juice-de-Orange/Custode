"""Was beim endgültigen Löschen einer Person mit jeder Zeile geschieht, die auf sie zeigt.

Art. 17 DSGVO, KONZEPT §5.1/§9. Zusammengestellt am Composition Root — der Kernel kennt keine
Modul-Tabellen (E2, ADR-0039), genau wie bei ``export_policy`` und ``_RETENTION_TABLES``.

**Der Ausgangsbefund, der die Form bestimmt.** Im echten Schema (nicht im ORM — das kennt 29
Spalten weniger) zeigen **31 Spalten** auf eine Person. Davon haben **vier** einen Fremdschlüssel
auf ``users``: drei mit ``ON DELETE CASCADE`` und ``memberships.user_id`` mit ``NO ACTION``, das
das Löschen der ``users``-Zeile aktiv **blockiert**. Die übrigen 27 sind ungesicherte Verweise —
nichts in der Datenbank hindert sie daran, ins Leere zu zeigen. Eine Löschkaskade kann sich hier
also auf **keine einzige** Fremdschlüssel-Regel verlassen; jede Spalte braucht eine Entscheidung.

**Und dann macht eine Entscheidung alles andere einfach.** Die ``users``-Zeile wird nicht gelöscht,
sondern **anonymisiert** (KONZEPT §5.1: Beiträge bleiben als „Ehemaliges Mitglied" stehen). Damit
bleibt jeder Verweis gültig: keine hängenden Referenzen, kein Nullen von ``NOT NULL``-Spalten, kein
Sentinel-Konto. Es bleiben genau zwei Antworten je Spalte:

- :data:`Disposal.delete` — die Zeile ist **über** die Person. Sie hat keinen Wert für den
  Haushalt und geht.
- :data:`Disposal.keep` — geteilter Inhalt oder ein Nachweis, der bestehen muss. Die Zeile bleibt
  und zeigt auf die anonymisierte ``users``-Zeile.

Ein dritter Wert, :data:`Disposal.operator`, ist keine Entscheidung, sondern eine Feststellung:
die Spalte verweist auf ``operators.id``, nicht auf ``users.id``. Sie steht trotzdem in der Liste,
weil Schweigen sonst wie eine Antwort aussähe.

**Vollständigkeit ist erzwungen, nicht dokumentiert.** ``tests/test_deletion_policy.py`` sucht im
**echten Schema** nach personenverdächtigen Spalten und macht CI rot, sobald eine unklassifiziert
ist. Das Gate läuft absichtlich nicht über ``Base.metadata``: das ORM ist nicht das Schema, und
genau in dieser Lücke saßen beim Export ``tenancy_probe`` und ``guides.search_tsv``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Disposal(StrEnum):
    """Was mit Zeilen geschieht, die über diese Spalte auf die gelöschte Person zeigen."""

    delete = "delete"
    keep = "keep"
    operator = "operator"


@dataclass(frozen=True)
class ColumnRule:
    """Eine Spalte, die auf eine Person zeigt — und was aus ihren Zeilen wird.

    ``reason`` ist Pflicht und wird vom Gate auf Substanz geprüft. „aus Gründen" ist keine
    Klassifizierung; wer eine Spalte hinzufügt, trifft eine DSGVO-Entscheidung und soll sie
    aufschreiben müssen.
    """

    table: str
    column: str
    disposal: Disposal
    reason: str


# --- Zeilen, die ÜBER die Person sind: sie gehen ------------------------------------------------
# Gemeinsamer Nenner: für den Haushalt haben sie keinen Wert, und ihr Fortbestand wäre allein eine
# Aussage über jemanden, der gelöscht werden will.
_DELETE: tuple[ColumnRule, ...] = (
    # Anmeldung und Geräte. Die drei mit CASCADE würden ohnehin mitfallen — sie stehen hier, weil
    # eine Kaskade, auf die man sich verlässt, ohne sie geprüft zu haben, dieselbe Klasse Fehler
    # ist wie eine Liste, die etwas über die Datenbank behauptet.
    ColumnRule("auth_sessions", "user_id", Disposal.delete, "Sitzung der Person (FK CASCADE)"),
    ColumnRule("auth_passkeys", "user_id", Disposal.delete, "Anmeldedaten der Person (FK CASCADE)"),
    ColumnRule(
        "auth_recovery_codes", "user_id", Disposal.delete, "Anmeldedaten der Person (FK CASCADE)"
    ),
    ColumnRule(
        "auth_login_events",
        "user_id",
        Disposal.delete,
        "Anmelde-Historie — user-scoped, ohne Haushaltsbezug, reine Aussage über die Person",
    ),
    # Die Mitgliedschaft blockiert das Löschen der users-Zeile nicht mehr, weil die stehen bleibt;
    # sie geht trotzdem: nach dem Austritt ist sie ein Tombstone ohne Aussage.
    ColumnRule(
        "memberships",
        "user_id",
        Disposal.delete,
        "beim Austritt bereits getombstonet; der Verbleib im Haushalt endet endgültig",
    ),
    # Persönliche Fächer. Keines davon ist je für andere sichtbar gewesen.
    ColumnRule("captures", "member_id", Disposal.delete, "persönlicher Eingangskorb"),
    ColumnRule("auto_accept_rules", "member_id", Disposal.delete, "persönliche Automatik-Regel"),
    ColumnRule(
        "calendar_feeds",
        "member_id",
        Disposal.delete,
        "der ICS-Token IST die Zugangskontrolle (ADR-0042) — er darf nichts überleben",
    ),
    ColumnRule(
        "external_calendar_subscriptions",
        "member_id",
        Disposal.delete,
        "Abo mit verschlüsselten Fremdsystem-Zugangsdaten, ausschließlich der Person zugeordnet",
    ),
    ColumnRule(
        "vault_key_envelopes",
        "member_id",
        Disposal.delete,
        "der persönliche Schlüsselumschlag der Person zum Haushalts-Tresor",
    ),
    ColumnRule("letter_reads", "user_id", Disposal.delete, "wer wann welchen Brief gelesen hat"),
    # Art. 9. Beim Austritt schon hart gelöscht — hier nochmal, weil eine Löschkaskade sich nicht
    # darauf verlassen darf, dass ein vorheriger Schritt gelaufen ist.
    ColumnRule(
        "wearable_connections", "member_id", Disposal.delete, "Art. 9 — Gesundheitsdaten, hart"
    ),
    ColumnRule("wearable_daily", "member_id", Disposal.delete, "Art. 9 — Gesundheitsdaten, hart"),
)

# --- Zeilen, die bleiben: geteilter Inhalt und Nachweise ----------------------------------------
# Sie zeigen danach auf die anonymisierte ``users``-Zeile und rendern als „Ehemaliges Mitglied".
_KEEP: tuple[ColumnRule, ...] = (
    # Der Ledger ist append-only und doppelt geführt (ADR-0035). Eine Buchung zu löschen veränderte
    # die Salden ANDERER — der Danke-Punkt gehört beiden Seiten. Deshalb steht `points_ledger` auch
    # ausdrücklich nicht in der Retention-Liste (app/worker.py).
    ColumnRule(
        "points_ledger",
        "created_by",
        Disposal.keep,
        "append-only Doppelbuchung — ein Löschen veränderte fremde Salden",
    ),
    ColumnRule(
        "redemptions", "member_id", Disposal.keep, "Einlösung hängt am Ledger, siehe points_ledger"
    ),
    ColumnRule(
        "market_listings", "seller_id", Disposal.keep, "Handelshistorie hängt am Ledger-Escrow"
    ),
    ColumnRule("market_listings", "buyer_id", Disposal.keep, "dito, Käuferseite"),
    # Beiträge zum gemeinsamen Bestand. KONZEPT §5.1 nennt sie wörtlich: sie bleiben, der Name
    # wird pseudonym.
    ColumnRule("shopping_items", "created_by", Disposal.keep, "Beitrag zur gemeinsamen Liste"),
    ColumnRule("shopping_items", "checked_by", Disposal.keep, "Beitrag zur gemeinsamen Liste"),
    ColumnRule("shopping_items", "reserved_by", Disposal.keep, "Beitrag zur gemeinsamen Liste"),
    ColumnRule("shopping_basics", "created_by", Disposal.keep, "gemeinsamer Grundvorrat"),
    ColumnRule("task_instances", "done_by", Disposal.keep, "erledigte Aufgabe des Haushalts"),
    ColumnRule("note_versions", "edited_by", Disposal.keep, "Versionsgeschichte einer Notiz"),
    ColumnRule("guide_attachments", "uploaded_by", Disposal.keep, "Anhang einer Anleitung"),
    ColumnRule("object_links", "created_by", Disposal.keep, "Verknüpfung zwischen Objekten"),
    # Kalender: der Haushalts-Layer ist gemeinsamer Bestand, der persönliche nicht. Die Trennung
    # kann keine Spaltenregel ausdrücken — sie steht als eigene Bedingung in PERSONAL_EVENTS.
    ColumnRule(
        "calendar_events",
        "owner_id",
        Disposal.keep,
        "Haushalts-Termine bleiben; persönliche gehen über PERSONAL_EVENT_CONDITION",
    ),
    # Nachweise. Der Consent-Ledger ist der Beleg, dass eine Einwilligung vorlag und widerrufen
    # wurde — ihn zu löschen entzöge dem Haushalt (und uns) genau die Rechtsgrundlage-Historie,
    # die Art. 7 Abs. 1 verlangt. Er zeigt danach auf eine anonyme Zeile.
    ColumnRule(
        "consents", "subject_user_id", Disposal.keep, "Art. 7 Abs. 1 — Nachweis der Einwilligung"
    ),
    ColumnRule(
        "consents", "granted_by", Disposal.keep, "Art. 7 Abs. 1 — wer sie erteilt hat (Eltern)"
    ),
    # --- Urheberschaft am gemeinsamen Bestand ---------------------------------------------------
    # Diese neun Spalten hat die erste Fassung des Gates **übersehen**: sein Namensmuster kannte
    # `user_id`/`member_id`/`_by`, aber kein `author_id`, `from_id`, `cook_id`, `contact_id`. Ein
    # Muster, das „absichtlich zu breit" heißt, muss zu breit *bewiesen* werden — seitdem prüft das
    # Gate **jede** `_id`-Spalte und verlangt eine Einordnung (Person oder Sachbezug).
    ColumnRule("notes", "author_id", Disposal.keep, "Notiz des Haushalts, KONZEPT §5.1"),
    ColumnRule("comments", "author_id", Disposal.keep, "Kommentar am gemeinsamen Objekt"),
    ColumnRule("guides", "author_id", Disposal.keep, "Anleitung des Haushalts"),
    ColumnRule(
        "guides", "contact_id", Disposal.keep, "Ansprechpartner einer Anleitung (S-12), nur Verweis"
    ),
    ColumnRule("vault_items", "author_id", Disposal.keep, "Tresor-Eintrag gehört dem Haushalt"),
    ColumnRule("meal_slots", "cook_id", Disposal.keep, "wer kocht — Teil des Wochenplans"),
    # Der Brief bleibt bei seinen Empfängern; er ist adressierte Post, nicht Bestand des Absenders.
    ColumnRule("letters", "from_id", Disposal.keep, "Absender eines zugestellten Briefs"),
    ColumnRule(
        "letters",
        "to_ids",
        Disposal.keep,
        "Empfängerliste (uuid[]) — historisch; eine Spaltenregel trifft Arrays ohnehin nicht",
    ),
    # Rückmeldung an den Betreiber: eine persönliche Mitteilung, kein Haushaltsbestand. Sie zu
    # behalten diente uns, nicht der Person, die gerade Löschung verlangt hat.
    ColumnRule("feedback", "author_id", Disposal.delete, "persönliche Mitteilung an den Betreiber"),
)

# --- `_id`-Spalten, die auf eine SACHE zeigen, nicht auf eine Person -----------------------------
# Sie stehen hier, damit das Gate **jede** `_id`-Spalte einfordern kann: eine unbekannte Spalte muss
# eingeordnet werden — als Person oder ausdrücklich als Sachbezug. Vorher genügte ein Name, der
# nicht ins Namensmuster passte, um durchzurutschen; genau so sind neun Personenbezüge
# durchgerutscht, gefunden erst beim Schreiben des E2E-Tests.
NOT_A_PERSON: dict[str, str] = {
    "household_id": "Mandant, keine Person",
    "id": "Primärschlüssel",
    "list_id": "Einkaufsliste",
    "letter_id": "Brief",
    "note_id": "Notiz",
    "plan_id": "Wochenplan",
    "recipe_id": "Rezept",
    "room_id": "Raum",
    "template_id": "Aufgaben-Vorlage",
    "reward_id": "Belohnung",
    "ingredient_id": "Zutat aus dem gemeinsamen Katalog",
    "subscription_id": "CalDAV-Abo",
    "guide_id": "Anleitung",
    "object_id": "polymorpher Verweis auf ein Fachobjekt",
    "src_id": "Quelle einer Objekt-Verknüpfung",
    "dst_id": "Ziel einer Objekt-Verknüpfung",
    "event_id": "Outbox-Ereignis",
    "task_instance_id": "Aufgaben-Instanz hinter einem Listing",
    "ref_id": "Fachereignis, auf das eine Buchung verweist (ADR-0035)",
    "operator_id": "Betreiber-Konto, kein Haushaltsmitglied",
    "credential_id": "WebAuthn-Credential-Kennung, kein Personenverweis",
    "family_id": "Login-Familie einer Sitzung — die Zeile selbst trägt user_id",
    "client_op_id": "Idempotenz-Marke eines Sync-Batches",
    "request_id": "Korrelations-Kennung einer HTTP-Anfrage",
    "target_id": "Ziel eines Betreiber-Zugriffs im Audit — Haushalt, nicht Person",
}

# --- Keine Mitgliederbezüge: sie zeigen auf operators.id ----------------------------------------
_OPERATOR: tuple[ColumnRule, ...] = (
    ColumnRule("audit_log", "actor_id", Disposal.operator, "Betreiber, nicht Haushaltsmitglied"),
    ColumnRule("global_flags", "updated_by", Disposal.operator, "Betreiber-Konsole"),
    ColumnRule("ops_banners", "created_by", Disposal.operator, "Betreiber-Konsole"),
)

RULES: tuple[ColumnRule, ...] = _DELETE + _KEEP + _OPERATOR


@dataclass(frozen=True)
class ConditionalDelete:
    """Eine Tabelle, in der **ein Teil** der Zeilen der Person allein gehört.

    Eine Spaltenregel kann das nicht ausdrücken — sie kennt nur „alle Zeilen mit diesem Verweis".
    Statt das Modell zu biegen, steht der Sonderfall ausdrücklich daneben: das ist genau eine
    Tabelle, und wenn eine zweite dazukommt, soll sie sichtbar dazukommen.
    """

    table: str
    column: str
    condition: tuple[str, str]
    reason: str


CONDITIONAL_DELETES: tuple[ConditionalDelete, ...] = (
    ConditionalDelete(
        "calendar_events",
        "owner_id",
        ("layer", "personal"),
        "persönliche Termine sind für Mitbewohner ein 404 (ADR-0040) — sie gehören der Person "
        "allein. Haushalts-Termine bleiben als gemeinsamer Bestand stehen.",
    ),
)

# Jede Tabelle, aus der der Purge Zeilen entfernt. Der Job braucht darauf DELETE als
# ``custode_maint`` — und Postgres prüft Tabellenrechte beim **Planen**, nicht beim Treffer: eine
# fehlende Berechtigung lässt die Anweisung scheitern, auch wenn es gar nichts zu löschen gäbe.
# Genau daran ist der Retention-Reaper monatelang gestorben (BUGLOG 2026-07-31). Die Liste wird
# deshalb in ``test_purge_grants.py`` gegen die echte Datenbank geprüft, nicht geglaubt.
# Aus der BEDEUTUNG abgeleitet (``disposal``), nicht aus der Gruppierung ``_DELETE``. Die erste
# Fassung las das Tupel — und übersah prompt die eine `delete`-Regel, die aus Lesbarkeitsgründen
# weiter unten steht. Ein Test hat es gefangen; ohne ihn wäre `feedback` nie geleert worden und
# hätte dabei ausgesehen wie eine Tabelle ohne Zeilen.
PURGED_TABLES: tuple[str, ...] = tuple(
    dict.fromkeys(
        [rule.table for rule in RULES if rule.disposal is Disposal.delete]
        + [rule.table for rule in CONDITIONAL_DELETES]
    )
)

# --- Was aus der users-Zeile selbst wird --------------------------------------------------------
# Sie bleibt, damit die Verweise oben gültig bleiben — und wird ausgeräumt. Der Anzeigename wird
# NICHT auf „Ehemaliges Mitglied" gesetzt: das fröre einen deutschen Anzeigetext in der Datenbank
# ein (CLAUDE.md verbietet hartcodierte Anzeigetexte, DE+EN via i18n) und machte ihn zum Zeitpunkt
# der Löschung unveränderlich. Stattdessen wird er geleert; der Zustand „gelöscht" ergibt sich aus
# `purged_at`, und die Oberfläche rendert daraus ihren Ersatztext.
#
# Die Werte sind gegen das **echte** Schema geprüft (``test_deletion_policy``): ``locale`` und
# ``totp_enabled`` sind ``NOT NULL``, ein ``None`` darauf wäre erst zur Laufzeit aufgefallen —
# beim Purge, nachts, im Cron. ``locale`` bleibt deshalb unangetastet: es ist eine
# Darstellungseinstellung, kein Personenbezug.
ANONYMISE_USER: dict[str, object] = {
    "email": None,
    "username": None,
    "display_name": "",
    "password_hash": None,
    "pin_hash": None,
    "totp_secret": None,
    "totp_enabled": False,
    "settings_json": {},
    "email_verified_at": None,
}
