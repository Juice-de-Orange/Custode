# ADR-0016: `uv` als Python-Environment- und Dependency-Manager

- **Status:** beschlossen
- **Datum:** 2026-06-14
- **Betrifft:** `backend/` · **Bezug:** ENTWICKLUNGSKONZEPT E8 (Boring Technology), CLAUDE.md Stack

## Kontext

Das Backend (Python 3.12+, FastAPI) braucht reproduzierbare Umgebungen mit
Lockfile, schnelle CI-Installation und eine einzige, beherrschbare Toolchain.
Das Konzept legt den Package-Manager nicht fest, fordert aber „langweilige",
beherrschte Technik (E8) und reproduzierbare Builds (DoD, CI-Gates).

## Entscheidung

Wir nutzen **uv** (astral-sh) für virtuelle Umgebung, Dependency-Resolution und
Lockfile. `pyproject.toml` (PEP 621) ist die Quelle, `uv.lock` wird committed.
CI installiert via `uv sync --frozen`. ruff (bereits gesetzt) und mypy laufen als
Dev-Dependencies über `uv run`.

## Konsequenzen

- **Positiv:** ein Tool für venv + Resolver + Runner; sehr schnelle, deterministische
  Installs (gut für CI-Budget); `uv.lock` macht Builds reproduzierbar; PEP-621-Standard.
- **Negativ / Kosten:** Entwickler installieren uv (winget/pipx); uv ist jünger als
  pip/poetry — Risiko durch gepinnte uv-Version in CI gemindert.
- **CI:** `uv sync --frozen`, dann `uv run ruff/mypy/pytest`. `uv.lock` committed.

## Alternativen (verworfen)

- **pip + requirements.txt / pip-tools** — mehr Handarbeit, getrennte Tools, keine
  integrierte venv-Verwaltung.
- **Poetry / PDM** — funktionsfähig, aber langsamer und schwergewichtiger; uv deckt
  denselben Bedarf schneller mit einem Tool ab.
