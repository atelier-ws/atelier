#!/bin/bash
cd /home/pankaj/Projects/leanchain/atelier
touch experiments/extract_all/run_output5.log
date > experiments/extract_all/run_output5.log
uv run python3 -u experiments/extract_all/extract_all_retrieval_data.py >> experiments/extract_all/run_output5.log 2>&1
echo "EXIT=$?" >> experiments/extract_all/run_output5.log
date >> experiments/extract_all/run_output5.log
