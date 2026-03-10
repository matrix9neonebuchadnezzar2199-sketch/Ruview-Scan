"""
RuView Scan - 2.4GHz + 5GHz データ統合
"""

import logging
import numpy as np

from src.scan.reflection_map import ReflectionMap

logger = logging.getLogger(__name__)


class BandMerger:
    """2.4GHz と 5GHz のデータを重み付け統合"""

    def __init__(self, weight_24: float = 0.4, weight_5: float = 0.6):
        self.weight_24 = weight_24
        self.weight_5 = weight_5

    def merge(self, map_24: ReflectionMap, map_5: ReflectionMap) -> ReflectionMap:
        """2バンドの反射マップを統合"""
        # グリッドサイズを合わせる
        target_rows = max(map_24.grid.shape[0], map_5.grid.shape[0])
        target_cols = max(map_24.grid.shape[1], map_5.grid.shape[1])

        from scipy.ndimage import zoom
        grid_24 = zoom(map_24.grid, (target_rows / map_24.grid.shape[0],
                                      target_cols / map_24.grid.shape[1]))
        grid_5 = zoom(map_5.grid, (target_rows / map_5.grid.shape[0],
                                    target_cols / map_5.grid.shape[1]))

        # 重み付け統合
        mixed = self.weight_24 * grid_24 + self.weight_5 * grid_5
        mixed = np.clip(mixed, 0, 1)

        return ReflectionMap(
            face=map_24.face,
            width_m=map_24.width_m,
            height_m=map_24.height_m,
            grid=mixed,
            resolution=min(map_24.resolution, map_5.resolution),
            band='mix',
        )
