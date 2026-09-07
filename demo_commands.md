# 박사님 시연용 명령어 정리 (2026-09-02 기준, map v2.4)

## ⚠ 시연 전 최우선 확인 — 카메라 (2026-09-02 종료 시점 고장 상태)
마지막 세션이 Orbbec 카메라 초기화 실패(`Failed to setup devices`) 상태로
끝났음. 전원 재부팅으로 풀릴 수도 있지만, 안 풀리면 **카메라 USB를 뽑았다
5초 후 재플러그**. 스택 켠 뒤 판정은 로그가 아니라 토픽 수신으로:
```bash
timeout 8 ros2 topic echo /camera/color/image_raw/compressed --field header.stamp.sec
```
숫자가 찍히면 정상. 안 찍히면 재플러그 후 스택 재시작.

## 시연 전 체크 3가지
1. **의자·가구를 옮기지 말 것.** 오늘 오전에 의자 몇 개가 살짝 이동한 것만으로
   P1이 미수렴됐음 (이어매핑으로 복구, v2.4). 시연 전에 배치가 바뀌었으면 아래
   "배치가 바뀌었을 때" 참고.
2. 조이스틱은 **명령 모드**(SWB 위치 확인). RC 모드면 스틱 드리프트로 저절로 돎.
3. 로봇 로그인 시 conda 메뉴에서 **1) Global Environment** 선택.

## 방법 A — 원커맨드 시연 (권장, 제일 간단)
로봇을 **P1 테이프**(강의실 중앙 통로)에 위치+방향 맞춰 놓고, 로봇 터미널에서:

```bash
cd ~/reloc_test
python3 auto_trial.py --point P1 --condition C1 --trial 0 --no-nav --map v2.4 --note demo
```

- 알아서 함: 원본 지도 검사 → 사본 생성 → 스택 cold start → 60초 측정 → 판정 출력
- 기대 출력: `[결과] 성공  t=0.4s (Phase A)  오차 0.08 m / 10°` 수준
  (P1은 오늘 6/6 성공, 전부 3초 이내)
- `--trial 0 --note demo` 라서 통계에는 안 섞임
- **실패해도 정상 범위** — cold start는 확률적임 (그게 이 실험의 결론).
  한 번 더 돌리면 됨. P2·P7에서 하면 실패 확률이 높은 것도 "정상 데이터"

## 방법 B — 화면 보면서 (rtabmap_viz 루프 클로저 시연)
NoMachine(또는 로봇 화면) 터미널에서:

```bash
# 1) 원본 지도 사본 준비 (원본은 읽기 전용이라 직접 열면 안 됨)
cp ~/maps/rtab_camera_master.db /tmp/reloc_work.db && chmod 644 /tmp/reloc_work.db

# 2) 스택 실행 — rtabmap_viz 창이 뜸 (Loop closure detection 패널 주목)
ros2 launch wego limo_rtabmap_navigation_camera_only.launch.py \
  database_path:=/tmp/reloc_work.db nav_map:=/home/wego/maps/rtab_camera_nav.yaml
```

- 수렴 순간 Loop closure detection 패널에 초록 테두리 매칭 이미지가 뜸
- 현재 믿음 확인 (다른 터미널): `python3 ~/reloc_test/auto_trial.py --where`
- 로봇을 조이스틱으로 옮겨 다니면 위치 추적이 따라오는 것도 보여줄 수 있음

## 결과 보여주기 (측정 데이터)
```bash
cat ~/reloc_test/results.csv          # 원본 데이터 (로봇)
```
맥북: `3d map/tools/report_table.md` (성공률 표), `report_map.png` (실패 지점 지도)

## 배치가 바뀌었을 때 (시연 직전 미수렴 대비)
방법 A를 P1에서 돌려 미수렴이면 배치 변화 의심. 복구는 5분 이어매핑:
```bash
cp ~/maps/rtab_camera_master.db ~/.ros/limo_rtabmap_camera.db && chmod 644 ~/.ros/limo_rtabmap_camera.db
ros2 launch wego limo_rtabmap_mapping_camera_only.launch.py
# 조이스틱으로 바뀐 구역을 천천히 2~3회 재방문 → Ctrl+C
bash ~/reloc_test/save_master.sh      # 새 원본 고정 (기존 것은 자동 백업)
```

## 주의
- `~/maps/rtab_camera_master.db` 는 **절대 직접 열지 말 것** (읽기 전용 원본).
  측정·시연은 전부 `/tmp/reloc_work.db` 사본으로 돎 — auto_trial이 자동 처리
- 오늘(9/2) C3는 **주간 소등**(창측 자연광 잔존) 조건이었음. 저녁 소등은 더
  어두워서 결과가 다를 수 있음 — 시연은 실내등 켠 C1 조건이 안전
- 스택 종료: `Ctrl+C`. 종료가 지저분하면 재부팅해도 무방 (원본 지도는 읽기 전용이라 안전)
