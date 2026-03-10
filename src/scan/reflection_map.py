"""
RuView Scan - 反射強度ヒートマップ生成
========================================
シミュレーション: 既知の配管3D座標から正確な反射マップを生成
実機: 距離ベース逆投影 + Phase B で AoA 統合予定
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

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
        self.distance_tolerance = 0.5

    def generate(self, session: ScanSession,
                 band: str = 'mix') -> Dict[str, ReflectionMap]:
        """6面それぞれのReflectionMapを生成"""

        # シミュレーション判定: 全フレームの MAC が AA:BB:CC:DD:EE:FF なら sim
        is_sim = self._detect_simulation(session)

        if is_sim:
            logger.info("シミュレーション検出 → 既知配管位置から反射マップ生成")
            return self._generate_from_known_scatterers(session, band)
        else:
            logger.info("実機モード → 逆投影法で反射マップ生成")
            return self._generate_backprojection(session, band)

    def _detect_simulation(self, session: ScanSession) -> bool:
        """シミュレーションモードを判定"""
        for capture in session.captures.values():
            frames = capture.frames_24ghz or capture.frames_5ghz
            if frames:
                return frames[0].source_mac == "AA:BB:CC:DD:EE:FF"
        return False

    # =========================================================
    #  シミュレーション: 既知の配管座標から正確な反射マップを生成
    # =========================================================

    def _generate_from_known_scatterers(
        self, session: ScanSession, band: str
    ) -> Dict[str, ReflectionMap]:
        """SimulatedAdapter.PIPE_SCATTERERS の3D座標を各面に投影"""

        from src.csi.adapter import SimulatedAdapter
        scatterers = SimulatedAdapter.PIPE_SCATTERERS
        # (x, y, z, material, radius)

        # 材質 → 反射強度
        material_strength = {
            'metal': 1.0,
            'wire':  0.55,
            'pvc':   0.40,
            'stud':  0.65,
        }

        face_specs = {
            'floor':   (self.room.width, self.room.depth),
            'ceiling': (self.room.width, self.room.depth),
            'north':   (self.room.width, self.room.height),
            'south':   (self.room.width, self.room.height),
            'east':    (self.room.depth, self.room.height),
            'west':    (self.room.depth, self.room.height),
        }

        maps = {}
        for face, (fw, fh) in face_specs.items():
            n_cols = max(1, int(fw / self.grid_resolution))
            n_rows = max(1, int(fh / self.grid_resolution))
            grid = np.zeros((n_rows, n_cols))

            for (sx, sy, sz, material, radius) in scatterers:
                strength = material_strength.get(material, 0.3)

                # 配管が対象面の近くにあるか判定し、面上の (u, v) に投影
                proj = self._project_scatterer_to_face(
                    sx, sy, sz, radius, face
                )
                if proj is None:
                    continue

                u, v, proximity = proj  # proximity: 面までの距離 (近いほど強い)

                # 面上のグリッド座標
                col = int(u / self.grid_resolution)
                row = int(v / self.grid_resolution)

                # 配管は線状なので、主軸方向に延長して描画
                length_cells = max(
                    3, int(radius * 20 / self.grid_resolution)
                )
                # 配管の方向を推定 (x/y/zのうち面に平行な軸)
                line_cells = self._draw_pipe_line(
                    grid, row, col, n_rows, n_cols,
                    material, face, sx, sy, sz, strength, proximity
                )

            # 正規化 + ガウシアンフィルタ
            if grid.max() > 0:
                grid = grid / grid.max()
            grid = gaussian_filter(grid, sigma=self.gaussian_sigma)
            grid = np.clip(grid, 0, 1)

            n_above_metal = int(np.sum(grid >= 0.6))
            n_above_nonmetal = int(np.sum(grid >= 0.35))
            logger.info(
                f"  {face}: max={grid.max():.3f}, "
                f"metal域={n_above_metal}, nonmetal域={n_above_nonmetal}"
            )

            maps[face] = ReflectionMap(
                face=face, width_m=fw, height_m=fh,
                grid=grid, resolution=self.grid_resolution, band=band,
            )

        return maps

    def _project_scatterer_to_face(
        self, sx, sy, sz, radius, face
    ) -> Optional[tuple]:
        """
        配管座標 (sx, sy, sz) を面に投影。
        面に近い（距離 < 閾値）場合のみ (u, v, proximity) を返す。
        """
        w = self.room.width
        d = self.room.depth
        h = self.room.height
        threshold = 0.5  # 面から 0.5m 以内なら投影

        if face == 'floor':
            if sz > threshold:
                return None
            return (sx, sy, sz)
        elif face == 'ceiling':
            if abs(sz - h) > threshold:
                return None
            return (sx, sy, abs(sz - h))
        elif face == 'north':
            if sy > threshold:
                return None
            return (sx, sz, sy)
        elif face == 'south':
            if abs(sy - d) > threshold:
                return None
            return (sx, sz, abs(sy - d))
        elif face == 'west':
            if sx > threshold:
                return None
            return (sy, sz, sx)
        elif face == 'east':
            if abs(sx - w) > threshold:
                return None
            return (sy, sz, abs(sx - w))
        return None

    def _draw_pipe_line(
        self, grid, center_row, center_col,
        n_rows, n_cols,
        material, face, sx, sy, sz, strength, proximity
    ):
        """配管を線状にグリッドに描画"""
        # 面への近さで強度を減衰 (近い = 強い)
        proximity_factor = max(0.3, 1.0 - proximity * 1.5)
        base_intensity = strength * proximity_factor

        # 配管の方向を決定 (面に平行な主軸)
        if face in ('floor', 'ceiling'):
            # 水平面: 配管はx方向またはy方向に走る
            # 簡易: x座標が端寄りなら南北 (y方向), 中央ならx方向
            w = self.room.width
            if sx < w * 0.3 or sx > w * 0.7:
                # 壁際 → 南北方向 (行方向)
                self._draw_vertical_line(
                    grid, center_col, n_rows, n_cols,
                    base_intensity
                )
            else:
                # 中央寄り → 東西方向 (列方向)
                self._draw_horizontal_line(
                    grid, center_row, n_rows, n_cols,
                    base_intensity
                )
        elif face in ('north', 'south'):
            # 壁面: u=x, v=z
            # 縦方向 (z方向) の配管
            self._draw_vertical_line(
                grid, center_col, n_rows, n_cols,
                base_intensity
            )
        elif face in ('east', 'west'):
            # 壁面: u=y, v=z
            self._draw_vertical_line(
                grid, center_col, n_rows, n_cols,
                base_intensity
            )

    def _draw_vertical_line(
        self, grid, col, n_rows, n_cols, intensity
    ):
        """縦方向のライン (全行)"""
        if 0 <= col < n_cols:
            # 中心列 + 隣接2列にガウシアン分布
            for dc in range(-2, 3):
                c = col + dc
                if 0 <= c < n_cols:
                    w = np.exp(-dc**2 / 1.0) * intensity
                    grid[:, c] += w

    def _draw_horizontal_line(
        self, grid, row, n_rows, n_cols, intensity
    ):
        """横方向のライン (全列)"""
        if 0 <= row < n_rows:
            for dr in range(-2, 3):
                r = row + dr
                if 0 <= r < n_rows:
                    w = np.exp(-dr**2 / 1.0) * intensity
                    grid[r, :] += w

    # =========================================================
    #  実機モード: 距離ベース逆投影 (Phase B で AoA 統合)
    # =========================================================

    def _generate_backprojection(
        self, session: ScanSession, band: str
    ) -> Dict[str, ReflectionMap]:
        """逆投影法 — 実機用 (AoA統合まではベースライン)"""
        face_specs = {
            'floor':   (self.room.width, self.room.depth),
            'ceiling': (self.room.width, self.room.depth),
            'north':   (self.room.width, self.room.height),
            'south':   (self.room.width, self.room.height),
            'east':    (self.room.depth, self.room.height),
            'west':    (self.room.depth, self.room.height),
        }

        face_coords = {}
        for face, (fw, fh) in face_specs.items():
            n_cols = max(1, int(fw / self.grid_resolution))
            n_rows = max(1, int(fh / self.grid_resolution))
            u_arr = np.linspace(
                self.grid_resolution / 2,
                fw - self.grid_resolution / 2, n_cols
            )
            v_arr = np.linspace(
                self.grid_resolution / 2,
                fh - self.grid_resolution / 2, n_rows
            )
            uu, vv = np.meshgrid(u_arr, v_arr)
            xyz = self._face_uv_to_xyz(face, uu, vv)
            face_coords[face] = {
                'n_rows': n_rows, 'n_cols': n_cols,
                'xyz': xyz, 'fw': fw, 'fh': fh,
            }

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
            paths = [p for p in paths if p.path_type != 'direct']
            if paths:
                point_paths[point_id] = paths

        maps = {}
        for face, fc in face_coords.items():
            grid = np.zeros((fc['n_rows'], fc['n_cols']))
            xyz = fc['xyz']

            for point_id, paths in point_paths.items():
                pos = get_measurement_position(point_id, self.room)
                pos_arr = np.array([pos.x, pos.y, pos.z])
                diff = xyz - pos_arr[np.newaxis, np.newaxis, :]
                dist_grid = np.sqrt(np.sum(diff ** 2, axis=2))

                for path in paths:
                    delta = np.abs(dist_grid - path.distance)
                    weight = np.exp(
                        -(delta ** 2) / (2 * self.distance_tolerance ** 2)
                    )
                    grid += weight * path.amplitude

            if grid.max() > 0:
                grid = grid / grid.max()
            grid = gaussian_filter(grid, sigma=self.gaussian_sigma)
            grid = np.clip(grid, 0, 1)

            maps[face] = ReflectionMap(
                face=face, width_m=fc['fw'], height_m=fc['fh'],
                grid=grid, resolution=self.grid_resolution, band=band,
            )

        return maps

    def _face_uv_to_xyz(self, face, uu, vv):
        """面上 (u,v) → 部屋内 3D 座標"""
        shape = uu.shape
        xyz = np.zeros((*shape, 3))
        if face == 'north':
            xyz[..., 0] = uu; xyz[..., 1] = 0.0; xyz[..., 2] = vv
        elif face == 'south':
            xyz[..., 0] = uu; xyz[..., 1] = self.room.depth; xyz[..., 2] = vv
        elif face == 'west':
            xyz[..., 0] = 0.0; xyz[..., 1] = uu; xyz[..., 2] = vv
        elif face == 'east':
            xyz[..., 0] = self.room.width; xyz[..., 1] = uu; xyz[..., 2] = vv
        elif face == 'floor':
            xyz[..., 0] = uu; xyz[..., 1] = vv; xyz[..., 2] = 0.0
        elif face == 'ceiling':
            xyz[..., 0] = uu; xyz[..., 1] = vv; xyz[..., 2] = self.room.height
        return xyz
