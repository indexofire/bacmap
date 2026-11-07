# Reproducible Python figure runtime for bacmap research recipes.
# Build: docker build -t bacmap-figures:py312 docker/figures/py312
FROM python:3.12-slim

RUN pip install --no-cache-dir \
    matplotlib==3.10.0 \
    seaborn==0.13.2 \
    numpy==1.26.4 \
    pandas==2.2.3

WORKDIR /work
