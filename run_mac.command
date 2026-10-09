#!/bin/zsh
set -e
cd "$(dirname "$0")"
if ! command -v swipl >/dev/null 2>&1; then
  echo "SWI-Prolog is required. Install it with: brew install swi-prolog"
  exit 2
fi
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 verify_setup.py
python3 run_experiment.py --runs 1000 --seed 42 --output outputs/n1000_seed42
