"""
RuView Scan - 反射強度ヒートマップ生成
========================================
距離ベースの逆投影 (Back-Projection) で反射マップを生成。
AoA不要: 各面のグリッドセルと計測点の距離を計算し、
ToFパスの距離と一致するセルにエネルギーを堆積する。
5測定点から弧が交差する位置に構造物のピークが形成される。
"""

import logging
from dataclasses import dataclass
from typing import Dict, List

import numpy as np
from scipy.ndimage import gaussian_filter

from src.csi.models import ScanSession, CSIFrame
from src.scan.tof_estimator import ToFEstimator, PathEstimate
from src.utils.geo_utils import (
    RoomDimensions, Point3D, get_measurement_position,
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
        # 距離一致判定の許容幅 (m)
        # 80MHz帯域の距離分解能 ≈ c/(2*BW) ≈ 1.87m なので、±0.5m は妥当
        self.distance_tolerance = 0.5

    def generate(self, session: ScanSession,
                 band: str = 'mix') -> Dict[str, ReflectionMap]:
        """6面それぞれのReflectionMapを生成 (逆投影法)"""

        face_specs = {
            'floor':   (self.room.width, self.room.depth),
            'ceiling': (self.room.width, self.room.depth),
            'north':   (self.room.width, self.room.height),
            'south':   (self.room.width, self.room.height),
            'east':    (self.room.depth, self.room.height),
            'west':    (self.room.depth, self.room.height),
        }

        # 各面のグリッド座標 → 3D座標 を事前計算
        face_coords = {}
        for face, (fw, fh) in face_specs.items():
            n_cols = max(1, int(fw / self.grid_resolution))
            n_rows = max(1, int(fh / self.grid_resolution))
            # u軸: 0 ~ fw, v軸: 0 ~ fh
            u_arr = np.linspace(
                self.grid_resolution / 2, fw - self.grid_resolution / 2, n_cols
            )
            v_arr = np.linspace(
                self.grid_resolution / 2, fh - self.grid_resolution / 2, n_rows
            )
            uu, vv = np.meshgrid(u_arr, v_arr)  # (n_rows, n_cols)

            # 面ごとに 3D 座標を構築
            xyz = self._face_uv_to_xyz(face, uu, vv)
            face_coords[face] = {
                'n_rows': n_rows,
                'n_cols': n_cols,
                'xyz': xyz,   # (n_rows, n_cols, 3)
                'fw': fw,
                'fh': fh,
            }

        # 各計測点のToFパスを事前抽出
        point_paths = {}
        for point_id, capture in session.captures.items():
            paths = []
            if band in ('24', 'mix') and capture.frames_24ghz:
                paths.extend(self.tof_estimator.estimate_tof(
                    capture.frames_24ghz[:250]
                ))
            if band in ('5', 'mix') and capture.frames_5ghz:
                paths.extend(self.tof_estimator.estimate_tof(
                    capture.frames_5ghz[:250]
                ))
            # 直接波を除外
            paths = [p for p in paths if p.path_type != 'direct']
            if paths:
                point_paths[point_id] = paths

        logger.info(
            f"反射マップ生成: {len(point_paths)}測定点, "
            f"パス数={sum(len(v) for v in point_paths.values())}"
        )

        # 逆投影: 各面 × 各計測点 × 各パス
        maps = {}
        for face, fc in face_coords.items():
            grid = np.zeros((fc['n_rows'], fc['n_cols']))
            xyz = fc['xyz']  # (rows, cols, 3)

            for point_id, paths in point_paths.items():
                pos = get_measurement_position(point_id, self.room)
                pos_arr = np.array([pos.x, pos.y, pos.z])

                # 計測点から各グリッドセルまでの距離 (rows, cols)
                diff = xyz - pos_arr[np.newaxis, np.newaxis, :]
                dist_grid = np.sqrt(np.sum(diff ** 2, axis=2))

                for path in paths:
                    # 距離一致度: ガウシアン重み
                    # path.distance は片道距離 (ToFは往復/2)
                    delta = np.abs(dist_grid - path.distance)
                    weight = np.exp(
                        -(delta ** 2) / (2 * self.distance_tolerance ** 2)
                    )
                    grid += weight * path.amplitude

            # 正規化 + ガウシアンフィルタ
            if grid.max() > 0:
                grid = grid / grid.max()
            grid = gaussian_filter(grid, sigma=self.gaussian_sigma)
            grid = np.clip(grid, 0, 1)

            n_above = np.sum(grid > 0.35)
            logger.info(
                f"  {face}: grid max={grid.max():.3f}, "
                f"cells>0.35={n_above}, shape={grid.shape}"
            )

            maps[face] = ReflectionMap(
                face=face,
                width_m=fc['fw'],
                height_m=fc['fh'],
                grid=grid,
                resolution=self.grid_resolution,
                band=band,
            )

        return maps

    def _face_uv_to_xyz(self, face: str,
                        uu: np.ndarray, vv: np.ndarray) -> np.ndarray:
        """
        面上の (u, v) グリッド座標を部屋内 3D 座標 (x, y, z) に変換

        座標系: x=東(+), y=南(+), z=上(+), 原点=北西下角

        各面の定義:
          north: y=0  面, u=x(東), v=z(上)
          south: y=D  面, u=x(東), v=z(上)
          west:  x=0  面, u=y(南), v=z(上)
          east:  x=W  面, u=y(南), v=z(上)
          floor: z=0  面, u=x(東), v=y(南)
          ceiling: z=H面, u=x(東), v=y(南)
        """
        shape = uu.shape
        xyz = np.zeros((*shape, 3))

        if face == 'north':
            xyz[..., 0] = uu          # x
            xyz[..., 1] = 0.0         # y = 0
            xyz[..., 2] = vv          # z
        elif face == 'south':
            xyz[..., 0] = uu
            xyz[..., 1] = self.room.depth
            xyz[..., 2] = vv
        elif face == 'west':
            xyz[..., 0] = 0.0
            xyz[..., 1] = uu          # u = y
            xyz[..., 2] = vv
        elif face == 'east':
            xyz[..., 0] = self.room.width
            xyz[..., 1] = uu
            xyz[..., 2] = vv
        elif face == 'floor':
            xyz[..., 0] = uu
            xyz[..., 1] = vv
            xyz[..., 2] = 0.0
        elif face == 'ceiling':
            xyz[..., 0] = uu
            xyz[..., 1] = vv
            xyz[..., 2] = self.room.height

        return xyz
