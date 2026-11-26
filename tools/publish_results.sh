#!/usr/bin/env bash
set -euo pipefail
OUT="$1"
RID="$2"
[[ "$RID" =~ ^[0-9a-f]{32}$ ]] || { echo 'Bad request ID' >&2; exit 1; }
[[ -f "$OUT/result.json" && -f "$OUT/firmware.bin" ]] || { echo 'Missing compiled output' >&2; exit 1; }
ROOT="$RUNNER_TEMP/esp-published-results"
if git ls-remote --exit-code --heads origin build-results >/dev/null 2>&1; then
  git fetch origin build-results
  git worktree add -B build-results "$ROOT" origin/build-results
else
  git worktree add --detach "$ROOT" HEAD
  git -C "$ROOT" checkout --orphan build-results
  git -C "$ROOT" rm -rf -q .
fi
mkdir -p "$ROOT/results/$RID/chunks"
cp "$OUT/result.json" "$ROOT/results/$RID/result.json"
cp "$OUT/chunks/"*.bin "$ROOT/results/$RID/chunks/"
python3 - "$ROOT" "$RID" <<'PY'
import json, pathlib, shutil, sys
root=pathlib.Path(sys.argv[1]); rid=sys.argv[2]
index=root/'result-index.json'
try:
    ids=json.loads(index.read_text(encoding='utf-8'))
    assert isinstance(ids,list)
except Exception: ids=[]
ids=[r for r in ids if r != rid] + [rid]
for old in ids[:-10]:
    if len(old)==32 and all(c in '0123456789abcdef' for c in old):
        shutil.rmtree(root/'results'/old, ignore_errors=True)
ids=ids[-10:]
index.write_text(json.dumps(ids,indent=2)+'\n',encoding='utf-8')
PY
git -C "$ROOT" config user.name 'github-actions[bot]'
git -C "$ROOT" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git -C "$ROOT" add -A
if ! git -C "$ROOT" diff --cached --quiet; then
  git -C "$ROOT" commit -m "Publish ESP Flasher build $RID"
  git -C "$ROOT" push origin HEAD:build-results
fi
echo "Result published: build-results/results/$RID/result.json"
