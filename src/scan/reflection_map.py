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
from src.utils.geo_utils import RoomDimensions, get_measurement_position, project_to_wall

logger = logging.getLogger(__name__)


@dataclass
class ReflectionMap:
    """1面の反射強度マップ"""
    face: str               # 'floor', 'ceiling', 'north', ...
    width_m: float
    height_m: float
    grid: np.ndarray        # shape: (H_cells, W_cells), 0.0~1.0
    resolution: float       # m/cell
    band: str               # '24', '5', 'mix'


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
        # 各面のグリッドサイズを計算
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
            # 各計測点からの反射を累積
            for point_id, capture in session.captures.items():
                position = get_measurement_position(point_id, self.room)

                # ToF推定でマルチパスを分離
                # 2.4GHz と 5GHz を別々に推定 (サブキャリア数が異なるため混合不可)
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

                # 各パスの反射点をグリッドに投影
                for path in paths:
                    if path.path_type == 'direct':
                        continue

                    # 簡易的な角度推定 (実際はAoAと組み合わせ)
                    angles = self._estimate_angles(point_id, face)
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

    def _estimate_angles(self, point_id: str, target_face: str):
        """
        計測点から対象面への推定角度セット

        TODO (Phase B): 現在は固定値の角度リストを使用している。
        AoAEstimator の結果を generate() に渡し、実測角度を使用するよう
        変更すべき。2×2 MIMOの制約で角度分解能は限定的だが、
        固定値よりは有意に改善する。
        """
        # 簡易版: 主方向と斜め方向のサンプリング
        base_angles = {
            ('north', 'north'): [(np.pi, 0)],
            ('north', 'south'): [(0, 0)],
            ('north', 'east'): [(np.pi/2, 0)],
            ('north', 'west'): [(-np.pi/2, 0)],
            ('south', 'north'): [(np.pi, 0)],
            ('south', 'south'): [(0, 0)],
            ('east', 'east'): [(np.pi/2, 0)],
            ('east', 'west'): [(-np.pi/2, 0)],
            ('west', 'east'): [(np.pi/2, 0)],
            ('west', 'west'): [(-np.pi/2, 0)],
            ('center', 'north'): [(np.pi, 0)],
            ('center', 'south'): [(0, 0)],
            ('center', 'east'): [(np.pi/2, 0)],
            ('center', 'west'): [(-np.pi/2, 0)],
        }

        # 天井/床への角度
        if target_face == 'ceiling':
            return [(0, np.pi/4), (np.pi/2, np.pi/4), (np.pi, np.pi/4), (-np.pi/2, np.pi/4)]
        if target_face == 'floor':
            return [(0, -np.pi/4), (np.pi/2, -np.pi/4)]

        key = (point_id, target_face)
        angles = base_angles.get(key, [(0, 0)])

        # 散乱を追加
        scattered = []
        for ah, av in angles:
            scattered.append((ah, av))
            for delta in [-0.3, -0.15, 0.15, 0.3]:
                scattered.append((ah + delta, av))
                scattered.append((ah, av + delta * 0.5))

        return scattered
