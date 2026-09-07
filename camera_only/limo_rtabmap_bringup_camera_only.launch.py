"""Bring up the LIMO base, state estimation and RGB-D camera (no LiDAR).

Camera-only variant per RTABMap_LIMO_Manual section 5:
the ydlidar driver is removed so RTAB-Map must rely on vision alone.
EKF odometry (/odometry/filtered) and /imu are kept as-is.
"""

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.descriptions import ParameterFile
from launch_ros.substitutions import FindPackageShare


def launch_file(package_name, filename, launch_arguments=None):
    # A scope prevents generic child arguments such as "log_level" from
    # leaking into the next included launch file.
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


def generate_launch_description():
    camera_degree = LaunchConfiguration("camera_degree")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "camera_degree",
                default_value="0.0",
                description="Camera pitch in radians.",
            ),
            launch_file("limo_description", "load_urdf.launch.py"),
            launch_file(
                "wego",
                "camera_tilt_launch.py",
                {"degree": camera_degree},
            ),
            launch_file(
                "limo_base",
                "limo_base.launch.py",
                {
                    "port_name": "ttylimo",
                    "odom_frame": "odom",
                    "base_frame": "base_link",
                    "odom_topic_name": "odom",
                    # robot_localization owns odom -> base_link.
                    "pub_odom_tf": "false",
                },
            ),
            launch_file(
                "orbbec_camera",
                "astra_stereo_u3.launch.py",
                {
                    "depth_registration": "true",
                    # Internal camera transforms are static, so publish them once.
                    "tf_publish_rate": "0.0",
                    # RTAB-Map consumes images directly; these clouds waste CPU/GPU.
                    "enable_point_cloud": "false",
                    "enable_colored_point_cloud": "false",
                    "enable_ir": "false",
                },
            ),
            Node(
                package="robot_localization",
                executable="ekf_node",
                name="ekf_filter_node_odom",
                output="screen",
                parameters=[
                    ParameterFile(
                        PathJoinSubstitution(
                            [
                                FindPackageShare("robot_localization"),
                                "params",
                                "limo_ekf.yaml",
                            ]
                        ),
                        allow_substs=True,
                    ),
                    {
                        # Differential and relative cannot both be enabled.
                        "odom0_relative": False,
                        # 20 Hz is sufficient for LIMO and leaves CPU for SLAM/Nav2.
                        "frequency": 20.0,
                    },
                ],
            ),
        ]
    )
