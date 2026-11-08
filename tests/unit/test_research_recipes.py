"""Figure recipe registry: stable recipes, planned roadmap and lookup."""

from __future__ import annotations

import pytest

from bacmap.research import recipes


def test_association_bar_is_stable_and_executable():
    recipe = recipes.get_recipe("association_bar")
    assert recipe.executable
    assert recipe.language == "svg"
    assert recipe.output_formats == ["svg"]


def test_forest_is_executable_builtin_svg():
    recipe = recipes.get_recipe("forest")
    assert recipe.executable
    assert recipe.language == "svg"
    assert recipe.runtime.kind == "builtin"
    assert recipe.entrypoint == "bacmap.research.render:render_forest_svg"
    assert recipe.status == "experimental"
    assert "svg" in recipe.output_formats


def test_strobe_flow_is_executable_builtin_svg():
    recipe = recipes.get_recipe("strobe_flow")
    assert recipe.executable
    assert recipe.language == "svg"
    assert recipe.runtime.kind == "builtin"
    assert recipe.entrypoint == "bacmap.research.render:render_flow_svg"
    assert recipe.status == "experimental"


def test_tree_recipe_is_render_only_and_planned():
    recipe = recipes.get_recipe("tree_rectangular")
    assert recipe.language == "r"
    assert recipe.status == "planned"
    assert not recipe.executable
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
    assert {"association_bar", "forest", "strobe_flow", "custom"} <= ids
    assert "tree_rectangular" not in ids
    assert "heatmap" not in ids
    assert "volcano" not in ids


def test_matplotlib_recipes_stay_planned_until_images_are_pinned():
    for recipe_id in ("heatmap", "pca", "volcano"):
        recipe = recipes.get_recipe(recipe_id)
        assert recipe.status == "planned"
        assert recipe.runtime.kind == "container"
        assert not recipe.executable


def test_unknown_recipe_raises():
    with pytest.raises(KeyError):
        recipes.get_recipe("nope")
