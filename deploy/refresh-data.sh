#!/bin/sh
# Rolling hourly refresh of Nobitex bars for the beta (no research manifest).
# Runs inside the image; from a plain install, run it from the repository root.
NNFX=${NNFX:-/app/.venv/bin/nnfx}
SYMBOLS=${NNFX_SYMBOLS:-"BTC/USDT ETH/USDT BTC/IRT ETH/IRT USDT/IRT"}
START=${NNFX_START:-2021-01-01}
END=$(date -u +%Y-%m-%dT%H:00)
cd "$(dirname "$NNFX")/../.." 2>/dev/null || true
for s in $SYMBOLS; do
  "$NNFX" fetch --feed nobitex --symbol "$s" --start "$START" --end "$END" --no-manifest \
    || echo "refresh failed for $s" >&2
done
