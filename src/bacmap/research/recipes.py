"""Figure recipe registry.

A recipe is a versioned, tested way to turn a ``FigureSpec`` into a figure.  Agents
select recipes; they do not invent standard plots or copy figures from papers.  Only
recipes with a non-empty entrypoint are executable today; ``planned`` entries document
the roadmap without pretending to work.

The registry is metadata.  Actual rendering runs either in bacmap (deterministic
recipes) or in the ``mine`` sandbox (R/Python recipes and custom scripts), with the
output registered through ``bacmap research figure attach``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RecipeLanguage = Literal["svg", "python", "r"]
RecipeStatus = Literal["stable", "experimental", "planned"]
RuntimeKind = Literal["builtin", "container", "pixi", "host"]


class RecipeRuntime(BaseModel):
    """Where a recipe executes.  Container is the reproducible default for R/Python."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: RuntimeKind = "builtin"
    image: str = ""
    environment: str = ""
    notes: str = ""


class FigureRecipe(BaseModel):
    """One versioned figure recipe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recipe_id: str
    version: str
    title: str
    description: str
    language: RecipeLanguage
    input_kind: str
    output_formats: list[str] = Field(default_factory=list)
    packages: list[str] = Field(default_factory=list)
    sandbox_image: str = ""
    runtime: RecipeRuntime = Field(default_factory=RecipeRuntime)
    entrypoint: str = ""
    status: RecipeStatus = "planned"
    notes: str = ""

    @property
    def executable(self) -> bool:
        return self.status != "planned" and bool(self.entrypoint)


_RECIPES: tuple[FigureRecipe, ...] = (
    FigureRecipe(
        recipe_id="association_bar",
        version="1.0.0",
        title="Association 2×2 bar chart",
        description=(
            "Deterministic SVG bar chart for the P1 AMR association: four counts, exact "
            "table from the FigureSpec, no added data."
        ),
        language="svg",
        input_kind="association_table",
        output_formats=["svg"],
        entrypoint="bacmap.research.render:render_association_svg",
        runtime=RecipeRuntime(kind="builtin", notes="deterministic SVG renderer"),
        status="stable",
        notes="PDF/PNG conversion belongs to the sandbox/export step, not this renderer.",
    ),
    FigureRecipe(
        recipe_id="forest",
        version="0.1.0",
        title="Forest plot",
        description=(
            "Effect estimates with 95% confidence intervals on a log axis with a "
            "no-effect line; renders one row per effect in the FigureSpec."
        ),
        language="svg",
        input_kind="effect_estimates",
        output_formats=["svg"],
        entrypoint="bacmap.research.render:render_forest_svg",
        runtime=RecipeRuntime(kind="builtin", notes="deterministic SVG renderer"),
        status="experimental",
        notes=(
            "Builtin SVG tier keeps the recipe offline-reproducible; journal-specific "
            "forest styling belongs to the custom sandbox path."
        ),
    ),
    FigureRecipe(
        recipe_id="tree_rectangular",
        version="0.1.0",
        title="Rectangular phylogenetic tree",
        description=(
            "Render a Newick tree with tip metadata, support values, scale bar and "
            "rooting annotation. Tree inference is a separate workflow step."
        ),
        language="r",
        input_kind="newick+metadata",
        output_formats=["pdf", "svg", "png"],
        packages=["ggtree", "ggplot2"],
        sandbox_image="bacmap-figures:r4",
        runtime=RecipeRuntime(
            kind="container", image="bacmap-figures:r4", notes="R + ggtree/ggplot2"
        ),
        status="planned",
        notes="Build the tree with IQ-TREE/Gubbins first; this recipe only renders it.",
    ),
    FigureRecipe(
        recipe_id="heatmap",
        version="0.1.0",
        title="Annotated heatmap",
        description=(
            "Matrix heatmap with row/column annotation tracks and a color scale."
        ),
        language="python",
        input_kind="matrix+annotations",
        output_formats=["pdf", "svg", "png"],
        packages=["matplotlib", "seaborn"],
        sandbox_image="bacmap-figures:py312",
        runtime=RecipeRuntime(
            kind="container", image="bacmap-figures:py312", notes="pinned matplotlib"
        ),
        status="planned",
    ),
    FigureRecipe(
        recipe_id="pca",
        version="0.1.0",
        title="PCA / ordination plot",
        description="Two-dimensional ordination with explained variance and group colors.",
        language="python",
        input_kind="matrix+groups",
        output_formats=["pdf", "svg", "png"],
        packages=["matplotlib"],
        sandbox_image="bacmap-figures:py312",
        runtime=RecipeRuntime(
            kind="container", image="bacmap-figures:py312", notes="pinned matplotlib"
        ),
        status="planned",
    ),
    FigureRecipe(
        recipe_id="volcano",
        version="0.1.0",
        title="Volcano plot",
        description="Effect size vs significance with FDR threshold and labeled hits.",
        language="python",
        input_kind="effect_estimates+fdr",
        output_formats=["pdf", "svg", "png"],
        packages=["matplotlib"],
        sandbox_image="bacmap-figures:py312",
        runtime=RecipeRuntime(
            kind="container", image="bacmap-figures:py312", notes="pinned matplotlib"
        ),
        status="planned",
    ),
    FigureRecipe(
        recipe_id="strobe_flow",
        version="0.1.0",
        title="STROBE-style flow diagram",
        description=(
            "Inclusion/exclusion flow with counts derived from the run roster and "
            "the session statistics (STROBE item 13)."
        ),
        language="svg",
        input_kind="cohort_flow",
        output_formats=["svg"],
        entrypoint="bacmap.research.render:render_flow_svg",
        runtime=RecipeRuntime(kind="builtin", notes="deterministic SVG renderer"),
        status="experimental",
        notes="Counts come from runs.sqlite and the session stat; nothing is typed in.",
    ),
    FigureRecipe(
        recipe_id="custom",
        version="1.0.0",
        title="Custom agent-authored figure",
        description=(
            "Fallback when no standard recipe expresses the result. The script runs in the "
            "mine sandbox and is attached with spec/data/code/output hashes."
        ),
        language="python",
        input_kind="figure_spec",
        output_formats=["pdf", "svg", "png"],
        sandbox_image="bacmap-figures:py312",
        runtime=RecipeRuntime(
            kind="container", image="bacmap-figures:py312", notes="agent-authored script"
        ),
        status="experimental",
        entrypoint="mine",
        notes="Requires human sign-off; never use for a plot a stable recipe already covers.",
    ),
)


def list_recipes(*, executable_only: bool = False) -> list[FigureRecipe]:
    items = list(_RECIPES)
    if executable_only:
        items = [recipe for recipe in items if recipe.executable]
    return items


def get_recipe(recipe_id: str) -> FigureRecipe:
    for recipe in _RECIPES:
        if recipe.recipe_id == recipe_id:
            return recipe
    raise KeyError(f"unknown figure recipe: {recipe_id!r}")
