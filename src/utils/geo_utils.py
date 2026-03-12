"""
RuView Scan - 座標変換・三角測量ユーティリティ
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Optional

# 光速 (m/s)
SPEED_OF_LIGHT = 299_792_458.0


def channel_to_freq(channel: int) -> float:
    """
    Wi-Fiチャネル番号から中心周波数(Hz)を返す

    2.4GHz: ch1(2412MHz) ~ ch14(2484MHz)
    5GHz:   ch36(5180MHz) ~ ch64(5320MHz), ch100(5500MHz) ~ ch144(5720MHz),
            ch149(5745MHz) ~ ch165(5825MHz)
    """
    if channel <= 14:
        if channel == 14:
            return 2484e6
        return (2412 + (channel - 1) * 5) * 1e6
    elif channel <= 64:
        return (5180 + (channel - 36) * 5) * 1e6
    elif channel <= 144:
        return (5500 + (channel - 100) * 5) * 1e6
    else:
        return (5745 + (channel - 149) * 5) * 1e6


@dataclass
class RoomDimensions:
    """部屋の寸法"""
    width: float    # 東西幅 (m)
    depth: float    # 南北奥行 (m)
    height: float   # 天井高 (m)

    @property
    def area(self) -> float:
        return self.width * self.depth

    @property
    def volume(self) -> float:
        return self.width * self.depth * self.height


@dataclass
class Point3D:
    """3D座標"""
    x: float
    y: float
    z: float

    def distance_to(self, other: 'Point3D') -> float:
        return np.sqrt(
            (self.x - other.x) ** 2 +
            (self.y - other.y) ** 2 +
            (self.z - other.z) ** 2
        )


# 計測点のデフォルト相対位置 (壁から1mの位置)
MEASUREMENT_OFFSETS = {
    'north': (0.0, 1.0, 0.0),   # 北壁から1m → y=1.0
    'east':  (-1.0, 0.0, 0.0),  # 東壁から1m → x=W-1.0
    'south': (0.0, -1.0, 0.0),  # 南壁から1m → y=D-1.0
    'west':  (1.0, 0.0, 0.0),   # 西壁から1m → x=1.0
    'center': (0.0, 0.0, 0.0),  # 中心
}


def tof_to_distance(tof_sec: float) -> float:
    """
    ToF（飛行時間）から距離を計算

    Parameters:
        tof_sec: 飛行時間 (秒)
    Returns:
        distance: 距離 (m) — 往復を考慮して 2 で割る
    """
    return SPEED_OF_LIGHT * tof_sec / 2.0


def distance_to_tof(distance_m: float) -> float:
    """距離からToFを計算"""
    return 2.0 * distance_m / SPEED_OF_LIGHT


def estimate_room_dimensions(
    wall_distances: dict,
    measurement_height: float = 0.75
) -> RoomDimensions:
    """
    5箇所の壁距離推定値から部屋寸法を推定

    Parameters:
        wall_distances: dict — 各計測点から各壁への推定距離
            {
                'north': {'north_wall': d1, 'south_wall': d2, 'east_wall': d3, 'west_wall': d4, ...},
                'east': {...},
                ...
            }
        measurement_height: 計測点の高さ (m) — ノートPCの位置
    Returns:
        RoomDimensions: 推定された部屋寸法
    """
    # 各計測点からの壁距離を統合して推定
    width_estimates = []
    depth_estimates = []
    height_estimates = []

    for point_id, distances in wall_distances.items():
        if 'east_wall' in distances and 'west_wall' in distances:
            width_estimates.append(distances['east_wall'] + distances['west_wall'])
        if 'north_wall' in distances and 'south_wall' in distances:
            depth_estimates.append(distances['north_wall'] + distances['south_wall'])
        if 'ceiling' in distances:
            height_estimates.append(distances['ceiling'] + measurement_height)
        if 'floor' in distances:
            height_estimates.append(distances['floor'] + measurement_height)

    # 中央値で統合 (外れ値に強い)
    width = float(np.median(width_estimates)) if width_estimates else 5.0
    depth = float(np.median(depth_estimates)) if depth_estimates else 4.0
    height = float(np.median(height_estimates)) if height_estimates else 2.5

    return RoomDimensions(
        width=round(width, 1),
        depth=round(depth, 1),
        height=round(height, 1)
    )


def get_measurement_position(
    point_id: str,
    room: RoomDimensions,
    measurement_height: float = 0.75
) -> Point3D:
    """
    計測点IDから部屋内の絶対座標を計算

    座標系: x=東西(東が+), y=南北(南が+), z=上下(上が+)
    原点: 部屋の北西下角
    """
    if point_id == 'north':
        return Point3D(room.width / 2, 1.0, measurement_height)
    elif point_id == 'east':
        return Point3D(room.width - 1.0, room.depth / 2, measurement_height)
    elif point_id == 'south':
        return Point3D(room.width / 2, room.depth - 1.0, measurement_height)
    elif point_id == 'west':
        return Point3D(1.0, room.depth / 2, measurement_height)
    elif point_id == 'center':
        return Point3D(room.width / 2, room.depth / 2, measurement_height)
    elif point_id == 'northeast':
        return Point3D(room.width - 1.0, 1.0, measurement_height)
    elif point_id == 'southeast':
        return Point3D(room.width - 1.0, room.depth - 1.0, measurement_height)
    elif point_id == 'southwest':
        return Point3D(1.0, room.depth - 1.0, measurement_height)
    elif point_id == 'northwest':
        return Point3D(1.0, 1.0, measurement_height)
    else:
        raise ValueError(f"Unknown point_id: {point_id}")



def project_to_wall(
    point: Point3D,
    distance: float,
    angle_h: float,
    angle_v: float,
    room: RoomDimensions
) -> Tuple[str, float, float]:
    """
    反射点を最寄りの壁面に投影

    Parameters:
        point: 計測点の位置
        distance: 反射点までの距離 (m)
        angle_h: 水平角 (rad) — 0=北, π/2=東
        angle_v: 垂直角 (rad) — 0=水平, π/2=上
    Returns:
        (face, u, v): 壁面名, 壁面上のU座標, V座標
    """
    # 反射点の3D座標を計算
    dx = distance * np.cos(angle_v) * np.sin(angle_h)
    dy = distance * np.cos(angle_v) * np.cos(angle_h)
    dz = distance * np.sin(angle_v)

    rx = point.x + dx
    ry = point.y + dy
    rz = point.z + dz

    # 最寄りの壁面に投影
    wall_distances = {
        'west': abs(rx),
        'east': abs(rx - room.width),
        'north': abs(ry),
        'south': abs(ry - room.depth),
        'floor': abs(rz),
        'ceiling': abs(rz - room.height),
    }

    face = min(wall_distances, key=wall_distances.get)

    # 壁面上の座標 (u, v)
    if face in ('north', 'south'):
        u = np.clip(rx, 0, room.width)
        v = np.clip(rz, 0, room.height)
    elif face in ('east', 'west'):
        u = np.clip(ry, 0, room.depth)
        v = np.clip(rz, 0, room.height)
    elif face == 'floor':
        u = np.clip(rx, 0, room.width)
        v = np.clip(ry, 0, room.depth)
    elif face == 'ceiling':
        u = np.clip(rx, 0, room.width)
        v = np.clip(ry, 0, room.depth)
    else:
        u, v = 0.0, 0.0

    return face, float(u), float(v)
