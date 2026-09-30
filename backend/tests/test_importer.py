"""Unit tests for the JSON-LD recipe extractor (modules/recipes/importer.py). Pure — sample HTML in,
draft out; no network, no Docker."""

from __future__ import annotations

from app.modules.recipes.importer import extract_jsonld_recipe, extract_with_scrapers


def _page(ld: str) -> str:
    return (
        f'<html><head><script type="application/ld+json">{ld}</script></head><body>x</body></html>'
    )


def test_extracts_standard_recipe() -> None:
    ld = """
    {"@context":"https://schema.org","@type":"Recipe","name":"Pfannkuchen",
     "recipeYield":"4 Portionen","keywords":"süß, schnell",
     "recipeIngredient":["250 g Mehl","2 Eier","500 ml Milch"],
     "recipeInstructions":[{"@type":"HowToStep","text":"Mehl und Eier verrühren."},
                            {"@type":"HowToStep","text":"In der Pfanne backen."}]}
    """
    draft = extract_jsonld_recipe(_page(ld), "https://example.com/pfannkuchen")
    assert draft is not None
    assert draft.title == "Pfannkuchen"
    assert draft.servings == 4
    assert [i.raw_text for i in draft.ingredients] == ["250 g Mehl", "2 Eier", "500 ml Milch"]
    assert "Mehl und Eier" in draft.steps_md
    assert "In der Pfanne backen." in draft.steps_md
    assert draft.tags == ["süß", "schnell"]
    assert draft.source_url == "https://example.com/pfannkuchen"


def test_extracts_from_graph_with_string_instructions() -> None:
    ld = """
    {"@context":"https://schema.org","@graph":[
        {"@type":"WebPage","name":"x"},
        {"@type":["Recipe","Thing"],"name":"Suppe","recipeYield":2,
         "recipeIngredient":["Wasser"],"recipeInstructions":"Kochen."}]}
    """
    draft = extract_jsonld_recipe(_page(ld), "https://example.com/suppe")
    assert draft is not None
    assert draft.title == "Suppe"
    assert draft.servings == 2
    assert draft.steps_md == "Kochen."


def test_returns_none_without_recipe() -> None:
    ld = '{"@context":"https://schema.org","@type":"WebPage","name":"Kein Rezept"}'
    assert extract_jsonld_recipe(_page(ld), "https://example.com/x") is None


def test_returns_none_on_no_jsonld() -> None:
    assert extract_jsonld_recipe("<html><body>nichts</body></html>", "https://example.com") is None


def test_ignores_malformed_jsonld() -> None:
    assert extract_jsonld_recipe(_page("{not json"), "https://example.com") is None


def test_clamps_servings() -> None:
    ld = '{"@type":"Recipe","name":"X","recipeYield":"99999","recipeIngredient":[]}'
    draft = extract_jsonld_recipe(_page(ld), "https://example.com/x")
    assert draft is not None
    assert draft.servings == 100


_MICRODATA = """<html><body>
<div itemscope itemtype="https://schema.org/Recipe">
  <h1 itemprop="name">Pfannkuchen</h1>
  <span itemprop="recipeYield">4 Portionen</span>
  <ul>
    <li itemprop="recipeIngredient">250 g Mehl</li>
    <li itemprop="recipeIngredient">2 Eier</li>
  </ul>
  <div itemprop="recipeInstructions">Mehl und Eier verruehren. In der Pfanne backen.</div>
</div></body></html>"""


def test_scrapers_fallback_parses_microdata() -> None:
    # No JSON-LD on the page -> the primary (JSON-LD) extractor declines...
    assert extract_jsonld_recipe(_MICRODATA, "https://example.com/p") is None
    # ...and the recipe-scrapers fallback reads the schema.org microdata.
    draft = extract_with_scrapers(_MICRODATA, "https://example.com/p")
    assert draft is not None
    assert draft.title == "Pfannkuchen"
    assert draft.servings == 4
    assert any("Mehl" in line.raw_text for line in draft.ingredients)
