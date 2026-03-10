"""
RuView Scan - 5箇所のデータ→統合空間モデル
"""

import logging
import numpy as np
from typing import Dict, List

from src.csi.models import ScanSession
from src.utils.geo_utils import RoomDimensions

logger = logging.getLogger(__name__)


class SpatialIntegrator:
    """5箇所の計測データを統合空間モデルに変換"""

    def __init__(self, room: RoomDimensions, grid_resolution: float = 0.05):
        self.room = room
        self.resolution = grid_resolution

    def integrate(self, per_point_grids: Dict[str, np.ndarray]) -> np.ndarray:
        """
        各計測点のグリッドデータを空間的に統合

        Parameters:
            per_point_grids: {point_id: 3D grid array}
        Returns:
            integrated: 統合3Dグリッド
        """
        nx = max(1, int(self.room.width / self.resolution))
        ny = max(1, int(self.room.depth / self.resolution))
        nz = max(1, int(self.room.height / self.resolution))

        volume = np.zeros((nx, ny, nz))
        weight = np.zeros((nx, ny, nz))

        for point_id, grid in per_point_grids.items():
            # 重み: 各計測点からの距離で重み付け
            volume += grid[:nx, :ny, :nz] if grid.shape[0] >= nx else np.pad(
                grid, [(0, max(0, nx - grid.shape[0])),
                       (0, max(0, ny - grid.shape[1])),
                       (0, max(0, nz - grid.shape[2]))]
            )[:nx, :ny, :nz]
            weight += 1

        # 平均化
        weight = np.maximum(weight, 1)
        integrated = volume / weight

        return integrated
