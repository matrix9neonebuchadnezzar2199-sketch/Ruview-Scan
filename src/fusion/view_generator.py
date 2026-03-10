"""
RuView Scan - 6面ビューデータ生成
"""

import logging
import numpy as np
from typing import Dict

from src.scan.reflection_map import ReflectionMap
from src.utils.geo_utils import RoomDimensions

logger = logging.getLogger(__name__)


class ViewGenerator:
    """統合空間モデルから6面ビューデータを生成"""

    def __init__(self, room: RoomDimensions):
        self.room = room

    def generate_views(self, volume: np.ndarray,
                       resolution: float = 0.05) -> Dict[str, ReflectionMap]:
        """3Dボリュームから6面の2Dスライスを生成"""
        nx, ny, nz = volume.shape
        maps = {}

        # 床面: z=0 のスライス
        floor_grid = volume[:, :, 0] if nz > 0 else np.zeros((nx, ny))
        maps['floor'] = ReflectionMap(
            face='floor', width_m=self.room.width, height_m=self.room.depth,
            grid=floor_grid, resolution=resolution, band='mix',
        )

        # 天井: z=max のスライス
        ceil_grid = volume[:, :, -1] if nz > 1 else floor_grid
        maps['ceiling'] = ReflectionMap(
            face='ceiling', width_m=self.room.width, height_m=self.room.depth,
            grid=ceil_grid, resolution=resolution, band='mix',
        )

        # 北壁: y=0 のスライス
        north_grid = volume[:, 0, :] if ny > 0 else np.zeros((nx, nz))
        maps['north'] = ReflectionMap(
            face='north', width_m=self.room.width, height_m=self.room.height,
            grid=north_grid, resolution=resolution, band='mix',
        )

        # 南壁: y=max のスライス
        south_grid = volume[:, -1, :] if ny > 1 else north_grid
        maps['south'] = ReflectionMap(
            face='south', width_m=self.room.width, height_m=self.room.height,
            grid=south_grid, resolution=resolution, band='mix',
        )

        # 東壁: x=max のスライス
        east_grid = volume[-1, :, :] if nx > 1 else np.zeros((ny, nz))
        maps['east'] = ReflectionMap(
            face='east', width_m=self.room.depth, height_m=self.room.height,
            grid=east_grid, resolution=resolution, band='mix',
        )

        # 西壁: x=0 のスライス
        west_grid = volume[0, :, :] if nx > 0 else east_grid
        maps['west'] = ReflectionMap(
            face='west', width_m=self.room.depth, height_m=self.room.height,
            grid=west_grid, resolution=resolution, band='mix',
        )

        return maps
