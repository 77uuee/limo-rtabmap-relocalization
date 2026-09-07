"""Localize in a camera-only RTAB-Map database and navigate on its map.

Camera-only variant per RTABMap_LIMO_Manual section 5 (NAV):
- Grid/Sensor 1 so the occupancy grid is regenerated from the camera
- no /scan subscription; localization relies on visual loop closures only

NOTE: Nav2's costmap obstacle layer in diff_navigation_params.yaml still
expects /scan. Without the LiDAR it simply receives nothing, so live
obstacle avoidance is degraded — keep speeds low and supervise the robot.
"""

import os
import shutil
import sqlite3

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
    OpaqueFunction,
    TimerAction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import (
    LaunchConfiguration,
    PathJoinSubstitution,
    PythonExpression,
)
from launch_ros.actions import Node, SetRemap
from launch_ros.substitutions import FindPackageShare
from nav2_common.launch import RewrittenYaml


RTABMAP_MAPPING_PARAMETERS = " ".join(
    [
        "--Grid/Sensor 1",
        # 재위치추정 실험용: 기본값(0.1m/0.1rad)은 로봇이 움직여야만 루프
        # 클로저를 시도함 → 정지 상태 수렴 측정(Phase A)이 불가능해짐.
        # 0으로 두면 정지 중에도 매 주기(1Hz) 재시도한다.
        "--RGBD/LinearUpdate 0",
        "--RGBD/AngularUpdate 0",
        # 2026-08-31: 자율 이동 중 책상 줄 반복 무늬로 잘못된 루프 클로저가
        # inlier 20개 문턱을 우연히 통과 → 위치 점프 → 벽 충돌.
        # 기하 검증 기준을 30으로 올려 우연 통과를 차단한다.
        # ※ 측정 조건의 일부이므로 C1~C4 전 회차 동안 바꾸지 말 것.
        "--Vis/MinInliers 30",
    ]
)


# 측정용 작업 사본. rtabmap은 localization 모드에서도 종료 시 메모리를 DB에
# 덮어쓰므로(2026-08-30 지도 유실 사고), 기준 지도 원본은 절대 직접 열지 않는다.
# 원본은 save_master.sh 가 만든 읽기 전용 파일이고, 여기서 매 실행마다 사본을
# 새로 뜬다. 사본이 망가져도 다음 실행에서 원본으로 다시 덮어써진다.
MASTER_DB = os.path.expanduser("~/maps/rtab_camera_master.db")
WORK_DB = "/tmp/reloc_work.db"


def prepare_database(context):
    database_path = os.path.expanduser(
        LaunchConfiguration("database_path").perform(context)
    )
    if database_path == WORK_DB and os.path.isfile(MASTER_DB):
        shutil.copyfile(MASTER_DB, database_path)
        os.chmod(database_path, 0o644)
        print(f"[prepare_database] {MASTER_DB} → {database_path} (사본 갱신)")
    return validate_database(context)


def validate_database(context):
    database_path = os.path.expanduser(
        LaunchConfiguration("database_path").perform(context)
    )
    if not os.path.isfile(database_path):
        raise RuntimeError(
            "RTAB-Map database is missing: "
            f"{database_path}. Run limo_rtabmap_mapping.launch.py first."
        )
    # 파일 크기 검사만으로는 부족하다. 2026-08-30에 /rtabmap/reset 후 정상
    # 종료된 DB가 120 KB짜리 "스키마만 남은 빈 DB"가 되었는데, 크기 검사는
    # 이를 통과시켜 의미 없는 측정을 계속하게 만들었다. 노드 수로 검사한다.
    try:
        with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as db:
            nodes = db.execute("SELECT COUNT(*) FROM Node").fetchone()[0]
    except sqlite3.Error as error:
        raise RuntimeError(
            f"RTAB-Map database is not readable: {database_path} ({error})"
        )
    if nodes == 0:
        raise RuntimeError(
            f"RTAB-Map database has 0 nodes (map is empty): {database_path}. "
            "Re-run limo_rtabmap_mapping_camera_only.launch.py."
        )
    print(f"[validate_database] {database_path}: {nodes} nodes")
    return []


def include_launch(package_name, filename, launch_arguments=None, remappings=None):
    return GroupAction(
        scoped=True,
        actions=[
            *[
                SetRemap(src=source, dst=destination)
                for source, destination in (remappings or [])
            ],
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    PathJoinSubstitution(
                        [FindPackageShare(package_name), "launch", filename]
                    )
                ),
                launch_arguments=(launch_arguments or {}).items(),
            )
        ],
    )


def safe_nav2_parameters(nav_map):
    source_file = PathJoinSubstitution(
        [
            FindPackageShare("wego_2d_nav"),
            "params",
            "diff_navigation_params.yaml",
        ]
    )
    rewrites = {
        "controller_server.ros__parameters.controller_frequency": "10.0",
        "controller_server.ros__parameters.FollowPath.max_vel_x": "0.35",
        "controller_server.ros__parameters.FollowPath.max_speed_xy": "0.35",
        "controller_server.ros__parameters.FollowPath.max_vel_theta": "0.8",
        "controller_server.ros__parameters.FollowPath.acc_lim_x": "0.8",
        "controller_server.ros__parameters.FollowPath.decel_lim_x": "-0.8",
        "controller_server.ros__parameters.FollowPath.acc_lim_theta": "1.5",
        "controller_server.ros__parameters.FollowPath.decel_lim_theta": "-1.5",
        "controller_server.ros__parameters.FollowPath.trans_stopped_velocity": "0.05",
        "behavior_server.ros__parameters.max_rotational_vel": "0.6",
        "behavior_server.ros__parameters.min_rotational_vel": "0.15",
        "behavior_server.ros__parameters.rotational_acc_lim": "1.5",
        "velocity_smoother.ros__parameters.smoothing_frequency": "10.0",
        "global_costmap.global_costmap.ros__parameters.inflation_layer.inflation_radius": "0.25",
        "local_costmap.local_costmap.ros__parameters.inflation_layer.inflation_radius": "0.25",
        "global_costmap.global_costmap.ros__parameters.obstacle_layer.scan.obstacle_max_range": "6.0",
        # nav_map(그린 지도)이 주어지면 경로계획용 static layer만 그 지도를 본다.
        # rtabmap의 /map(재위치추정·실험 대상)은 건드리지 않는다 — depth가 못 보는
        # 펜스 등을 사람이 그려 넣어 planner가 그리로 계획하지 않게 하는 용도.
        "global_costmap.global_costmap.ros__parameters.static_layer.map_topic": PythonExpression(
            ["'/map_nav' if '", nav_map, "' else '/map'"]
        ),
        "global_costmap.global_costmap.ros__parameters.obstacle_layer.scan.raytrace_max_range": "8.0",
        "local_costmap.local_costmap.ros__parameters.obstacle_layer.scan.obstacle_max_range": "2.5",
        "local_costmap.local_costmap.ros__parameters.obstacle_layer.scan.raytrace_max_range": "3.0",
    }
    return RewrittenYaml(
        source_file=source_file,
        param_rewrites=rewrites,
        convert_types=True,
    )


def rtabmap_arguments(database_path, initial_pose, rtabmap_viz):
    return {
        "localization": "true",
        "database_path": database_path,
        "initial_pose": initial_pose,
        "frame_id": "base_link",
        "map_frame_id": "map",
        "map_topic": "/map",
        "publish_tf_map": "true",
        "visual_odometry": "false",
        "publish_tf_odom": "false",
        "odom_topic": "/odometry/filtered",
        "rgb_topic": "/camera/color/image_raw",
        "depth_topic": "/camera/depth/image_raw",
        "camera_info_topic": "/camera/color/camera_info",
        "rgbd_sync": "true",
        "approx_rgbd_sync": "true",
        "approx_sync": "true",
        "approx_sync_max_interval": "0.03",
        "subscribe_scan": "false",
        # "scan_topic": "/scan",
        # "imu_topic": "/imu",
        "wait_for_transform": "1.0",
        # "use_action_for_goal": "true",
        "rtabmap_viz": rtabmap_viz,
        "rviz": "false",
        "log_level": "info",
        "rtabmap_args": RTABMAP_MAPPING_PARAMETERS,
    }


def generate_launch_description():
    database_path = LaunchConfiguration("database_path")
    initial_pose = LaunchConfiguration("initial_pose")
    camera_degree = LaunchConfiguration("camera_degree")
    rtabmap_viz = LaunchConfiguration("rtabmap_viz")
    rviz = LaunchConfiguration("rviz")
    nav_map = LaunchConfiguration("nav_map")
    nav_map_given = IfCondition(PythonExpression(["'", nav_map, "' != ''"]))

    robot_bringup = include_launch(
        "wego",
        "limo_rtabmap_bringup_camera_only.launch.py",
        {"camera_degree": camera_degree},
    )
    rtabmap = include_launch(
        "rtabmap_launch",
        "rtabmap.launch.py",
        rtabmap_arguments(database_path, initial_pose, rtabmap_viz),
        # RViz's 2D Pose Estimate tool publishes on /initialpose, while the
        # namespaced RTAB-Map node would otherwise listen on
        # /rtabmap/initialpose.
        remappings=[("initialpose", "/initialpose")],
    )
    nav2 = include_launch(
        "nav2_bringup",
        "navigation_launch.py",
        {
            "use_sim_time": "false",
            "autostart": "true",
            # Humble's navigation launch evaluates this as a Python expression.
            "use_composition": "False",
            "params_file": safe_nav2_parameters(nav_map),
        },
    )
    # 경로계획 전용 지도 서버 (nav_map 인자를 줄 때만 뜸)
    nav_map_server = Node(
        package="nav2_map_server",
        executable="map_server",
        name="map_server_nav",
        output="screen",
        condition=nav_map_given,
        parameters=[{
            "yaml_filename": nav_map,
            "topic_name": "map_nav",
            "frame_id": "map",
        }],
    )
    nav_map_lifecycle = Node(
        package="nav2_lifecycle_manager",
        executable="lifecycle_manager",
        name="lifecycle_manager_nav_map",
        output="screen",
        condition=nav_map_given,
        parameters=[{
            "autostart": True,
            "node_names": ["map_server_nav"],
        }],
    )
    rviz_node = Node(
        package="rviz2",
        executable="rviz2",
        name="rviz2",
        output="screen",
        condition=IfCondition(rviz),
        arguments=[
            "-d",
            PathJoinSubstitution(
                [FindPackageShare("wego"), "rviz", "navigation.rviz"]
            ),
        ],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "database_path",
                # 기본값은 원본이 아니라 작업 사본. 원본(~/maps/rtab_camera_master.db)
                # 은 읽기 전용으로 두고, 실행할 때마다 여기로 복사해서 쓴다.
                default_value=WORK_DB,
                description=("RTAB-Map database to localize in. Defaults to a "
                             "throwaway copy of ~/maps/rtab_camera_master.db."),
            ),
            DeclareLaunchArgument(
                "initial_pose",
                default_value="",
                description="Optional x y z roll pitch yaw pose in the saved map.",
            ),
            DeclareLaunchArgument(
                "camera_degree",
                default_value="0.16",
                description="Camera pitch in radians.",
            ),
            DeclareLaunchArgument(
                "rtabmap_viz",
                default_value="false",
                description="Start the RTAB-Map GUI in addition to RViz.",
            ),
            DeclareLaunchArgument(
                "rviz",
                default_value="true",
                description="Start RViz with Nav2 controls.",
            ),
            DeclareLaunchArgument(
                "nav_map",
                default_value="",
                description=("Optional hand-edited map yaml used ONLY by the "
                             "Nav2 global costmap (planner). Empty = use "
                             "rtabmap's /map as before."),
            ),
            OpaqueFunction(function=prepare_database),
            robot_bringup,
            TimerAction(period=5.0, actions=[rtabmap]),
            # RTAB-Map should publish the saved occupancy map before Nav2 activates.
            TimerAction(period=10.0, actions=[nav_map_server, nav_map_lifecycle,
                                              nav2, rviz_node]),
        ]
    )
