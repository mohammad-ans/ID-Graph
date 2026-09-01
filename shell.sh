#!/usr/bin/env bash

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

echo -e "Installing demo dependencies for the scripts to run (pyyaml, psycopg2-binary, identityresolver-dev)\n"

python -m pip install --break-system-packages pyyaml psycopg2-binary identityresolver-dev 2>/dev/null \
    || python -m pip install --quiet pyyaml psycopg2-binary identityresolver-dev

echo -e "\n\nRunning all the tests...\n"

python -m unittest discover -s tests -v

echo -e "\n\n"

echo "Running the demo with deterministic and probability modes"

python demo/run_demo.py --adaptive-detection