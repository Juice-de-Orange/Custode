"""nutrition — kanonische ``ingredients`` (globale Referenzdaten) + Starter-Korpus (KONZEPT §5.3)

Revision ID: 0017_ingredients
Revises: 0016_recipes
Create Date: 2026-06-20

Erste **globale Referenztabelle** (kein ``household_id``): die kanonische Zutaten-Liste ist für
alle Haushalte gleich (ADR-0031). Read-only für die App-Rolle (nur ``GRANT SELECT``); kuratiert vom
Owner/Migration. RLS ist ``ENABLE`` (nicht ``FORCE``) mit einer Allow-all-Lese-Policy — so bleibt
das „jede Tabelle hat RLS"-Posture, während der Owner seeden kann. ``grams_per_unit`` bildet
Einheiten auf Gramm ab (für Nährwert/Skalierung in S5); ``aliases`` hilft dem Freitext-Matching.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_ingredients"
down_revision = "0016_recipes"
branch_labels = None
depends_on = None

# (name_de, name_en, category, default_unit, grams_per_unit, aliases)
_SEED: list[tuple[str, str, str, str, str, list[str]]] = [
    ("Zwiebel", "Onion", "Gemüse", "Stück", '{"Stück": 110, "g": 1}', []),
    ("Knoblauchzehe", "Garlic clove", "Gemüse", "Zehe", '{"Zehe": 3, "g": 1}', ["Knoblauch"]),
    ("Mehl", "Flour", "Backen", "g", '{"g": 1, "EL": 10, "Tasse": 120}', []),
    ("Zucker", "Sugar", "Backen", "g", '{"g": 1, "EL": 12, "TL": 4, "Tasse": 200}', []),
    ("Butter", "Butter", "Milchprodukte", "g", '{"g": 1, "EL": 15, "TL": 5}', []),
    ("Ei", "Egg", "Eier", "Stück", '{"Stück": 55, "g": 1}', ["Eier"]),
    ("Milch", "Milk", "Milchprodukte", "ml", '{"ml": 1, "g": 1.03, "Tasse": 240, "l": 1000}', []),
    ("Olivenöl", "Olive oil", "Öle", "ml", '{"ml": 1, "EL": 13, "TL": 4.5, "g": 1.09}', ["Öl"]),
    ("Salz", "Salt", "Gewürze", "g", '{"g": 1, "TL": 6, "Prise": 0.4}', []),
    ("Pfeffer", "Pepper", "Gewürze", "g", '{"g": 1, "TL": 2.3}', []),
    ("Tomate", "Tomato", "Gemüse", "Stück", '{"Stück": 120, "g": 1}', []),
    ("Kartoffel", "Potato", "Gemüse", "Stück", '{"Stück": 150, "g": 1}', []),
    ("Karotte", "Carrot", "Gemüse", "Stück", '{"Stück": 60, "g": 1}', ["Möhre"]),
    ("Paprika", "Bell pepper", "Gemüse", "Stück", '{"Stück": 120, "g": 1}', []),
    ("Reis", "Rice", "Getreide", "g", '{"g": 1, "Tasse": 185}', []),
    ("Nudeln", "Pasta", "Getreide", "g", '{"g": 1}', ["Pasta"]),
    ("Spaghetti", "Spaghetti", "Getreide", "g", '{"g": 1}', []),
    ("Hähnchenbrust", "Chicken breast", "Fleisch", "g", '{"g": 1, "Stück": 150}', ["Hähnchen"]),
    ("Hackfleisch", "Ground beef", "Fleisch", "g", '{"g": 1}', ["Hack"]),
    ("Schinken", "Ham", "Fleisch", "g", '{"g": 1, "Scheibe": 20}', []),
    ("Käse", "Cheese", "Milchprodukte", "g", '{"g": 1, "Scheibe": 25}', []),
    ("Mozzarella", "Mozzarella", "Milchprodukte", "g", '{"g": 1, "Kugel": 125}', []),
    ("Frischkäse", "Cream cheese", "Milchprodukte", "g", '{"g": 1, "EL": 15}', []),
    ("Joghurt", "Yogurt", "Milchprodukte", "g", '{"g": 1, "EL": 15, "Becher": 150}', []),
    ("Sahne", "Cream", "Milchprodukte", "ml", '{"ml": 1, "g": 1.0, "EL": 15}', ["Schlagsahne"]),
    ("Wasser", "Water", "Sonstiges", "ml", '{"ml": 1, "g": 1, "l": 1000}', []),
    ("Zitrone", "Lemon", "Obst", "Stück", '{"Stück": 100, "g": 1}', []),
    ("Apfel", "Apple", "Obst", "Stück", '{"Stück": 180, "g": 1}', []),
    ("Banane", "Banana", "Obst", "Stück", '{"Stück": 120, "g": 1}', []),
    ("Honig", "Honey", "Süßungsmittel", "g", '{"g": 1, "EL": 21, "TL": 7}', []),
    ("Tomatenmark", "Tomato paste", "Konserven", "g", '{"g": 1, "EL": 16, "TL": 5}', []),
    ("Brot", "Bread", "Backwaren", "Scheibe", '{"Scheibe": 40, "g": 1}', []),
    ("Petersilie", "Parsley", "Kräuter", "g", '{"g": 1, "EL": 4, "Bund": 30}', []),
    ("Basilikum", "Basil", "Kräuter", "g", '{"g": 1, "Blatt": 0.5}', []),
    ("Champignons", "Mushrooms", "Gemüse", "g", '{"g": 1, "Stück": 20}', ["Pilze", "Champignon"]),
]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ingredients (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            name_de varchar(120) NOT NULL,
            name_en varchar(120) NOT NULL,
            category varchar(60) NOT NULL,
            default_unit varchar(20) NOT NULL,
            grams_per_unit jsonb NOT NULL DEFAULT '{}',
            aliases varchar[] NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE UNIQUE INDEX ux_ingredients_name_de ON ingredients (lower(name_de));")

    # Seed the starter corpus while the table is still plain (owner insert, pre-RLS). Fully
    # parameterized (the SQL is a constant; only bound values vary) — no string-built SQL.
    insert = sa.text(
        "INSERT INTO ingredients "
        "(name_de, name_en, category, default_unit, grams_per_unit, aliases) "
        "VALUES (:name_de, :name_en, :category, :unit, CAST(:grams AS jsonb), "
        "CAST(:aliases AS varchar[]))"
    )
    bind = op.get_bind()
    for name_de, name_en, category, unit, grams, aliases in _SEED:
        bind.execute(
            insert,
            {
                "name_de": name_de,
                "name_en": name_en,
                "category": category,
                "unit": unit,
                "grams": grams,
                "aliases": aliases,
            },
        )

    # Reference data (ADR-0031): RLS ENABLED (not FORCE) so the owner can seed in later migrations;
    # allow-all SELECT policy; app/maint get SELECT only (no write grant -> read-only for the app).
    op.execute("ALTER TABLE ingredients ENABLE ROW LEVEL SECURITY;")
    op.execute("CREATE POLICY ingredients_read ON ingredients FOR SELECT USING (true);")
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT ON ingredients TO custode_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                GRANT SELECT ON ingredients TO custode_maint;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ingredients CASCADE;")
