#!/usr/bin/env python3
"""재위치추정 1회차 자동 기록기 (로봇에서 실행).

navigation_camera_only launch를 띄운 직후 이 스크립트를 실행하면:
  - /rtabmap/localization_pose 첫 발행까지의 시간을 잰다
  - 발행된 자세를 정답 좌표와 비교해 성공/오탐을 판정한다
  - 결과를 CSV 한 줄로 저장한다 (60회 반복 대비 사람 실수 제거)

사용:
  python3 relocation_logger.py --point P1 --condition C1 --trial 1
  python3 relocation_logger.py --point P1 --condition C1 --trial 1 --save-truth
      (C1 첫 회차: 수렴 자세를 그 지점의 정답으로 points.csv에 저장)

판정 기준 (measurement_plan.md 0장):
  성공   = 첫 발행 자세가 정답에서 0.5 m / 30° 이내
  오탐   = 발행됐지만 허용치 초과
  미수렴 = 60초까지 발행 없음
  Phase A = 0~20초(정지), Phase B = 20~60초(제자리 회전)
"""
import argparse
import csv
import math
import os
import sys
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseWithCovarianceStamped
from rtabmap_msgs.msg import Info

POS_TOL_M = 0.5      # 위치 허용 오차
YAW_TOL_DEG = 30.0   # 방향 허용 오차
PHASE_A_SEC = 20.0   # 정지 대기
TIMEOUT_SEC = 60.0   # 총 관측 시간

HERE = os.path.dirname(os.path.abspath(__file__))
POINTS_CSV = os.path.join(HERE, "points.csv")   # point,x,y,yaw_deg
RESULTS_CSV = os.path.join(HERE, "results.csv")


def yaw_from_quat(q):
    # 평면 로봇이므로 z-yaw만 필요. 쿼터니언 → yaw 표준 변환식.
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                      1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def load_truth(point):
    if not os.path.exists(POINTS_CSV):
        return None
    with open(POINTS_CSV) as f:
        for row in csv.DictReader(f):
            if row["point"] == point:
                return (float(row["x"]), float(row["y"]),
                        math.radians(float(row["yaw_deg"])))
    return None


def save_truth(point, x, y, yaw):
    rows = []
    if os.path.exists(POINTS_CSV):
        with open(POINTS_CSV) as f:
            rows = [r for r in csv.DictReader(f) if r["point"] != point]
    rows.append({"point": point, "x": f"{x:.3f}", "y": f"{y:.3f}",
                 "yaw_deg": f"{math.degrees(yaw):.1f}"})
    with open(POINTS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["point", "x", "y", "yaw_deg"])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["point"]))


class Logger(Node):
    def __init__(self):
        super().__init__("relocation_logger")
        self.msg = None
        self.t_recv = None
        self.t0 = None                # rtabmap 처리 시작(/rtabmap/info 첫 수신) 시점
        self.phase_b_announced = False
        # rtabmap의 localization_pose는 기본(RELIABLE) QoS라 기본 구독으로 받힘
        self.create_subscription(
            PoseWithCovarianceStamped, "/rtabmap/localization_pose",
            self.cb, 10)
        # 측정 시계는 스크립트 시작이 아니라 rtabmap이 프레임 처리를 시작한
        # 순간부터 돌린다 → launch 부팅 시간(~15초)이 수렴 시간에 섞이지 않음
        self.create_subscription(Info, "/rtabmap/info", self.cb_info, 10)

    def cb_info(self, msg):
        if self.t0 is None:
            self.t0 = time.monotonic()
            print("[기동 감지] rtabmap 처리 시작 — 측정 시계 개시")

    def cb(self, msg):
        if self.t0 is None:
            return                    # 스택 기동 전 메시지는 무시
        # cov 9999 = 아직 수렴 못 한 추측값 → 판정 대상 아님
        if msg.pose.covariance[0] >= 1.0:
            return
        if self.msg is None:          # 수렴된 첫 발행만 판정 대상
            self.msg = msg
            self.t_recv = time.monotonic() - self.t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--point", required=True)
    ap.add_argument("--condition", required=True)
    ap.add_argument("--trial", type=int, required=True)
    ap.add_argument("--map", default="v2",
                    help="기준 지도 태그. 재매핑하면 반드시 올릴 것")
    ap.add_argument("--save-truth", action="store_true",
                    help="이번 수렴 자세를 이 지점의 정답으로 저장 (C1 1회차용)")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    truth = load_truth(args.point)
    if truth is None and not args.save_truth:
        sys.exit(f"[중단] {POINTS_CSV}에 {args.point} 정답이 없음. "
                 f"C1 1회차를 --save-truth로 먼저 실행할 것")

    rclpy.init()
    node = Logger()
    print(f"[시작] {args.point} / {args.condition} / #{args.trial} — "
          f"rtabmap 기동 대기 중 (이제 launch를 실행하세요)")

    t_script = time.monotonic()
    while rclpy.ok() and node.msg is None:
        rclpy.spin_once(node, timeout_sec=0.1)
        if node.t0 is None:
            # 스택이 아직 안 뜸 — 90초까지만 기다림
            if time.monotonic() - t_script > 90.0:
                print("[중단] 90초 내 rtabmap 기동 감지 실패 — launch 상태 확인")
                break
            continue
        el = time.monotonic() - node.t0
        if el >= PHASE_A_SEC and not node.phase_b_announced:
            node.phase_b_announced = True
            print(f"[{el:5.1f}s] Phase B — 제자리 저속 회전 시작하세요")
        if el >= TIMEOUT_SEC:
            break

    # ---- 판정 ----
    row = {
        "datetime": time.strftime("%Y-%m-%d %H:%M:%S"),
        # map: 어느 기준 지도에서 잰 값인지. 재매핑하면 좌표계가 바뀌므로
        # 이전 지도의 데이터와 섞으면 안 된다 (auto_trial.py와 같은 스키마).
        "map": args.map,
        "point": args.point, "condition": args.condition, "trial": args.trial,
        "verdict": "", "t_converge_s": "", "phase": "",
        "err_pos_m": "", "err_yaw_deg": "",
        "x": "", "y": "", "yaw_deg": "", "cov_x": "", "cov_y": "",
        # 정답 등록 회차는 오차가 자동으로 0이라(자기 자신과 비교) 측정 통계에서
        # 제외해야 함 → note로 자동 표시
        "note": ("truth-reg " + args.note).strip() if args.save_truth else args.note,
    }

    if node.msg is None:
        row["verdict"] = "미수렴"
        print(f"[결과] 미수렴 ({TIMEOUT_SEC:.0f}초 초과)")
    else:
        p = node.msg.pose.pose.position
        yaw = yaw_from_quat(node.msg.pose.pose.orientation)
        cov = node.msg.pose.covariance
        row.update(t_converge_s=f"{node.t_recv:.1f}",
                   phase="A" if node.t_recv <= PHASE_A_SEC else "B",
                   x=f"{p.x:.3f}", y=f"{p.y:.3f}",
                   yaw_deg=f"{math.degrees(yaw):.1f}",
                   cov_x=f"{cov[0]:.4f}", cov_y=f"{cov[7]:.4f}")

        if args.save_truth:
            save_truth(args.point, p.x, p.y, yaw)
            truth = (p.x, p.y, yaw)
            print(f"[정답 저장] {args.point} = ({p.x:.2f}, {p.y:.2f}, "
                  f"{math.degrees(yaw):.0f}°) → 눈으로 맞는지 꼭 확인!")

        err_pos = math.hypot(p.x - truth[0], p.y - truth[1])
        # 각도 차는 ±π 래핑 처리
        err_yaw = math.degrees(abs(math.atan2(
            math.sin(yaw - truth[2]), math.cos(yaw - truth[2]))))
        # Phase B는 회전 중 수렴 → 방향은 시작 자세와 당연히 다름.
        # 제자리 회전이라 위치 기준만 판정하고 err_yaw는 참고 기록.
        in_phase_b = node.t_recv > PHASE_A_SEC
        ok = err_pos <= POS_TOL_M and (in_phase_b or err_yaw <= YAW_TOL_DEG)
        row.update(verdict="성공" if ok else "오탐",
                   err_pos_m=f"{err_pos:.3f}", err_yaw_deg=f"{err_yaw:.1f}")
        print(f"[결과] {row['verdict']}  t={node.t_recv:.1f}s "
              f"(Phase {row['phase']})  오차 {err_pos:.2f} m / {err_yaw:.0f}°")

    new_file = not os.path.exists(RESULTS_CSV)
    with open(RESULTS_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new_file:
            w.writeheader()
        w.writerow(row)
    print(f"[저장] {RESULTS_CSV}")

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
