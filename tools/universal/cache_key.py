"""Compute a bounded cache key from an Arduino core recipe, never from source code."""
import hashlib
import json
import sys
from pathlib import Path

cores = json.loads((Path(__file__).resolve().parents[2]/'profiles/arduino-cores.json').read_text())
core = ':'.join(sys.argv[1].split(':')[:2])
if core not in cores:
    print('none')
else:
    recipe = cores[core]
    print(hashlib.sha256(json.dumps([sys.argv[1], core, recipe, sys.argv[2] or recipe['version']],sort_keys=True).encode()).hexdigest()[:24])
