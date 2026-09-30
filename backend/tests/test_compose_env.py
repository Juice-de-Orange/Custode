"""Guard the compose <-> Settings seam (BUGLOG 2026-06-17, wiederholt 2026-07-26).

Zweimal hat dieselbe Fehlerklasse zugeschlagen: eine neue Settings-Abhaengigkeit wurde in den
Test-Fixtures gesetzt, aber nicht in den Compose-Dateien — CI gruen, Prod still kaputt. Die
Fixtures beweisen, dass der CODE die Einstellung liest; niemand bewies, dass sie den CONTAINER
erreicht. Diese Datei ist die fehlende Haelfte.

Bewusst reiner Text/YAML-Test: kein Docker, keine DB, laeuft in Millisekunden und ist damit im
selben CI-Gate wie ruff/mypy. Die Soll-Listen sind ABSICHTLICH explizit — eine neue Variable
soll eine bewusste Entscheidung erzwingen ("welche Services brauchen die?"), nicht automatisch
durchrutschen.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
PROD = REPO_ROOT / "docker-compose.prod.yml"
DEV = REPO_ROOT / "docker-compose.dev.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.prod.example"

# Services, die den Python-Code fahren (web = Caddy, postgres/redis = Fremd-Images).
APP_SERVICES = ("api", "worker", "scheduler")

# Was auf Prod je Service gesetzt sein MUSS. Fehlt hier etwas, laeuft die Funktion still im
# Null-/503-Pfad statt zu krachen — genau der Fehler, den dieser Test verhindert.
REQUIRED_PROD: dict[str, set[str]] = {
    "api": {
        "CUSTODE_ENV",
        "CUSTODE_DATABASE_URL",
        "CUSTODE_DATABASE_URL_ADMIN",
        # Ohne MAINT faellt maint_session auf custode_app zurueck -> Login bricht (BUGLOG).
        "CUSTODE_DATABASE_URL_MAINT",
        # Betreiber-Grenze auf DB-Ebene (ADR-0015/0071); leer => Fallback auf custode_app.
        "CUSTODE_DATABASE_URL_OPS",
        "CUSTODE_DATABASE_URL_OPS_ACTIONS",
        "CUSTODE_REDIS_URL",
        # ADR-0077: ohne Key antworten CalDAV-Credentials-Writes 503 crypto_unconfigured.
        "CUSTODE_CRYPTO_KEY",
        "CUSTODE_CALDAV_SYNC_ENABLED",
        "CUSTODE_CALDAV_ALLOW_PRIVATE_URLS",
        "CUSTODE_SMTP_HOST",
        "CUSTODE_PUBLIC_BASE_URL",
        "CUSTODE_STORAGE_DIR",
        # Build-Info der /ops-Konsole — sonst unknown / 0.0.0.
        "CUSTODE_GIT_SHA",
        "CUSTODE_APP_VERSION",
        # Wearables (ADR-0081): die api braucht den Kill-Switch + Credentials fuer /authorize.
        "CUSTODE_OURA_ENABLED",
        "CUSTODE_OURA_CLIENT_ID",
        "CUSTODE_OURA_CLIENT_SECRET",
    },
    "worker": {
        "CUSTODE_ENV",
        "CUSTODE_DATABASE_URL",
        "CUSTODE_DATABASE_URL_MAINT",
        "CUSTODE_REDIS_URL",
        # Der worker faehrt den CalDAV-Cron (app/worker.py).
        "CUSTODE_CRYPTO_KEY",
        "CUSTODE_CALDAV_SYNC_ENABLED",
        "CUSTODE_CALDAV_ALLOW_PRIVATE_URLS",
        # ... und den Wochen-Digest-Cron: ohne SMTP faellt smtp_host auf den Default
        # "localhost" zurueck und der Versand laeuft ins Leere.
        "CUSTODE_SMTP_HOST",
        "CUSTODE_PUBLIC_BASE_URL",
        # Feedback -> GitHub Issues wird im WORKER komponiert (Outbox-Handler), nicht in der api.
        "CUSTODE_GITHUB_TOKEN",
        "CUSTODE_GITHUB_REPO",
        # ... und der naechtliche Wearable-Ingest + die 90-Tage-Retention laufen hier.
        "CUSTODE_OURA_ENABLED",
        "CUSTODE_OURA_CLIENT_ID",
        "CUSTODE_OURA_CLIENT_SECRET",
        "CUSTODE_WEARABLE_RAW_RETENTION_DAYS",
    },
    "scheduler": {
        "CUSTODE_ENV",
        "CUSTODE_DATABASE_URL",
        "CUSTODE_DATABASE_URL_MAINT",
        "CUSTODE_REDIS_URL",
        "CUSTODE_CRYPTO_KEY",
    },
}

# Integrations-Schalter, die in beiden Umgebungen bewusst gesetzt sein muessen. Dev und Prod
# duerfen unterschiedliche WERTE haben (Radicale im Compose-Netz vs. oeffentliches Nextcloud),
# aber nicht "in dev gesetzt, in prod vergessen" — so entstand die Luecke.
REQUIRED_BOTH_ENVS = {"CUSTODE_CRYPTO_KEY", "CUSTODE_CALDAV_ALLOW_PRIVATE_URLS"}


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    return data


def _env_keys(compose: dict[str, Any], service: str) -> set[str]:
    """Environment-Keys eines Service. Compose erlaubt Mapping und Liste (KEY=VAL)."""
    env = compose["services"][service].get("environment", {})
    if isinstance(env, dict):
        return set(env)
    return {str(item).split("=", 1)[0] for item in env}


@pytest.mark.parametrize("service", APP_SERVICES)
def test_prod_service_has_required_env(service: str) -> None:
    missing = REQUIRED_PROD[service] - _env_keys(_load(PROD), service)
    assert not missing, (
        f"docker-compose.prod.yml: Service '{service}' fehlen {sorted(missing)}. "
        "Eine neue Settings-Abhaengigkeit MUSS in ALLE Compose-Dateien (BUGLOG 2026-06-17), "
        "sonst ist CI gruen und Prod still kaputt."
    )


@pytest.mark.parametrize("service", APP_SERVICES)
def test_prod_env_names_match_settings_fields(service: str) -> None:
    """Ein vertippter Variablenname ist genauso still wie ein fehlender.

    ``CUSTODE_CRYPTO_KEYY`` wuerde von pydantic-settings ignoriert; der Container startet, das
    Feature bleibt aus. Deshalb: jeder ``CUSTODE_*``-Key muss auf ein echtes Settings-Feld zeigen.
    """
    fields = Settings.model_fields
    unknown = {
        key
        for key in _env_keys(_load(PROD), service)
        if key.startswith("CUSTODE_") and key.removeprefix("CUSTODE_").lower() not in fields
    }
    assert not unknown, (
        f"docker-compose.prod.yml: Service '{service}' setzt {sorted(unknown)} — "
        "kein passendes Feld in app/settings.py (Tippfehler? Feld umbenannt?)."
    )


@pytest.mark.parametrize("key", sorted(REQUIRED_BOTH_ENVS))
def test_integration_switches_set_in_dev_and_prod(key: str) -> None:
    dev, prod = _load(DEV), _load(PROD)
    for service in APP_SERVICES:
        assert key in _env_keys(dev, service), f"docker-compose.dev.yml: '{service}' fehlt {key}"
        assert key in _env_keys(prod, service), (
            f"docker-compose.prod.yml: '{service}' fehlt {key} — in dev gesetzt, "
            "in prod vergessen ist genau die Luecke, die dieser Test schliesst."
        )


def test_env_example_documents_every_interpolated_variable() -> None:
    """Jede ``${VAR}`` aus dem Prod-Compose muss in der Secret-Vorlage stehen.

    Sonst weiss der Betreiber nicht, dass es sie gibt — der Wert bleibt leer und das Feature
    aus, ohne dass irgendwo etwas auffaellt.
    """
    # Kommentarzeilen raus — dort steht die Syntax erklaerend als ${VAR:+...}, nicht als Referenz.
    yaml_body = "\n".join(
        line
        for line in PROD.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    referenced = set(re.findall(r"\$\{([A-Z0-9_]+)[:?}-]", yaml_body))
    documented = {
        line.split("=", 1)[0].strip()
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    missing = referenced - documented
    assert not missing, (
        f".env.prod.example fehlen {sorted(missing)} — in docker-compose.prod.yml "
        "referenziert, aber nirgends fuer den Betreiber dokumentiert."
    )


#: Variables whose NAME implies a credential. These must never carry a real value in a template.
_SECRETISH = ("PASSWORD", "SECRET", "TOKEN", "KEY")

#: The only values a credential variable may have in a committed template.
_ALLOWED_PLACEHOLDERS = {"", "change-me"}


def test_prod_secret_template_carries_no_real_values() -> None:
    """Guard the PROD template ourselves, because gitleaks no longer can.

    A committed ``.env.*.example`` documents which variables exist; a variable whose default is
    "leave empty" trips gitleaks' generic-api-key rule on the key name alone. Narrowing that by
    regex is not possible (it matches the extracted secret, not the source line), so
    ``.gitleaks.toml`` allowlists the templates by path — which would also blind it to a real
    value pasted in.

    This test is that guard, and a stricter one: it knows which variables are credentials and
    accepts only an empty value or the documented ``change-me`` placeholder. A real password,
    token or key committed into the prod template fails here.

    Deliberately scoped to the PROD template. ``.env.example`` describes the throwaway local
    stack and carries the same known dev credentials as ``docker-compose.dev.yml`` — gitleaks
    still guards that file, so a second, weaker opinion here would only get in the way."""
    offenders = [
        f"{ENV_EXAMPLE.name}:{number} {name}"
        for number, name, value in _assignments(ENV_EXAMPLE)
        if any(marker in name.upper() for marker in _SECRETISH)
        and value not in _ALLOWED_PLACEHOLDERS
    ]
    assert not offenders, (
        f"Echte Werte in der Prod-Secret-Vorlage: {offenders}. Vorlagen dokumentieren nur die "
        "Variablennamen — der Wert gehoert in <stack-dir>/.env, nie ins Repo."
    )


def _assignments(path: Path) -> list[tuple[int, str, str]]:
    """``(line number, name, value)`` for every non-comment ``KEY=VALUE`` line."""
    out: list[tuple[int, str, str]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        out.append((number, name.strip(), value.strip()))
    return out
