# Advanced-statistics runtime

Pinned R runtime for `research` plan tasks of `analysis=advstats` (ADR-22):
mixed-effects logistic (lme4), IPTW (WeightIt + survey), propensity matching
(MatchIt), KM/log-rank and Cox (survival). bacmap renders the R script
deterministically from the typed plan spec and executes it here; results are
normalised back into `bacmap.advstats_result/1`. The main bacmap environment
deliberately depends on none of these packages.

Build locally (rootless Podman without a systemd session needs the cgroupfs
manager — same as the figure images):

```bash
podman --cgroup-manager=cgroupfs build -t bacmap-stats:r45 docker/stats/r45
```

Preview the rendered script for a plan without running it:

```bash
bacmap research advstats render --method cox --data cohort.csv \
  --time days --event died --predictors tx
```

Publishing to a registry is a CI/deployment step, not something a research run
does; single workstations can build locally.
