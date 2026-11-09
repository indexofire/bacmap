#!/usr/bin/env bash
# bacmap one-line installer (PLAN #2)
# Usage: curl -fsSL https://raw.githubusercontent.com/indexofire/bacmap/main/scripts/setup.sh | bash
#
# Steps:
#   1. Check prerequisites (git, pixi or conda)
#   2. Clone bacmap (or use existing checkout)
#   3. pixi install (runtime environment)
#   4. Run bacmap doctor (health check)
#
# Override defaults:
#   BACMAP_INSTALL_DIR=~/repos/bacmap  (clone destination)
#   BACMAP_SKIP_DOCTOR=1               (skip health check)

set -euo pipefail

BACMAP_INSTALL_DIR="${BACMAP_INSTALL_DIR:-$HOME/repos/bacmap}"
REPO_URL="https://github.com/indexofire/bacmap.git"

info() { echo "▸ $*"; }
error() { echo "✗ $*" >&2; exit 1; }

# ── 1. Prerequisites ─────────────────────────────────────────────
info "Checking prerequisites..."

command -v git >/dev/null 2>&1 || error "git not found. Install it first: sudo apt install git"

if command -v pixi >/dev/null 2>&1; then
    info "pixi found: $(pixi --version)"
elif [ -f "$HOME/.pixi/bin/pixi" ]; then
    export PATH="$HOME/.pixi/bin:$PATH"
    info "pixi found at ~/.pixi/bin: $(pixi --version)"
else
    error "pixi not found. Install it:
  curl -fsSL https://pixi.sh/install.sh | bash
Then restart your shell and re-run this script."
fi

# ── 2. Clone or update ───────────────────────────────────────────
if [ -d "$BACMAP_INSTALL_DIR/.git" ]; then
    info "Updating existing checkout at $BACMAP_INSTALL_DIR..."
    cd "$BACMAP_INSTALL_DIR"
    git pull --ff-only
else
    info "Cloning bacmap to $BACMAP_INSTALL_DIR..."
    mkdir -p "$(dirname "$BACMAP_INSTALL_DIR")"
    git clone "$REPO_URL" "$BACMAP_INSTALL_DIR"
    cd "$BACMAP_INSTALL_DIR"
fi

# ── 3. Install runtime environment ───────────────────────────────
info "Installing pixi environment (this may take a few minutes)..."
pixi install

# ── 4. Health check ──────────────────────────────────────────────
if [ -z "${BACMAP_SKIP_DOCTOR:-}" ]; then
    info "Running health check..."
    pixi run bacmap doctor || true  # doctor may flag optional tools; don't block install
fi

info ""
info "✅ bacmap installed successfully!"
info "   Directory: $BACMAP_INSTALL_DIR"
info "   Try:       pixi run bacmap --version"
info "   Start:     pixi run bacmap start web"
info "   MCP:       pixi run bacmap start mcp"
