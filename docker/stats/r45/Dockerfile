# Reproducible advanced-statistics runtime for bacmap research tasks (ADR-22).
# Build: podman --cgroup-manager=cgroupfs build -t bacmap-stats:r45 docker/stats/r45
FROM docker.io/mambaorg/micromamba:1.5.10

RUN micromamba install -y -n base \
      -c conda-forge -c bioconda \
      r-base=4.5 \
      r-lme4 \
      r-survival \
      r-matchit \
      r-weightit \
      r-survey \
      r-jsonlite \
    && micromamba clean --all --yes

# 沙箱以 rootless podman 运行：宿主 uid 在容器内映射为 0，workspace 挂载目录
# 属主即 0——必须以 root 运行才能写 result.json（与 mine 的 python:slim 同构；
# 沙箱无网络、数据只读挂载，root 不构成额外权限面）。
USER root

WORKDIR /workspace
