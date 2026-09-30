"""Export the FastAPI OpenAPI schema — the single source of truth for client
types (ARCHITECTURE §7). ``make openapi`` runs this, then regenerates the web
client; CI's oasdiff gate blocks breaking changes."""

from __future__ import annotations

import json
from pathlib import Path

from app.main import create_app


def main() -> None:
    schema = create_app().openapi()
    out = Path(__file__).resolve().parents[2] / "openapi.json"
    out.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
