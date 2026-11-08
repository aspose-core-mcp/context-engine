#!/usr/bin/env bash
# Clone all missing submodules and launch ingestion.
# Usage: bash scripts/clone_and_ingest.sh
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

echo "=== Cloning missing git submodules ==="

# Initialize and update all submodules (shallow clone for speed)
git submodule init 2>&1
git submodule update --depth 1 --jobs 4 2>&1

echo ""
echo "=== Submodule clone complete ==="
git submodule status | wc -l | xargs -I{} echo "Total submodules: {}"

echo ""
echo "=== Resetting ingestion checkpoint ==="
# Back up old checkpoint
if [ -f logs/ingestion_checkpoint.json ]; then
    cp logs/ingestion_checkpoint.json "logs/ingestion_checkpoint_wave1_$(date +%Y%m%d_%H%M%S).json"
    echo "Old checkpoint backed up"
fi

echo ""
echo "=== Starting ingestion ==="
PYTHONPATH=./src python3 scripts/run_full_ingestion.py
