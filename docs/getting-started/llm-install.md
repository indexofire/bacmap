# LLM-installable setup instructions

Paste this entire document into any LLM chat and ask it to install bacmap for you.

## Prerequisites

1. **Linux** (x86_64 recommended; ARM may have bioinformatics tool issues)
2. **git** — `sudo apt install git` (or your distro's equivalent)
3. **pixi** — package manager (installs Python + all bioinformatics tools)

```bash
curl -fsSL https://pixi.sh/install.sh | bash
# Restart your shell, then verify:
pixi --version
```

## Install bacmap

```bash
git clone https://github.com/indexofire/bacmap.git ~/repos/bacmap
cd ~/repos/bacmap
pixi install
```

## Verify

```bash
# Version check
pixi run bacmap --version

# Health check (read-only)
pixi run bacmap doctor
```

## Start services

```bash
# Web interface (http://127.0.0.1:8800)
pixi run bacmap start web

# MCP server (for AI agents)
pixi run bacmap start mcp

# Terminal UI
pixi run bacmap start tui
```

## Quick analysis test

```bash
# Submit a FASTA directory for analysis
pixi run bacmap task submit --fasta-dir /path/to/assemblies --type analyze

# Check task status
pixi run bacmap task list
```

## Hardware requirements

| Tier | CPU | RAM | Disk | Notes |
|---|---|---|---|---|
| Minimum | 8 cores | 16 GB | 100 GB | Basic analysis, no GTDB-Tk |
| Workstation | 16 cores | 64 GB | 300 GB | Full pipeline including GTDB-Tk |
| Server | 64 cores | 256 GB | 1 TB | GTDB-Tk full-tree, heavy batch |

### Local LLM (optional)

| Setup | GPU | RAM | Notes |
|---|---|---|---|
| Entry | RTX 5060 Ti 16 GB | 64 GB | Quantised DeepSeek/Qwen models |
| Dual | 2× DGX Spark | — | DeepSeek mini + separate x86_64 bioinformatics server |

> **Note**: Bioinformatics tools may have ARM build issues. Use x86_64 for the
> bacmap server. GPU servers can run LLM inference separately (set
> `[llm.endpoints]` `location = "lan"` in config.toml).
