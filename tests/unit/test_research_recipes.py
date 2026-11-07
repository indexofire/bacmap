"""Figure recipe registry: stable recipes, planned roadmap and lookup."""

from __future__ import annotations

import pytest

from bacmap.research import recipes


def test_association_bar_is_stable_and_executable():
    recipe = recipes.get_recipe("association_bar")
    assert recipe.executable
    assert recipe.language == "svg"
    assert recipe.output_formats == ["svg"]


def test_tree_recipe_is_render_only_and_planned():
    recipe = recipes.get_recipe("tree_rectangular")
    assert recipe.language == "r"
    assert recipe.status == "planned"
    assert "ggtree" in recipe.packages
    assert "Tree inference is a separate workflow step" in recipe.description
    assert recipe.runtime.kind == "container"
    assert recipe.runtime.image == "bacmap-figures:r4"


def test_builtin_recipe_has_builtin_runtime():
    recipe = recipes.get_recipe("association_bar")
    assert recipe.runtime.kind == "builtin"
    assert recipe.runtime.image == ""


def test_executable_only_excludes_planned_recipes():
    ids = {recipe.recipe_id for recipe in recipes.list_recipes(executable_only=True)}
    assert "association_bar" in ids
    assert "tree_rectangular" not in ids
    assert "forest" not in ids


def test_unknown_recipe_raises():
    with pytest.raises(KeyError):
        recipes.get_recipe("nope")
