#!/usr/bin/env bash
# Install the CoinFello plugin into the active Hermes profile.
set -euo pipefail

HERMES_ROOT="${HERMES_HOME:-$HOME/.hermes}"
TARGET="$HERMES_ROOT/plugins/coinfello"
SRC="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$(dirname "$TARGET")"

if [ -e "$TARGET" ]; then
  echo "Already installed at $TARGET — reinstalling over it."
  rsync -a --delete \
    --exclude .git/ --exclude __pycache__/ --exclude .pytest_cache/ \
    --exclude .venv/ --exclude '*.pyc' --exclude .coinfello-state.json --exclude '.coinfello-venues-*.json' \
    "$SRC/" "$TARGET/"
else
  rsync -a \
    --exclude .git/ --exclude __pycache__/ --exclude .pytest_cache/ \
    --exclude .venv/ --exclude '*.pyc' --exclude .coinfello-state.json --exclude '.coinfello-venues-*.json' \
    "$SRC/" "$TARGET/"
fi

echo "Installed to $TARGET"
echo "Next:"
echo "  1. hermes config set plugins.enabled '[\"coinfello\"]'   # merge with existing entries"
echo "  2. Restart Hermes; the coinfello_* tools appear in every session."
echo "  3. In the desktop app: ⌘K → Reload desktop plugins (the pane is opt-in;"
echo "     flip it on under Capabilities → Plugins)."
