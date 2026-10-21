#!/usr/bin/env bash
set -euo pipefail
START="${V10_START:-2026-03-15}"
END="${V10_END:-2026-10-20}"
OUTPUT="${V10_OUT:-artifacts/research_v10}"
mkdir -p "$OUTPUT/raw"
for SYMBOL in xauusd eurusd; do
  for SIDE in bid ask; do
    BASE="${SYMBOL}_${SIDE}"
    echo "Fetching public Dukascopy ${BASE} M1 ${START} to ${END}"
    # Public market data only. No account, token, bridge, or order API calls.
    npx --no-install dukascopy-node \
      --instrument "$SYMBOL" --date-from "$START" --date-to "$END" \
      --timeframe m1 --price-type "$SIDE" --format csv \
      --directory "$OUTPUT/raw" --file-name "$BASE" \
      --batch-size 5 --batch-pause 1200 --retries 2 --retry-pause 2000 \
      >"$OUTPUT/raw/${BASE}.download.log" 2>&1 || {
        tail -100 "$OUTPUT/raw/${BASE}.download.log"
        exit 1
      }
    find "$OUTPUT/raw" -maxdepth 1 -type f -name '*csv' -printf '%f %s bytes\\n'
  done
  BID=$(find "$OUTPUT/raw" -maxdepth 1 -iname "${SYMBOL}_bid*.csv" | head -1)
  ASK=$(find "$OUTPUT/raw" -maxdepth 1 -iname "${SYMBOL}_ask*.csv" | head -1)
  [[ -n "$BID" && -n "$ASK" ]] || { echo 'Quote files not found'; exit 3; }
  python scripts/research_v10/normalize_bid_ask.py \
    --bid "$BID" --ask "$ASK" --start "$START" --end "$END" \
    --out "$OUTPUT/${SYMBOL^^}_bid_ask_m1.csv"
done
echo 'Public BID/ASK M1 verified. No strategy PF calculated and no orders sent.'
