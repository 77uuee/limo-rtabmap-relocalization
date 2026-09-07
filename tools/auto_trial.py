#!/usr/bin/env python3
"""재위치추정 자동 측정 (로봇에서 실행).

한 번의 호출로: (선택) Nav2로 지점 이동 → 시작 자세 스냅샷(=이 회차의 정답)
→ /rtabmap/reset 으로 cold start → Phase A 정지 20초 → Phase B 자동 회전
→ 판정 → results.csv 기록. 미수렴 시 복구 회전으로 재수렴 시도.

사용:
  # 일반 (이동 + reset + 측정):
  python3 auto_trial.py --point P3 --condition C1 --trial 1
  # launch를 방금 켠 직후 (이동/reset 없이 현재 상태에서 측정, points.csv 정답 사용):
  python3 auto_trial.py --point P1 --condition C1 --trial 3 --no-reset --note launch-cold
  # 배치:
  python3 auto_trial.py --batch "P3:3,P2:3" --condition C1
"""
import argparse
import csv
import math
import os
import sys
import time

import subprocess

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from geometry_msgs.msg import PoseWithCovarianceStamped, PoseStamped, Twist
from nav2_msgs.action import NavigateToPose
from rtabmap_msgs.msg import Info
import tf2_ros

# reset 서비스는 검증 결과 부적합: WM까지 비워버려 재수렴 자체가 불가능해짐.
# cold start는 launch 전체 재시작으로 수행한다 (검증된 방식).
#
# ★ 2026-08-31: 기준 지도 DB가 통째로 날아간 사고가 있었다.
#   /rtabmap/reset 으로 WM을 비운 상태에서 rtabmap이 "정상 종료"되면,
#   비어 있는 메모리가 그대로 DB에 저장되어 지도가 0노드가 된다.
#   → 측정은 절대 원본(MASTER_DB)에 붙지 않는다. 매 회차 사본을 만들어
#     그 사본으로 launch 한다. 사본이 망가져도 원본은 무사하다.
MASTER_DB = os.path.expanduser("~/maps/rtab_camera_master.db")
WORK_DB = "/tmp/reloc_work.db"
# 경로계획 전용 손그림 지도 (펜스 등 depth가 못 보는 장애물 봉인).
# 이 파일이 있으면 자동으로 launch에 넘긴다. 재위치추정에는 영향 없음.
NAV_MAP = os.path.expanduser("~/maps/rtab_camera_nav.yaml")
LAUNCH_PATTERN = "limo_rtabmap_navigation_camera_only.launch"
# launch 부모가 죽어도 자식 노드는 고아로 살아남을 수 있다 (2026-09-01 사고:
# limo_base 3중 실행 → 시리얼 충돌 "Invalid frame! Check sum failed!" + TF 오염).
# 그래서 종료 확인/강제 정리는 부모가 아니라 노드 단위로 한다.
# 주의: 어떤 패턴도 auto_trial 자신의 cmdline과 매칭되면 안 됨 (pkill 자기참조)
NODE_PATTERNS = [
    LAUNCH_PATTERN,          # ros2 launch 부모
    "rtabmap_slam/lib",      # rtabmap 본체
    "rtabmap_sync",          # rgbd_sync
    "limo_base/lib",         # 섀시 드라이버 — 시리얼 포트 점유자
    "__ns:=/camera",         # Orbbec 컴포넌트 컨테이너
    "/nav2_",                # Nav2 노드 전부 (install/nav2_*/lib 경로 매칭)
    "ekf_node",
    "robot_state_publisher",
]


def stack_alive():
    """스택 노드가 하나라도 살아 있으면 그 패턴을 반환."""
    for pat in NODE_PATTERNS:
        if subprocess.run(["pgrep", "-f", pat],
                          capture_output=True).returncode == 0:
            return pat
    return None
LAUNCH_CMD = ("nohup ros2 launch wego "
              "limo_rtabmap_navigation_camera_only.launch.py rviz:=false "
              f"database_path:={WORK_DB} "
              + (f"nav_map:={NAV_MAP} " if os.path.isfile(NAV_MAP) else "")
              + ">> ~/lab_logs_nav_launch.log 2>&1 &")


def db_nodes(path):
    """DB의 노드 수. 지도가 살아 있는지 확인하는 유일하게 믿을 만한 값."""
    import sqlite3
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            return db.execute("SELECT COUNT(*) FROM Node").fetchone()[0]
    except sqlite3.Error:
        return -1


def check_master():
    """측정 시작 전 원본 지도 검사. 여기서 막지 못하면 하루치 데이터가 무의미해진다."""
    if not os.path.isfile(MASTER_DB):
        print(f"[중단] 원본 지도가 없다: {MASTER_DB}\n"
              "  매핑 후 다음으로 원본을 만들어 둘 것:\n"
              "    cp ~/.ros/limo_rtabmap_camera.db ~/maps/rtab_camera_master.db\n"
              "    chmod 444 ~/maps/rtab_camera_master.db")
        return False
    n = db_nodes(MASTER_DB)
    if n <= 0:
        print(f"[중단] 원본 지도가 비어 있다 ({n} nodes): {MASTER_DB}")
        return False
    print(f"[확인] 원본 지도 {MASTER_DB}: {n} nodes")
    return True


def refresh_work_db():
    """원본 → 작업 사본. launch 는 항상 이 사본만 연다."""
    import shutil
    shutil.copyfile(MASTER_DB, WORK_DB)
    os.chmod(WORK_DB, 0o644)

POS_TOL_M = 0.5
PHASE_A_SEC = 20.0
TIMEOUT_SEC = 60.0
RECOVER_SEC = 90.0      # 미수렴 후 복구 회전 최대 시간
ROT_SPEED = 0.35        # rad/s — 매 회차 동일 (사람 손보다 일관적)

HERE = os.path.dirname(os.path.abspath(__file__))
POINTS_CSV = os.path.join(HERE, "points.csv")
RESULTS_CSV = os.path.join(HERE, "results.csv")
# map 열: 어느 기준 지도에서 잰 값인지. 지도를 다시 만들면 좌표계가 바뀌어
# 이전 데이터와 섞을 수 없다 (2026-08-30 map v1 유실 → v2 재매핑).
# truth_src 열: 이 회차의 정답 좌표를 어디서 가져왔나.
#   points = 바닥 테이프 등록 좌표 (points.csv). 회차와 독립된 외부 기준 → 기본값
#   snap   = 회차 시작 시점의 tf 자세 (= rtabmap 자신의 믿음)
# ★ 2026-08-31 17:55 사건으로 기본값을 points 로 바꿨다.
#   로봇은 P1에 서 있는데 믿음은 P7(4 m 밖)이었다. snap 을 정답으로 쓰면 그
#   틀린 좌표가 "정답"이 되어 오차 0 cm 성공으로 기록된다 — 측정 대상이 스스로
#   정답을 정하는 순환논증이고, 정확히 우리가 재려는 실패 모드를 못 보게 만든다.
# snap_* / err_*_snap_* 는 판정에 쓰지 않는다. 두 기준으로 계산해도 결론이
# 같은지 보이는 민감도 분석용 기록.
FIELDS = ["datetime", "map", "point", "condition", "trial", "verdict",
          "t_converge_s", "phase", "err_pos_m", "err_yaw_deg", "x", "y",
          "yaw_deg", "cov_x", "cov_y", "truth_src",
          "snap_x", "snap_y", "snap_yaw_deg",
          "err_pos_snap_m", "err_yaw_snap_deg", "note"]

# 스냅샷이 테이프 좌표에서 이만큼 벗어나면 믿음이 점프한 것으로 본다.
SNAP_WARN_M = 0.7


def yaw_from_quat(q):
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                      1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def ang_diff_deg(a, b):
    """두 각의 차이를 0~180°로. -179°와 179°가 2°가 되도록 감싼다."""
    return math.degrees(abs(math.atan2(math.sin(a - b), math.cos(a - b))))


def nearest_point(points, pose):
    """자세와 가장 가까운 등록 지점. 믿음이 어디로 점프했는지 알려준다."""
    if pose is None:
        return None
    best = min(points.items(),
               key=lambda kv: math.hypot(kv[1][0] - pose[0], kv[1][1] - pose[1]))
    return best[0], math.hypot(best[1][0] - pose[0], best[1][1] - pose[1])


def load_points():
    with open(POINTS_CSV) as f:
        return {r["point"]: (float(r["x"]), float(r["y"]),
                             math.radians(float(r["yaw_deg"])))
                for r in csv.DictReader(f)}


class AutoTrial(Node):
    def __init__(self):
        super().__init__("auto_trial")
        self.loc_msg = None
        self.info_count = 0
        self.create_subscription(PoseWithCovarianceStamped,
                                 "/rtabmap/localization_pose", self.cb_loc, 10)
        self.create_subscription(Info, "/rtabmap/info", self.cb_info, 10)
        self.cmd_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self.nav_cli = ActionClient(self, NavigateToPose, "/navigate_to_pose")
        self.tf_buf = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buf, self)
        # 스크립트가 로봇을 회전시킨 뒤 테이프 방향으로 못 되돌린 상태.
        # True 면 방향 판정을 할 수 없다 (정답 yaw = 테이프 yaw 이므로).
        self.yaw_dirty = False

    def cb_loc(self, msg):
        # cov>=1 은 수렴 전 추측값 → 무시
        if msg.pose.covariance[0] < 1.0:
            self.loc_msg = msg

    def cb_info(self, msg):
        self.info_count += 1

    def spin(self, sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.05)

    # ---- 현재 자세 (tf, 2초 내 신선한 것만) ----
    def get_pose(self, timeout=6.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.05)
            try:
                t = self.tf_buf.lookup_transform("map", "base_link",
                                                 rclpy.time.Time())
                age = (self.get_clock().now().nanoseconds
                       - rclpy.time.Time.from_msg(t.header.stamp).nanoseconds)
                if age > 3e9:      # 오래된 TF = 죽은 스택의 잔상 → 무시
                    continue
                q = t.transform.rotation
                return (t.transform.translation.x, t.transform.translation.y,
                        yaw_from_quat(q))
            except Exception:
                continue
        return None

    def ensure_localized(self):
        """배치 시작 전: 수렴 상태가 아니면 launch 재시작 + 회전으로 수렴시킴"""
        if self.get_pose(3.0) is not None:
            return True
        print("[준비] 미수렴 상태 — launch 재시작 후 수렴 회전")
        if not self.restart_launch():
            return False
        return self.recover()

    # ---- Nav2 이동 ----
    def navigate(self, x, y, yaw, timeout=180.0):
        # launch 재시작을 겪은 클라이언트는 DDS 연결이 낡아 결과 응답을
        # 유실할 수 있다 (서버는 Goal succeeded인데 클라이언트만 타임아웃).
        # 이동마다 클라이언트를 새로 만들어 신선한 연결로 보낸다.
        try:
            self.nav_cli.destroy()
        except Exception:
            pass
        self.nav_cli = ActionClient(self, NavigateToPose, "/navigate_to_pose")
        if not self.nav_cli.wait_for_server(timeout_sec=10.0):
            return False, "nav2 액션 서버 없음"
        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = "map"
        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y
        goal.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(yaw / 2.0)
        fut = self.nav_cli.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=15.0)
        gh = fut.result()
        if gh is None or not gh.accepted:
            return False, "goal 거부"
        rfut = gh.get_result_async()
        rclpy.spin_until_future_complete(self, rfut, timeout_sec=timeout)
        if rfut.result() is None:
            # 결과 응답 유실 대비: 실제 위치가 goal 반경 안이면 성공으로 판정
            pose = self.get_pose(3.0)
            if pose is not None and math.hypot(pose[0]-x, pose[1]-y) < 0.35:
                return True, "결과 응답 유실 — 위치 기준 성공 판정"
            return False, "goal 타임아웃"
        return rfut.result().status == 4, f"status={rfut.result().status}"  # 4=SUCCEEDED

    # ---- 회전 ----
    def rotate(self, on):
        tw = Twist()
        tw.angular.z = ROT_SPEED if on else 0.0
        self.cmd_pub.publish(tw)

    def stop(self):
        for _ in range(3):
            self.rotate(False)
            time.sleep(0.05)

    def align_yaw(self, target, tol=0.09, timeout=40.0):
        """수렴된 믿음을 이용해 테이프 방향(target)으로 제자리 회전 복귀.

        Phase B/복구 회전이 로봇 방향을 틀어놓으면, 다음 회차의 방향 판정
        기준(테이프 yaw)이 무효가 된다. 수렴 상태라면 여기서 되돌려 놓는다.
        tol 0.09 rad ≈ 5° (판정 허용치 30° 대비 충분히 작음).
        """
        end = time.monotonic() + timeout
        try:
            while time.monotonic() < end:
                pose = self.get_pose(2.0)
                if pose is None:
                    return False        # 미수렴 — 믿음이 없으면 되돌릴 수 없다
                err = math.atan2(math.sin(target - pose[2]),
                                 math.cos(target - pose[2]))
                if abs(err) <= tol:
                    return True
                tw = Twist()
                tw.angular.z = ROT_SPEED if err > 0 else -ROT_SPEED
                self.cmd_pub.publish(tw)
            return False
        finally:
            self.stop()

    # ---- launch 재시작 (cold start) ----
    def restart_launch(self):
        subprocess.run(["pkill", "-INT", "-f", LAUNCH_PATTERN])
        # 모든 노드가 내려갈 때까지 대기. 정상 종료도 카메라 해제 + 600MB DB
        # 저장 때문에 30초를 넘길 수 있어 40초까지 봐준다.
        for _ in range(40):
            if stack_alive() is None:
                break
            time.sleep(1.0)
        else:
            # 늦는 노드는 개별 강제 종료. work DB가 저장 중에 죽어도 상관없다
            # (어차피 매 회차 원본에서 새로 복사).
            for pat in NODE_PATTERNS:
                subprocess.run(["pkill", "-9", "-f", pat])
            time.sleep(2.0)
        left = stack_alive()
        if left is not None:
            print(f"  [중단] 이전 스택이 안 내려감 (pattern: {left}) — 수동 정리 필요")
            return False
        refresh_work_db()   # 매 회차 깨끗한 사본으로 시작 (원본 보호 + 오염 차단)
        subprocess.run(LAUNCH_CMD, shell=True, executable="/bin/bash")
        # rtabmap이 프레임 처리를 시작할 때까지 대기 → 그 순간이 측정 t0.
        # 주의: 이 대기는 DB 로드 시간을 포함한다. 이어매핑으로 DB가 커지면
        # 로드가 길어진다 (888MB에서 90초 초과 실측, 2026-09-01) → 300초.
        self.info_count = 0
        end = time.monotonic() + 300.0
        while time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self.info_count > 0:
                return True
        return False

    # ---- 측정 본체 ----
    def measure(self):
        """reset(또는 launch 직후) 상태에서 수렴까지 측정. 반환: (msg, t, phase)"""
        self.loc_msg = None
        t0 = time.monotonic()
        rotating = False
        try:
            while True:
                rclpy.spin_once(self, timeout_sec=0.05)
                el = time.monotonic() - t0
                if self.loc_msg is not None:
                    ph = "A" if el <= PHASE_A_SEC else "B"
                    return self.loc_msg, el, ph
                if el >= TIMEOUT_SEC:
                    return None, None, None
                if el >= PHASE_A_SEC and not rotating:
                    rotating = True
                    self.yaw_dirty = True
                    print(f"  [{el:4.1f}s] Phase B — 자동 회전 시작")
                if rotating:
                    self.rotate(True)
        finally:
            self.stop()

    def recover(self):
        """미수렴 후 복구: 계속 회전하며 재수렴 대기"""
        print("  [복구] 재수렴 회전...")
        self.yaw_dirty = True
        self.loc_msg = None
        t0 = time.monotonic()
        try:
            while time.monotonic() - t0 < RECOVER_SEC:
                rclpy.spin_once(self, timeout_sec=0.05)
                if self.loc_msg is not None:
                    print(f"  [복구] 재수렴 성공 ({time.monotonic()-t0:.0f}s)")
                    return True
                self.rotate(True)
            return False
        finally:
            self.stop()


def ensure_results_schema():
    """기존 results.csv 를 새 컬럼 구성으로 올린다.

    DictWriter 는 헤더를 확인하지 않고 FIELDS 순서대로 쓴다. 파일의 헤더가
    옛 구성인 채로 새 행을 붙이면 값이 다른 열로 밀려 들어가 데이터가 조용히
    망가진다. 그래서 붙이기 전에 반드시 헤더를 맞춘다.
    """
    if not os.path.exists(RESULTS_CSV):
        return
    with open(RESULTS_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
        f.seek(0)
        header = next(csv.reader(f), [])
    if header == FIELDS:
        return
    bak = RESULTS_CSV + time.strftime(".bak-%Y%m%d_%H%M%S")
    os.replace(RESULTS_CSV, bak)
    with open(RESULTS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            out = dict.fromkeys(FIELDS, "")
            out.update({k: v for k, v in r.items() if k in FIELDS})
            # 이행 전 데이터는 전부 스냅샷 기준으로 잰 것이다.
            if not out.get("truth_src"):
                out["truth_src"] = "snap"
            w.writerow(out)
    print(f"[이행] results.csv 컬럼 갱신 ({len(rows)}행). 원본 백업: {bak}")


def append_row(row):
    new = not os.path.exists(RESULTS_CSV)
    with open(RESULTS_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def where(node, points):
    """지금 rtabmap 이 어디라고 믿는지 + 가장 가까운 등록 지점.

    회차 시작 전 1초 점검용. 믿음이 옆 지점으로 점프해 있으면 여기서 걸린다.
    """
    pose = node.get_pose(5.0)
    if pose is None:
        print("[미수렴] map->base_link TF 없음 — 아직 자기 위치를 못 찾았다")
        return
    print(f"[믿음] x={pose[0]:.3f}  y={pose[1]:.3f}  "
          f"yaw={math.degrees(pose[2]):.1f}°")
    print(f"{'지점':<5} {'거리(m)':>8} {'방향차(°)':>10}")
    for name, (x, y, yaw) in sorted(points.items()):
        d = math.hypot(x - pose[0], y - pose[1])
        mark = "  ←" if d <= SNAP_WARN_M else ""
        print(f"{name:<5} {d:8.2f} {ang_diff_deg(yaw, pose[2]):10.1f}{mark}")


def run_trial(node, points, point, condition, trial, do_nav, do_reset, note,
              map_tag="v2", truth_src="points"):
    print(f"[{point} / {condition} / #{trial}] 시작")
    truth = points[point]

    if do_nav:
        print(f"  Nav2 이동 → ({truth[0]:.2f}, {truth[1]:.2f})")
        ok, msg = node.navigate(*truth)
        if not ok:
            print(f"  [중단] Nav2 실패: {msg}")
            return False
        node.spin(2.0)  # 정지 안정화

    # 이전 회차의 Phase B/복구 회전으로 방향이 테이프에서 틀어졌을 수 있다.
    # 수렴 상태면 테이프 방향으로 되돌리고, 못 되돌리면 이번 회차는 위치만 판정.
    if do_reset and node.yaw_dirty:
        if node.align_yaw(truth[2]):
            print("  [정렬] 테이프 방향으로 복귀 완료")
            node.yaw_dirty = False
        else:
            print("  [주의] 방향 복귀 불가(미수렴) — 이번 회차는 위치만 판정")
    yaw_valid = not node.yaw_dirty

    # 시작 자세 스냅샷: truth_src=snap 이면 정답, points 면 "믿음이 점프했나"를
    # 보는 창. 어느 쪽이든 기록은 남긴다 (두 기준 비교용).
    snap = node.get_pose() if do_reset else None
    snap_off = None
    if do_reset:
        if snap is None:
            print("  [주의] 스냅샷 불가(미수렴)")
            if truth_src == "snap":
                print("  [중단] --truth snap 인데 스냅샷이 없다 — 수렴 후 다시 할 것")
                return False
        else:
            snap_off = math.hypot(snap[0] - truth[0], snap[1] - truth[1])
            print(f"  스냅샷 ({snap[0]:.2f}, {snap[1]:.2f}, "
                  f"{math.degrees(snap[2]):.0f}°)  테이프와 {snap_off:.2f} m")
            if snap_off > SNAP_WARN_M:
                if truth_src == "snap":
                    # 지점 이름 오타/오탐 방지: snap 이 정답일 때는 여기서 멈춘다
                    print(f"  [중단] 스냅샷이 {point} 좌표와 "
                          f"{SNAP_WARN_M} m 이상 차이 — 지점 이름 확인!")
                    return False
                # 정답이 테이프이므로 측정 자체는 진행할 수 있다. 다만 이건
                # 가짜 루프 클로저 신호이므로 크게 남긴다 (결과물 소재이기도 함).
                near = nearest_point(points, snap)
                print(f"  [경고] rtabmap 믿음이 테이프에서 {snap_off:.2f} m "
                      "벗어나 있다 — 가짜 루프 클로저 의심.")
                if near:
                    print(f"         믿음에 가장 가까운 등록 지점: "
                          f"{near[0]} ({near[1]:.2f} m)")
                print(f"         로봇이 {point} 테이프 위에 있는 게 맞는지 확인할 것.")
        print("  launch 재시작(cold start)...")
        if not node.restart_launch():
            print("  [중단] launch 재시작 후 rtabmap 기동 실패")
            return False
        print("  rtabmap 기동 — 측정 시작")

    # 판정에 쓰는 정답. 기본은 테이프(회차와 독립된 외부 기준).
    truth_used = snap if (truth_src == "snap" and snap) else truth
    print(f"  정답 = {'스냅샷' if truth_used is snap else '테이프 ' + point}"
          f" ({truth_used[0]:.2f}, {truth_used[1]:.2f}, "
          f"{math.degrees(truth_used[2]):.0f}°)")

    msg, t, ph = node.measure()
    row = dict.fromkeys(FIELDS, "")
    if snap_off is not None and snap_off > SNAP_WARN_M:
        note = f"{note}+snapjump{snap_off:.2f}m"
    if not yaw_valid:
        note = f"{note}+yawfree"
    row.update(datetime=time.strftime("%Y-%m-%d %H:%M:%S"), map=map_tag,
               point=point, condition=condition, trial=trial, note=note,
               truth_src=truth_src)
    if snap is not None:
        row.update(snap_x=f"{snap[0]:.3f}", snap_y=f"{snap[1]:.3f}",
                   snap_yaw_deg=f"{math.degrees(snap[2]):.1f}")

    if msg is None:
        row["verdict"] = "미수렴"
        print("  [결과] 미수렴 (60s)")
        append_row(row)
        if node.recover():      # 다음 회차 위해 재수렴 시도
            return True
        if not do_nav:
            # 테이프 정답 + 수동 이동 체제에서는 수렴 없이도 다음 회차를
            # cold start 할 수 있다. 배치를 여기서 끊지 않는다.
            print("  [주의] 재수렴 실패 — 미수렴 상태로 다음 회차 계속")
            return True
        return False

    p = msg.pose.pose.position
    yaw = yaw_from_quat(msg.pose.pose.orientation)
    ep = math.hypot(p.x - truth_used[0], p.y - truth_used[1])
    ey = ang_diff_deg(yaw, truth_used[2])
    # Phase B(회전 중)와 방향 미복귀(yawfree) 회차는 위치만 판정
    ok = (ep <= POS_TOL_M if (ph == "B" or not yaw_valid)
          else (ep <= POS_TOL_M and ey <= 30.0))
    row.update(verdict="성공" if ok else "오탐", t_converge_s=f"{t:.1f}",
               phase=ph, err_pos_m=f"{ep:.3f}", err_yaw_deg=f"{ey:.1f}",
               x=f"{p.x:.3f}", y=f"{p.y:.3f}", yaw_deg=f"{math.degrees(yaw):.1f}",
               cov_x=f"{msg.pose.covariance[0]:.4f}",
               cov_y=f"{msg.pose.covariance[7]:.4f}")
    # 판정에는 안 쓰지만, 스냅샷 기준 오차도 같이 남긴다 (민감도 분석용)
    if snap is not None:
        row.update(err_pos_snap_m=f"{math.hypot(p.x - snap[0], p.y - snap[1]):.3f}",
                   err_yaw_snap_deg=f"{ang_diff_deg(yaw, snap[2]):.1f}")
    print(f"  [결과] {row['verdict']}  t={t:.1f}s (Phase {ph})  "
          f"오차 {ep:.2f} m / {ey:.0f}°")
    append_row(row)
    if not ok:
        if node.recover():      # 오탐이면 위치가 틀렸을 수 있음 → 복구
            return True
        if not do_nav:
            print("  [주의] 재수렴 실패 — 미수렴 상태로 다음 회차 계속")
            return True
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--point")
    ap.add_argument("--condition")   # --where 외에는 필수 (아래에서 검사)
    ap.add_argument("--trial", type=int, default=1)
    ap.add_argument("--batch", help='예: "P3:3,P2:3" / 재개는 "P1:2-3"')
    ap.add_argument("--no-nav", action="store_true")
    ap.add_argument("--no-reset", action="store_true")
    ap.add_argument("--note", default="auto")
    ap.add_argument("--map", default="v2",
                    help="기준 지도 태그. 재매핑하면 반드시 올릴 것")
    ap.add_argument("--truth", choices=["points", "snap"], default="points",
                    help="정답 좌표 출처. points=바닥 테이프(기본, 외부 기준) / "
                         "snap=회차 시작 시점의 rtabmap 믿음(순환논증 주의)")
    ap.add_argument("--where", action="store_true",
                    help="측정 없이 현재 믿음과 등록 지점 거리만 출력")
    args = ap.parse_args()

    ensure_results_schema()

    if args.where:
        rclpy.init()
        node = AutoTrial()
        try:
            where(node, load_points())
        finally:
            node.destroy_node()
            rclpy.shutdown()
        return

    if not args.condition:
        ap.error("--condition 이 필요하다 (--where 만 예외)")

    if not check_master():
        sys.exit(1)

    rclpy.init()
    node = AutoTrial()
    points = load_points()
    try:
        if args.batch:
            # 수동 이동 + 테이프 정답 체제(--no-nav)에서는 사전 수렴이 필수가
            # 아니다 — cold start 측정 자체가 수렴 시도다. Nav2 이동이 필요할
            # 때만 수렴을 요구한다.
            if not args.no_nav and not node.ensure_localized():
                print("[중단] 초기 수렴 실패 — 사람 개입 필요")
                return
            for item in args.batch.split(","):
                # "P1:3" = 1~3회차, "P1:2-3" = 2~3회차 (중단 후 재개용)
                pt, n = item.split(":")
                if "-" in n:
                    a, b = n.split("-")
                    trials = range(int(a), int(b) + 1)
                else:
                    trials = range(1, int(n) + 1)
                for tr in trials:
                    # 배치도 --no-nav 를 존중한다. 조이스틱 이동이 기본이 된
                    # 뒤로는 "같은 지점 3회 반복"이 배치의 주 용도다.
                    if not run_trial(node, points, pt, args.condition, tr,
                                     not args.no_nav, not args.no_reset,
                                     args.note, args.map, args.truth):
                        print(f"[배치 중단] {pt} #{tr} 이후 복구 실패 — "
                              "사람 개입 필요")
                        return
            print("[배치 완료]")
        else:
            run_trial(node, points, args.point, args.condition, args.trial,
                      not args.no_nav, not args.no_reset, args.note, args.map,
                      args.truth)
    finally:
        node.stop()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
