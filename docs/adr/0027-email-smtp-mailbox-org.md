# ADR-0027: E-Mail-Versand via mailbox.org SMTP (aiosmtplib)

- **Status:** beschlossen
- **Datum:** 2026-06-19
- **Betrifft:** `adapters/smtp`, `modules/accounts`, `kernel/ports/mail` · **Bezug:** KONZEPT §11 (E-Mail-Zustellbarkeit), §8 (Passwort-Reset), Roadmap Phase 1

## Kontext

Phase 1 braucht transaktionale E-Mails (Passwort-Reset jetzt, Adress-Verifikation als Folge).
Der Mail-Port (`kernel/ports/mail.py::MailPort.send(to, subject, body_md)`) und ein Null-Adapter
(`adapters/null::NullMail`, No-Op) existieren bereits, aber **kein realer Versand**. Der Betreiber hat
bereits einen SMTP-Zugang bei einem Anbieter (hier **mailbox.org**) mit verifizierter Versanddomain
(SPF/DKIM/DMARC vorhanden). Die App bootet ohne Mail (Null-Pfad); der reale Adapter darf den
Event-Loop nicht blockieren (FastAPI ist async).

## Entscheidung

**Realer Mail-Adapter via SMTP mit `aiosmtplib`** (`adapters/smtp/mail.py::SmtpMail`,
implementiert den Mail-Port strukturell). Versand über `smtp.mailbox.org:465` (implicit TLS) bzw.
`:587` (STARTTLS), Auth mit **vollständiger Adresse + (App-)Passwort**, Absender = verifizierte
mailbox.org-Domain (Anzeigename = `BRAND_NAME` aus Settings). **Null-Adapter/mailpit bleibt Default
in Dev/Tests** (mailpit ist in `docker-compose.dev.yml` vorhanden, Web-UI `:8025`). Die
Adapter-Auswahl ist **env-getrieben** im Composition-Root (`main.py` → `app.state.mail`); Module
beziehen den Port via DI (`kernel/ports/mail.py::get_mail` liest `app.state.mail` — **kein**
`modules→adapters`- oder `kernel→adapters`-Import, import-linter bleibt grün). **Graceful
Enhancement:** ein SMTP-Fehler wird geloggt (Referenzcode, **keine Empfänger/Inhalte**) und als
`False` zurückgegeben — die auslösende Operation (Reset-Token in Redis) bleibt konsistent, der
Versand ist Best-Effort. Secrets ausschließlich via `.env` (`CUSTODE_SMTP_*`), **nie ins Repo**.

E5 (neue Abhängigkeit): die stdlib `smtplib` ist **blockierend** und damit im async-FastAPI-Stack
ungeeignet (sie würde den Event-Loop anhalten); `aiosmtplib` ist der etablierte async-SMTP-Client.

## Konsequenzen

- **Positiv:** nutzt vorhandene mailbox.org-Infrastruktur (Domain + SPF/DKIM/DMARC) → „Boring
  Technology" (E8), kein neuer Provider-Account; sauber über den bestehenden Mail-Port; Dev/Tests
  bleiben offline (mailpit/Null); App bootet auch ohne Mail-Konfiguration.
- **Negativ / Kosten:** eine neue Backend-Abhängigkeit (`aiosmtplib`); Betrieb muss SPF/DKIM/DMARC
  der Versanddomain pflegen; SMTP-Secrets liegen in der Deployment-`.env` des Servers (außerhalb des Repos).
- **Auswirkungen:** `pyproject.toml` (+`aiosmtplib`); `settings.py` (`smtp_user/password/from/
  starttls`, `public_base_url` für Links); `main.py` wählt Adapter; `.env(.prod).example` +
  Compose um SMTP-Platzhalter ergänzt. Tests: Adapter-Unit (Null-Pfad + gemocktes `aiosmtplib.send`,
  Fehler→`False`); Reset-E2E mit Capturing-Mail (Token aus Body). **Keine Mail/Token in Logs.**

## Alternativen (verworfen, mit Begründung)

- **Transaktions-API (Postmark/Resend o. Ä.)** — bessere Zustellraten/Analytics, aber neuer Account
  + Abhängigkeit; mailbox.org ist vorhanden und genügt für Phase 1. Verworfen (E8).
- **stdlib `smtplib`** — keine neue Lib, aber **blockierend** im async-Stack (E5-Bedarf belegt).
  Verworfen.
- **Eigener Mailserver (Postfix o. Ä.)** — volle Kontrolle, aber Betriebs-/Reputationslast
  (Deliverability) ohne Mehrwert in Phase 1. Verworfen.
