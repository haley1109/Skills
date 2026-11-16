#!/usr/bin/env sh
# Run with: sh install.sh [--offline]
set -eu
skill_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python_cmd=${PYTHON:-python3}
"$python_cmd" -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
requirement=requirements-online.txt
if [ "${1:-}" = "--offline" ]; then requirement=requirements.txt; fi
"$python_cmd" -m pip install -r "$skill_dir/$requirement"
if [ "$requirement" = requirements-online.txt ]; then
  "$python_cmd" "$skill_dir/scripts/capture_single.py" --diagnose
fi
