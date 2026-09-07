"""Map with LIMO wheel/IMU odometry and RGB-D only (no LiDAR).

Camera-only variant per RTABMap_LIMO_Manual section 5:
- Reg/Strategy 0  : visual registration (feature matching), not ICP
- Grid/Sensor 1   : build the occupancy grid from the depth camera
- Grid/3D true    : 3-D grid so the ground can be segmented by normals
- subscribe_scan false and no /scan input
"""

import os

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
    LogInfo,
    TimerAction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


RTABMAP_MAPPING_PARAMETERS = " ".join(
    [
        "--Reg/Strategy 0",
        "--Reg/Force3DoF true",
        "--Kp/MaxFeatures 500",
        "--Vis/MaxFeatures 1000",
        "--RGBD/NeighborLinkRefining false",
        "--Grid/Sensor 1",
        "--Grid/3D true",
        "--Grid/RayTracing false",
        "--Grid/CellSize 0.05",
        "--Grid/DepthDecimation 4",
        "--Grid/RangeMin 0.0",
        "--Grid/RangeMax 5.0",
        "--Grid/NormalsSegmentation true",
        "--Grid/GroundIsObstacle false",
        "--Grid/FlatObstacleDetected true",
        "--Grid/NormalK 20",
        "--Grid/MaxGroundAngle 45",
        "--Grid/MaxGroundHeight 0.1",
        "--Grid/MaxObstacleHeight 1.5",
        "--Optimizer/GravitySigma 0.3",
    ]
)


def include_launch(package_name, filename, launch_arguments=None):
    return GroupAction(
        scoped=True,
        actions=[
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


def rtabmap_arguments(database_path, rtabmap_viz):
    return {
        "localization": "false",
        "database_path": database_path,
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
        "rtabmap_viz": rtabmap_viz,
        "rviz": "false",
        "log_level": "info",
        "rtabmap_args": RTABMAP_MAPPING_PARAMETERS,
    }


def generate_launch_description():
    database_path = LaunchConfiguration("database_path")
    camera_degree = LaunchConfiguration("camera_degree")
    rtabmap_viz = LaunchConfiguration("rtabmap_viz")

    robot_bringup = include_launch(
        "wego",
        "limo_rtabmap_bringup_camera_only.launch.py",
        {"camera_degree": camera_degree},
    )
    rtabmap = include_launch(
        "rtabmap_launch",
        "rtabmap.launch.py",
        rtabmap_arguments(database_path, rtabmap_viz),
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "database_path",
                # Separate DB so camera-only maps never mix with the
                # LiDAR-assisted database of the default launch files.
                default_value=os.path.expanduser("~/.ros/limo_rtabmap_camera.db"),
                description="RTAB-Map database to create or continue.",
            ),
            DeclareLaunchArgument(
                "camera_degree",
                default_value="0.16",
                description="Camera pitch in radians.",
            ),
            DeclareLaunchArgument(
                "rtabmap_viz",
                default_value="true",
                description="Start the RTAB-Map mapping GUI.",
            ),
            LogInfo(
                msg=(
                    "Manual mapping mode: drive with the LIMO radio controller "
                    "(SWB=center/remote control). Do not start another cmd_vel "
                    "publisher."
                )
            ),
            robot_bringup,
            # Give the camera, EKF and static transforms time to appear.
            TimerAction(period=5.0, actions=[rtabmap]),
        ]
    )
