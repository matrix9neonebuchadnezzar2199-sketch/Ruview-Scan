"""
RuView Scan - 部屋寸法推定
=========================
5点のToF/AoA結果から壁距離→幅・奥行・天井高を推定
"""

import logging
from typing import Dict, List, Optional

import numpy as np

from src.csi.models import ScanSession
from src.scan.tof_estimator import ToFEstimator, PathEstimate
from src.scan.aoa_estimator import AoAEstimator
from src.utils.geo_utils import RoomDimensions, estimate_room_dimensions
from src.errors import RoomEstimationError, InsufficientDataError

logger = logging.getLogger(__name__)


class RoomEstimator:
    """5箇所のCSIデータから部屋寸法を推定"""

    def __init__(self, tof_estimator: ToFEstimator, aoa_estimator: AoAEstimator):
        self.tof_estimator = tof_estimator
        self.aoa_estimator = aoa_estimator

    def estimate(self, session: ScanSession) -> RoomDimensions:
        """
        全5箇所のデータから部屋寸法を推定

        Parameters:
            session: スキャンセッション (5箇所分)
        Returns:
            RoomDimensions: 推定された部屋寸法
        """
        if not session.is_complete:
            completed = len(session.completed_points)
            raise InsufficientDataError(required=5, actual=completed)

        wall_distances = {}

        for point_id, capture in session.captures.items():
            logger.info(f"[{point_id}] ToF推定開始...")

            # 2.4GHz と 5GHz 両方のToFを推定
            paths_24 = self.tof_estimator.estimate_tof(capture.frames_24ghz)
            paths_5 = self.tof_estimator.estimate_tof(capture.frames_5ghz)

            # 壁距離の推定
            distances = self._extract_wall_distances(
                point_id, paths_24, paths_5
            )
            wall_distances[point_id] = distances

            logger.info(
                f"[{point_id}] 壁距離推定: "
                + ", ".join(f"{k}={v:.2f}m" for k, v in distances.items())
            )

        # 5点を統合して部屋寸法を推定
        room = estimate_room_dimensions(wall_distances)

        logger.info(
            f"部屋寸法推定結果: "
            f"幅={room.width}m, 奥行={room.depth}m, "
            f"天井高={room.height}m, 面積={room.area}m²"
        )

        return room

    def _extract_wall_distances(
        self,
        point_id: str,
        paths_24: List[PathEstimate],
        paths_5: List[PathEstimate]
    ) -> Dict[str, float]:
        """
        ToF結果から各壁までの距離を推定

        直接波の次に来る反射波を壁反射と仮定する。
        計測点の位置から、どの壁の反射かを推定。
        """
        distances = {}

        # 2.4GHz + 5GHz のパスを統合 (5GHzの分解能を優先、2.4GHzで補完)
        all_paths = self._merge_paths(paths_24, paths_5)

        if len(all_paths) < 2:
            # パスが少ない場合はデフォルト値
            return self._default_distances(point_id)

        # 直接波を除いた反射パスを壁反射として割り当て
        wall_paths = [p for p in all_paths if p.path_type != 'direct']

        # 計測点から壁への距離をマッピング
        if point_id == 'north':
            # 北壁から1m → 北壁への反射は近い、南壁への反射は遠い
            if len(wall_paths) >= 1:
                distances['north_wall'] = max(0.5, wall_paths[0].distance)
            if len(wall_paths) >= 2:
                distances['south_wall'] = wall_paths[1].distance
        elif point_id == 'south':
            if len(wall_paths) >= 1:
                distances['south_wall'] = max(0.5, wall_paths[0].distance)
            if len(wall_paths) >= 2:
                distances['north_wall'] = wall_paths[1].distance
        elif point_id == 'east':
            if len(wall_paths) >= 1:
                distances['east_wall'] = max(0.5, wall_paths[0].distance)
            if len(wall_paths) >= 2:
                distances['west_wall'] = wall_paths[1].distance
        elif point_id == 'west':
            if len(wall_paths) >= 1:
                distances['west_wall'] = max(0.5, wall_paths[0].distance)
            if len(wall_paths) >= 2:
                distances['east_wall'] = wall_paths[1].distance
        elif point_id == 'center':
            # 中心からは4方向ほぼ等距離
            for i, wall in enumerate(['north_wall', 'south_wall', 'east_wall', 'west_wall']):
                if i < len(wall_paths):
                    distances[wall] = wall_paths[i].distance

        # 天井距離の推定 (全計測点共通)
        if len(wall_paths) >= 3:
            # 天井高は通常 2.0~4.0m なのでフィルタリング
            ceil_candidate = wall_paths[-1].distance
            if ceil_candidate > 5.0:
                # マルチバウンスの可能性 → デフォルト値
                distances['ceiling'] = 2.0
            else:
                distances['ceiling'] = max(1.5, ceil_candidate)

        return distances

    def _merge_paths(
        self,
        paths_24: List[PathEstimate],
        paths_5: List[PathEstimate]
    ) -> List[PathEstimate]:
        """2バンドのパス推定結果を統合"""
        all_paths = []
        used_5 = set()

        # 5GHzを優先
        for p5 in paths_5:
            all_paths.append(p5)
            used_5.add(round(p5.distance, 1))

        # 2.4GHzのうち、5GHzで未検出のパスを追加
        for p24 in paths_24:
            d_rounded = round(p24.distance, 1)
            if d_rounded not in used_5:
                all_paths.append(p24)

        return sorted(all_paths, key=lambda p: p.distance)

    def _default_distances(self, point_id: str) -> Dict[str, float]:
        """デフォルト壁距離 (パスが不足時のフォールバック)"""
        return {
            'north_wall': 1.0 if point_id == 'north' else 3.0,
            'south_wall': 1.0 if point_id == 'south' else 3.0,
            'east_wall': 1.0 if point_id == 'east' else 2.5,
            'west_wall': 1.0 if point_id == 'west' else 2.5,
            'ceiling': 2.0,
        }
