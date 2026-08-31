#!/usr/bin/env bash

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "Installing demo dependencies for the scripts to run(pyyaml, psycopg2-binary)\n"
pip install --break-system-packages pyyaml psycopg2-binary 2>/dev/null || pip install --quiet pyyaml psycopg2-binary

echo -e "\n\nRunning all the tests...\n"
python -m unittest discover -s tests -v

echo -e "\n\n"
echo "Running the demo with deterministic and probability modes\n"
python demo/run_demo.py --adaptive-detection