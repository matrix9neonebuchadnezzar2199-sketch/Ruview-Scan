"""
RuView Scan - 反射強度ヒートマップ生成
"""

import logging
from dataclasses import dataclass
from typing import Dict, List

import numpy as np
from scipy.ndimage import gaussian_filter

from src.csi.models import ScanSession, CSIFrame
from src.scan.tof_estimator import ToFEstimator, PathEstimate
from src.utils.geo_utils import (
    RoomDimensions, Point3D, get_measurement_position, project_to_wall
)

logger = logging.getLogger(__name__)


@dataclass
class ReflectionMap:
    """1面の反射強度マップ"""
    face: str
    width_m: float
    height_m: float
    grid: np.ndarray
    resolution: float
    band: str


class ReflectionMapGenerator:
    """5箇所のCSIデータから反射強度ヒートマップを生成"""

    def __init__(self, room_dims: RoomDimensions,
                 grid_resolution: float = 0.05,
                 gaussian_sigma: float = 2.0):
        self.room = room_dims
        self.grid_resolution = grid_resolution
        self.gaussian_sigma = gaussian_sigma
        self.tof_estimator = ToFEstimator(method='music', n_paths=8)

    def generate(self, session: ScanSession,
                 band: str = 'mix') -> Dict[str, ReflectionMap]:
        """6面それぞれのReflectionMapを生成"""
        face_specs = {
            'floor': (self.room.width, self.room.depth),
            'ceiling': (self.room.width, self.room.depth),
            'north': (self.room.width, self.room.height),
            'south': (self.room.width, self.room.height),
            'east': (self.room.depth, self.room.height),
            'west': (self.room.depth, self.room.height),
        }

        maps = {}
        for face, (w, h) in face_specs.items():
            n_cols = max(1, int(w / self.grid_resolution))
            n_rows = max(1, int(h / self.grid_resolution))
            grid = np.zeros((n_rows, n_cols))

            for point_id, capture in session.captures.items():
                position = get_measurement_position(point_id, self.room)

                # バンド別にToF推定
                paths = []
                if band in ('24', 'mix') and capture.frames_24ghz:
                    paths.extend(self.tof_estimator.estimate_tof(
                        capture.frames_24ghz[:250]
                    ))
                if band in ('5', 'mix') and capture.frames_5ghz:
                    paths.extend(self.tof_estimator.estimate_tof(
                        capture.frames_5ghz[:250]
                    ))

                if not paths:
                    continue

                for path in paths:
                    if path.path_type == 'direct':
                        continue

                    # 全方向に角度を掃引して対象面に当たるものを収集
                    angles = self._sweep_angles(position, path.distance, face)
                    for angle_h, angle_v in angles:
                        face_name, u, v = project_to_wall(
                            position, path.distance, angle_h, angle_v, self.room
                        )
                        if face_name == face:
                            col = int(u / self.grid_resolution)
                            row = int(v / self.grid_resolution)
                            if 0 <= row < n_rows and 0 <= col < n_cols:
                                grid[row, col] += path.amplitude

            # 正規化 + ガウシアンフィルタ
            if grid.max() > 0:
                grid = grid / grid.max()
            grid = gaussian_filter(grid, sigma=self.gaussian_sigma)
            grid = np.clip(grid, 0, 1)

            maps[face] = ReflectionMap(
                face=face,
                width_m=w,
                height_m=h,
                grid=grid,
                resolution=self.grid_resolution,
                band=band,
            )

        return maps

    def _sweep_angles(self, position: Point3D, distance: float,
                      target_face: str) -> list:
        """
        計測点から対象面に向けて角度を掃引し、
        その面に到達し得る角度セットを返す。

        幾何学的に対象面上の格子点への角度を計算するため、
        全ポイント×全面で確実にグリッドへの投影が行われる。
        """
        w = self.room.width
        d = self.room.depth
        h = self.room.height
        px, py, pz = position.x, position.y, position.z

        # 対象面上のサンプルポイントを生成
        targets = []
        n_samples = 8  # 各軸のサンプル数

        if target_face == 'north':    # y=0 面
            for xi in np.linspace(0.1, w - 0.1, n_samples):
                for zi in np.linspace(0.1, h - 0.1, n_samples):
                    targets.append((xi, 0.01, zi))
        elif target_face == 'south':  # y=d 面
            for xi in np.linspace(0.1, w - 0.1, n_samples):
                for zi in np.linspace(0.1, h - 0.1, n_samples):
                    targets.append((xi, d - 0.01, zi))
        elif target_face == 'west':   # x=0 面
            for yi in np.linspace(0.1, d - 0.1, n_samples):
                for zi in np.linspace(0.1, h - 0.1, n_samples):
                    targets.append((0.01, yi, zi))
        elif target_face == 'east':   # x=w 面
            for yi in np.linspace(0.1, d - 0.1, n_samples):
                for zi in np.linspace(0.1, h - 0.1, n_samples):
                    targets.append((w - 0.01, yi, zi))
        elif target_face == 'floor':  # z=0 面
            for xi in np.linspace(0.1, w - 0.1, n_samples):
                for yi in np.linspace(0.1, d - 0.1, n_samples):
                    targets.append((xi, yi, 0.01))
        elif target_face == 'ceiling':  # z=h 面
            for xi in np.linspace(0.1, w - 0.1, n_samples):
                for yi in np.linspace(0.1, d - 0.1, n_samples):
                    targets.append((xi, yi, h - 0.01))

        # 各ターゲットへの角度を計算
        angles = []
        for tx, ty, tz in targets:
            dx = tx - px
            dy = ty - py
            dz = tz - pz
            d_horiz = np.sqrt(dx**2 + dy**2)

            if d_horiz < 0.001:
                angle_h = 0.0
            else:
                angle_h = np.arctan2(dx, dy)  # sin=dx, cos=dy → 0=north

            d_total_target = np.sqrt(dx**2 + dy**2 + dz**2)
            if d_total_target < 0.001:
                angle_v = 0.0
            else:
                angle_v = np.arcsin(np.clip(dz / d_total_target, -1, 1))

            angles.append((angle_h, angle_v))

        return angles
