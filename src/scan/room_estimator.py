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

        鏡像法の壁反射では、距離は「計測点から壁までの距離×2」ではなく
        「計測点→壁鏡像ルーター」の距離として現れる。

        計測点の既知の配置(壁から1m)を利用して、
        最寄り壁反射を幾何学的に識別する。
        """
        distances = {}

        # 2バンドのパスを統合
        all_paths = self._merge_paths(paths_24, paths_5)

        if len(all_paths) < 2:
            return self._default_distances(point_id)

        # 直接波を特定 (最短距離のパス)
        direct_path = all_paths[0] if all_paths else None
        if direct_path is None:
            return self._default_distances(point_id)

        direct_dist = direct_path.distance

        # 壁反射パスの候補: 直接波より遠い全パス
        reflection_paths = [p for p in all_paths if p.distance > direct_dist + 0.3]

        if not reflection_paths:
            return self._default_distances(point_id)

        # --- 計測点の配置に基づく壁距離の推定 ---
        # 近距離反射 = 最寄り壁、遠距離反射 = 反対壁
        near_wall_candidates = [p for p in reflection_paths if p.distance < direct_dist + 4.0]
        far_wall_candidates = [p for p in reflection_paths if p.distance >= direct_dist + 4.0]

        if point_id == 'north':
            if near_wall_candidates:
                distances['north_wall'] = max(0.5, self._mirror_to_wall_dist(
                    near_wall_candidates[0].distance, direct_dist))
            if far_wall_candidates:
                distances['south_wall'] = self._mirror_to_wall_dist(
                    far_wall_candidates[0].distance, direct_dist)
        elif point_id == 'south':
            if near_wall_candidates:
                distances['south_wall'] = max(0.5, self._mirror_to_wall_dist(
                    near_wall_candidates[0].distance, direct_dist))
            if far_wall_candidates:
                distances['north_wall'] = self._mirror_to_wall_dist(
                    far_wall_candidates[0].distance, direct_dist)
        elif point_id == 'east':
            if near_wall_candidates:
                distances['east_wall'] = max(0.5, self._mirror_to_wall_dist(
                    near_wall_candidates[0].distance, direct_dist))
            if far_wall_candidates:
                distances['west_wall'] = self._mirror_to_wall_dist(
                    far_wall_candidates[0].distance, direct_dist)
        elif point_id == 'west':
            if near_wall_candidates:
                distances['west_wall'] = max(0.5, self._mirror_to_wall_dist(
                    near_wall_candidates[0].distance, direct_dist))
            if far_wall_candidates:
                distances['east_wall'] = self._mirror_to_wall_dist(
                    far_wall_candidates[0].distance, direct_dist)
        elif point_id == 'center':
            sorted_refs = sorted(reflection_paths, key=lambda p: p.distance)
            walls = ['north_wall', 'south_wall', 'east_wall', 'west_wall']
            for i, wall in enumerate(walls):
                if i < len(sorted_refs):
                    distances[wall] = self._mirror_to_wall_dist(
                        sorted_refs[i].distance, direct_dist)

        # 天井距離: 壁に割り当てた距離を除外した残りから推定
        assigned_dists = set(round(d, 1) for d in distances.values())
        ceil_candidates = [
            p.distance for p in reflection_paths
            if round(self._mirror_to_wall_dist(p.distance, direct_dist), 1) not in assigned_dists
        ]
        if ceil_candidates:
            ceil_dist = self._mirror_to_wall_dist(min(ceil_candidates), direct_dist)
            if ceil_dist > 0.5:
                distances['ceiling'] = ceil_dist

        return distances

    def _mirror_to_wall_dist(self, reflection_dist: float, direct_dist: float) -> float:
        """
        鏡像反射距離から壁までの片道距離を推定

        鏡像法: reflection_dist ≈ sqrt(direct_dist² + (2*wall_dist)²)
        → wall_dist ≈ sqrt(reflection_dist² - direct_dist²) / 2
        """
        diff_sq = reflection_dist ** 2 - direct_dist ** 2
        if diff_sq <= 0:
            return 0.5
        return np.sqrt(diff_sq) / 2.0

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
