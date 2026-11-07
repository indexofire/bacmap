# Figure runtimes

These images are the reproducible default for R/Python figure recipes. The main bacmap
environment deliberately does not depend on R, matplotlib or Bioconductor.

Build locally:

```bash
docker build -t bacmap-figures:py312 docker/figures/py312
docker build -t bacmap-figures:r4   docker/figures/r4
```

For Apptainer/Podman (the sandbox backends bacmap uses), convert or pull the image and record
its digest with the artifact:

```bash
apptainer build bacmap-figures-r4.sif docker-daemon://bacmap-figures:r4
podman image inspect bacmap-figures:r4 --format '{{.Digest}}'
```

Publishing to a registry is a CI/deployment step, not something a research run does. Pin the
digest in the recipe or deployment config; never `install.packages()`/`pip install` during a
run.
