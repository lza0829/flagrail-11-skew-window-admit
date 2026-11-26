#!/usr/bin/env bash
# 时间窗自动化总入口：各场景仍以独立进程脚本分开跑。
# 规格特别要求「超大漂移」与「逆序」两套脚本分开跑 —— 这里也是两条独立命令。
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"
BASE="${FLAGRAIL_BASE:-http://127.0.0.1:11800}"
rc=0

run() {
  echo "================================================================"
  echo "▶ $1"
  "$PY" "$DIR/$1" "$BASE" || rc=1
}

run "时间窗_正常时序.py"
run "时间窗_逆序.py"
run "时间窗_超大漂移.py"
run "时间窗_并发双回读.py"
run "时间窗_校正收证_口径分叉.py"

echo "================================================================"
if [ "$rc" -eq 0 ]; then
  echo "ALL TIME-WINDOW SCRIPTS PASS"
else
  echo "SOME SCRIPTS FAILED"
fi
exit $rc
