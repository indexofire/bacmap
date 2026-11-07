# Reproducible R figure runtime for ggtree/ggplot2 recipes.
# Build: docker build -t bacmap-figures:r4 docker/figures/r4
FROM mambaorg/micromamba:1.5.10

RUN micromamba install -y -n base \
      -c conda-forge -c bioconda \
      r-base=4.4 \
      r-ggplot2 \
      r-ggtree \
      r-ape \
      r-phangorn \
    && micromamba clean --all --yes

WORKDIR /work
