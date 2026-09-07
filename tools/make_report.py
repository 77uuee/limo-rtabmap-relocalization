#!/usr/bin/env python3
"""과제 결과물 자동 생성 (맥북에서 실행. /usr/bin/python3 필요 — cv2/numpy).

  /usr/bin/python3 make_report.py [--csv results.csv] [--map ../rtab_camera_v2_2.yaml]

출력:
  report_table.md — 조건별 × 지점별 성공률 표 (PPT 17p 결과물 ①)
  report_map.png  — 지점별 성공률을 지도 위에 표시 (PPT 17p 결과물 ②)

집계 규칙:
- truth_src=points 행만 (통일 기준. snap 행은 8/31 구기준 — 표 각주로만 언급)
- trial 0(스팟 체크), note에 truth-reg/spotcheck/invalid 포함 행 제외
- 성공률 = 성공 / (성공+미수렴+오탐). 성공 회차의 평균 수렴 시간·오차 병기
"""
import argparse
import csv
import math
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CONDS = ["C1", "C2", "C3", "C4"]
COND_LABEL = {"C1": "C1 기준", "C2": "C2 시간대", "C3": "C3 소등", "C4": "C4 배치"}


def load_rows(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            note = r.get("note", "")
            if r.get("truth_src") != "points":
                continue
            if not r.get("trial") or int(r["trial"]) < 1:
                continue
            if any(k in note for k in ("truth-reg", "spotcheck", "invalid")):
                continue
            rows.append(r)
    return rows


def cell(rows, pt, cond):
    sel = [r for r in rows if r["point"] == pt and r["condition"] == cond]
    if not sel:
        return None
    n_ok = sum(1 for r in sel if r["verdict"] == "성공")
    n_false = sum(1 for r in sel if r["verdict"] == "오탐")
    ts = [float(r["t_converge_s"]) for r in sel
          if r["verdict"] == "성공" and r["t_converge_s"]]
    eps = [float(r["err_pos_m"]) for r in sel
           if r["verdict"] == "성공" and r["err_pos_m"]]
    return dict(n=len(sel), ok=n_ok, false=n_false,
                t=(sum(ts) / len(ts)) if ts else None,
                ep=(sum(eps) / len(eps)) if eps else None)


def make_table(rows, points, out):
    pts = [p for p in sorted(points) if any(r["point"] == p for r in rows)]
    lines = ["# RTAB-Map 재위치추정 성공률 (60초, 회전 허용, 판정 0.5 m/30°)",
             "",
             "| 지점 | " + " | ".join(COND_LABEL[c] for c in CONDS) + " |",
             "|---|" + "---|" * len(CONDS)]
    for p in pts:
        row = [f"**{p}**"]
        for c in CONDS:
            d = cell(rows, p, c)
            if d is None:
                row.append("—")
            else:
                s = f"{d['ok']}/{d['n']}"
                if d["t"] is not None:
                    s += f" ({d['t']:.1f}s"
                    if d["ep"] is not None:
                        s += f", {d['ep']*100:.0f}cm"
                    s += ")"
                if d["false"]:
                    s += f" 오탐{d['false']}"
                row.append(s)
        lines.append("| " + " | ".join(row) + " |")
    # 조건 합계
    row = ["**전체**"]
    for c in CONDS:
        sel = [r for r in rows if r["condition"] == c]
        if not sel:
            row.append("—")
        else:
            ok = sum(1 for r in sel if r["verdict"] == "성공")
            row.append(f"{ok}/{len(sel)} ({100*ok/len(sel):.0f}%)")
    lines.append("| " + " | ".join(row) + " |")
    lines += ["",
              "- 성공 칸: 성공수/시도수 (평균 수렴시간, 평균 위치오차)",
              "- 정답 기준: 바닥 테이프 등록 좌표 (measurement_plan.md 0.1절)",
              "- 지도: results.csv `map` 열 참조 (v2.2~v2.4, 좌표계 동일)"]
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[표] {out}")


def make_map(rows, points, map_yaml, out):
    meta = {}
    with open(map_yaml) as f:
        for line in f:
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    res = float(meta["resolution"])
    origin = [float(x) for x in meta["origin"].strip("[]").split(",")[:2]]
    pgm = os.path.join(os.path.dirname(map_yaml), meta["image"])
    img = cv2.imread(pgm, cv2.IMREAD_GRAYSCALE)
    assert img is not None, pgm
    H = img.shape[0]
    vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    scale = 3
    vis = cv2.resize(vis, None, fx=scale, fy=scale,
                     interpolation=cv2.INTER_NEAREST)

    def to_px(x, y):
        return (int((x - origin[0]) / res * scale),
                int((H - (y - origin[1]) / res) * scale))

    for p, (x, y, yaw) in sorted(points.items()):
        sel = [r for r in rows if r["point"] == p]
        cx, cy = to_px(x, y)
        if not sel:
            color, label = (160, 160, 160), f"{p} (-)"
        else:
            ok = sum(1 for r in sel if r["verdict"] == "성공")
            frac = ok / len(sel)
            # 초록(전부 성공) → 노랑 → 빨강(전부 실패)
            color = (0, int(255 * frac), int(255 * (1 - frac)))
            label = f"{p} {ok}/{len(sel)}"
        cv2.circle(vis, (cx, cy), 10, color, -1)
        cv2.circle(vis, (cx, cy), 10, (0, 0, 0), 1)
        # 방향 표시
        dx, dy = math.cos(yaw), math.sin(yaw)
        cv2.line(vis, (cx, cy),
                 (int(cx + 22 * dx), int(cy - 22 * dy)), (0, 0, 0), 2)
        cv2.putText(vis, label, (cx + 14, cy - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)
        cv2.putText(vis, label, (cx + 14, cy - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.imwrite(out, vis)
    print(f"[지도] {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(HERE, "results.csv"))
    ap.add_argument("--map", default=os.path.join(HERE, "..",
                                                  "rtab_camera_v2_2.yaml"))
    ap.add_argument("--outdir", default=HERE)
    args = ap.parse_args()

    with open(os.path.join(HERE, "points.csv")) as f:
        points = {r["point"]: (float(r["x"]), float(r["y"]),
                               math.radians(float(r["yaw_deg"])))
                  for r in csv.DictReader(f)}
    rows = load_rows(args.csv)
    print(f"[집계] 유효 {len(rows)}행")
    make_table(rows, points, os.path.join(args.outdir, "report_table.md"))
    make_map(rows, points, args.map, os.path.join(args.outdir, "report_map.png"))


if __name__ == "__main__":
    main()
