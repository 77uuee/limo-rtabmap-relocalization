#!/usr/bin/env bash
# 매핑 직후 1회 실행. 기준 지도를 읽기 전용 원본으로 고정한다.
#
# 왜 필요한가 (2026-08-30 사고):
#   rtabmap 은 localization 모드에서도 "정상 종료" 시 현재 메모리를 DB에 쓴다.
#   /rtabmap/reset 등으로 WM이 비어 있는 상태에서 종료하면, 빈 메모리가
#   그대로 저장돼 기준 지도가 0노드가 된다. 백업이 없으면 재매핑밖에 없다.
set -euo pipefail

SRC="${1:-$HOME/.ros/limo_rtabmap_camera.db}"
DST="${2:-$HOME/maps/rtab_camera_master.db}"

nodes() {
  python3 - "$1" <<'PY'
import sqlite3, sys
try:
    with sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True) as db:
        print(db.execute("SELECT COUNT(*) FROM Node").fetchone()[0])
except sqlite3.Error as e:
    print(-1)
PY
}

N=$(nodes "$SRC")
if [ "$N" -le 0 ]; then
  echo "[중단] $SRC 의 노드 수가 $N — 저장할 지도가 없다."
  exit 1
fi

mkdir -p "$(dirname "$DST")"
if [ -f "$DST" ]; then
  BAK="$DST.$(date +%Y%m%d_%H%M%S).bak"
  chmod 644 "$DST"; mv "$DST" "$BAK"
  echo "[백업] 기존 원본 → $BAK"
fi
cp "$SRC" "$DST"
chmod 444 "$DST"      # 읽기 전용: 실수로 열려도 rtabmap이 덮어쓸 수 없다
echo "[완료] 원본 지도 고정: $DST ($N nodes, 읽기 전용)"
echo "       측정(auto_trial.py)은 이 원본의 사본(/tmp/reloc_work.db)만 사용한다."
