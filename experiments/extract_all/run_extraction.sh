#!/bin/bash
cd /home/pankaj/Projects/leanchain/atelier || exit 1
echo "=== Starting at $(date) ==="
uv run python3 experiments/extract_all/extract_all_retrieval_data.py > experiments/extract_all/run_output4.log 2>&1
echo "=== Exit: $? at $(date) ==="
