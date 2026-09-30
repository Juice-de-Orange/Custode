"""nutrition — ingredient_nutrition (per-100g Nährwerte, globale Referenzdaten) (KONZEPT §5.3)

Revision ID: 0018_ingredient_nutrition
Revises: 0017_ingredients
Create Date: 2026-06-20

Zweite globale Referenztabelle (ADR-0031): per-100g-Nährwerte je kanonischer Zutat. Geseedet über
einen JOIN auf ``ingredients.name_de`` (die ingredient_id wird in 0017 generiert). Quelle ``manual``
(kuratierte Näherung; USDA/Open-Food-Facts-Verfeinerung später). Die Rezept-Konfidenz („estimated")
wird zur Laufzeit aus der Abdeckung berechnet, nicht hier gespeichert.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_ingredient_nutrition"
down_revision = "0017_ingredients"
branch_labels = None
depends_on = None

# (name_de, kcal, protein_g, fat_g, carbs_g, sugar_g, fiber_g) — je 100 g (USDA-Näherungen)
_NUTRITION: list[tuple[str, float, float, float, float, float, float]] = [
    ("Zwiebel", 40, 1.1, 0.1, 9.3, 4.2, 1.7),
    ("Knoblauchzehe", 149, 6.4, 0.5, 33, 1.0, 2.1),
    ("Mehl", 364, 10, 1.0, 76, 0.3, 2.7),
    ("Zucker", 387, 0, 0, 100, 100, 0),
    ("Butter", 717, 0.85, 81, 0.1, 0.1, 0),
    ("Ei", 155, 13, 11, 1.1, 1.1, 0),
    ("Milch", 64, 3.4, 3.6, 4.8, 4.8, 0),
    ("Olivenöl", 884, 0, 100, 0, 0, 0),
    ("Salz", 0, 0, 0, 0, 0, 0),
    ("Pfeffer", 251, 10, 3.3, 64, 0.6, 25),
    ("Tomate", 18, 0.9, 0.2, 3.9, 2.6, 1.2),
    ("Kartoffel", 77, 2.0, 0.1, 17, 0.8, 2.2),
    ("Karotte", 41, 0.9, 0.2, 10, 4.7, 2.8),
    ("Paprika", 31, 1.0, 0.3, 6.0, 4.2, 2.1),
    ("Reis", 360, 7, 0.6, 79, 0.1, 1.3),
    ("Nudeln", 371, 13, 1.5, 75, 2.7, 3.2),
    ("Spaghetti", 371, 13, 1.5, 75, 2.7, 3.2),
    ("Hähnchenbrust", 165, 31, 3.6, 0, 0, 0),
    ("Hackfleisch", 250, 26, 15, 0, 0, 0),
    ("Schinken", 145, 21, 6.0, 1.5, 1.0, 0),
    ("Käse", 402, 25, 33, 1.3, 0.5, 0),
    ("Mozzarella", 280, 28, 17, 3.1, 1.0, 0),
    ("Frischkäse", 342, 6, 34, 4.0, 3.0, 0),
    ("Joghurt", 61, 3.5, 3.3, 4.7, 4.7, 0),
    ("Sahne", 340, 2.1, 36, 2.8, 2.9, 0),
    ("Wasser", 0, 0, 0, 0, 0, 0),
    ("Zitrone", 29, 1.1, 0.3, 9.3, 2.5, 2.8),
    ("Apfel", 52, 0.3, 0.2, 14, 10, 2.4),
    ("Banane", 89, 1.1, 0.3, 23, 12, 2.6),
    ("Honig", 304, 0.3, 0, 82, 82, 0.2),
    ("Tomatenmark", 82, 4.3, 0.5, 19, 12, 4.1),
    ("Brot", 265, 9, 3.2, 49, 5.0, 2.7),
    ("Petersilie", 36, 3.0, 0.8, 6.3, 0.9, 3.3),
    ("Basilikum", 23, 3.2, 0.6, 2.7, 0.3, 1.6),
    ("Champignons", 22, 3.1, 0.3, 3.3, 2.0, 1.0),
]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ingredient_nutrition (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            ingredient_id uuid NOT NULL REFERENCES ingredients(id),
            source varchar(20) NOT NULL DEFAULT 'manual',
            kcal real NOT NULL,
            protein_g real NOT NULL,
            fat_g real NOT NULL,
            carbs_g real NOT NULL,
            sugar_g real NOT NULL,
            fiber_g real NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_ingredient_nutrition_ingredient UNIQUE (ingredient_id)
        );
        """
    )

    insert = sa.text(
        "INSERT INTO ingredient_nutrition "
        "(ingredient_id, source, kcal, protein_g, fat_g, carbs_g, sugar_g, fiber_g) "
        "SELECT id, 'manual', :kcal, :protein, :fat, :carbs, :sugar, :fiber "
        "FROM ingredients WHERE lower(name_de) = lower(:name)"
    )
    bind = op.get_bind()
    for name, kcal, protein, fat, carbs, sugar, fiber in _NUTRITION:
        bind.execute(
            insert,
            {
                "name": name,
                "kcal": kcal,
                "protein": protein,
                "fat": fat,
                "carbs": carbs,
                "sugar": sugar,
                "fiber": fiber,
            },
        )

    # Reference data (ADR-0031): RLS ENABLE + allow-all SELECT policy; app/maint SELECT only.
    op.execute("ALTER TABLE ingredient_nutrition ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY ingredient_nutrition_read ON ingredient_nutrition FOR SELECT USING (true);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT ON ingredient_nutrition TO custode_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                GRANT SELECT ON ingredient_nutrition TO custode_maint;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ingredient_nutrition CASCADE;")
