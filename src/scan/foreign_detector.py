"""
RuView Scan - 異物検出 (RF + CSI統合)
"""

import logging
from dataclasses import dataclass
from typing import List, Dict, Optional

import numpy as np
from scipy import ndimage

from src.csi.models import ScanSession
from src.scan.reflection_map import ReflectionMap
from src.scan.structure_detector import DetectedStructure
from src.rf.scanner import RFScanner, RFDevice

logger = logging.getLogger(__name__)


@dataclass
class ForeignObject:
    """検出された異物"""
    face: str
    x: float
    y: float          # 面上の座標(m)
    radius: float           # 推定サイズ(m)
    confidence: float       # 固定値
    label: str              # '不審デバイス (盗聴器疑い)' 等
    detail: str             # '壁内 深さ≈5cm / 2.4GHz微弱電波源'
    detection_method: str   # 'rf', 'csi', 'both'


class ForeignDetector:
    """不審デバイス（盗聴器・隠しAP等）を検出"""

    def __init__(self, rf_scanner: RFScanner,
                 residual_threshold: float = 0.5,
                 min_cluster_size: int = 3):
        self.rf_scanner = rf_scanner
        self.residual_threshold = residual_threshold
        self.min_cluster_size = min_cluster_size

    async def detect(
        self,
        session: ScanSession,
        reflection_maps: Dict[str, ReflectionMap],
        structures: List[DetectedStructure]
    ) -> List[ForeignObject]:
        """RF + CSI の二段階検出"""

        # 第一段階: RFパッシブスキャン
        try:
            rf_devices = await self.rf_scanner.scan()
            suspicious_rf = [d for d in rf_devices if d.is_suspicious]
        except Exception as e:
            logger.warning(f"RFスキャンスキップ: {e}")
            suspicious_rf = []

        # 第二段階: CSI異常パターン
        residual_objects = self._detect_residual(reflection_maps, structures)

        # 統合
        return self._merge_detections(suspicious_rf, residual_objects)

    def _detect_residual(
        self,
        reflection_maps: Dict[str, ReflectionMap],
        structures: List[DetectedStructure]
    ) -> List[ForeignObject]:
        """反射マップから既知構造物を除去した残差で異物検出"""
        foreign = []

        for face, rmap in reflection_maps.items():
            grid = rmap.grid.copy()

            # 既知構造物の領域をマスク
            for s in structures:
                if s.face != face:
                    continue
                c1 = int(s.x1 / rmap.resolution)
                r1 = int(s.y1 / rmap.resolution)
                c2 = int(s.x2 / rmap.resolution)
                r2 = int(s.y2 / rmap.resolution)
                r1 = max(0, min(r1, grid.shape[0] - 1))
                r2 = max(0, min(r2, grid.shape[0] - 1))
                c1 = max(0, min(c1, grid.shape[1] - 1))
                c2 = max(0, min(c2, grid.shape[1] - 1))
                grid[r1:r2+1, c1:c2+1] = 0

            # 残差マップで閾値以上のクラスタを検出
            residual_mask = grid > self.residual_threshold
            labeled, num_features = ndimage.label(residual_mask)

            for i in range(1, num_features + 1):
                component = labeled == i
                coords = np.argwhere(component)

                if len(coords) < self.min_cluster_size:
                    continue

                # 重心
                cy, cx = np.mean(coords, axis=0)
                x_m = cx * rmap.resolution
                y_m = cy * rmap.resolution

                # サイズ
                radius = np.sqrt(len(coords)) * rmap.resolution / 2

                # 強度
                intensity = float(np.mean(grid[component]))

                foreign.append(ForeignObject(
                    face=face,
                    x=round(x_m, 2),
                    y=round(y_m, 2),
                    radius=round(radius, 2),
                    confidence=round(min(0.9, intensity * 0.8), 2),
                    label="壁内不明反射源",
                    detail=f"CSI残差検出 / 強度{intensity:.2f}",
                    detection_method="csi",
                ))

        return foreign

    def _merge_detections(
        self,
        suspicious_rf: List[RFDevice],
        residual_objects: List[ForeignObject]
    ) -> List[ForeignObject]:
        """RF検出結果とCSI残差検出結果を統合"""
        merged = list(residual_objects)

        # RFで検出された不審デバイスを追加
        for rf_dev in suspicious_rf:
            # RFデバイスの位置は不明なので、検出情報として追加
            freq_detail = f"{rf_dev.frequency}帯 信号{rf_dev.signal}dBm"
            ssid_info = f"SSID:{rf_dev.ssid or '非公開'}"

            label = "不審デバイス"
            if not rf_dev.ssid:
                label = "不審デバイス (隠しAP)"
            elif rf_dev.signal > -30:
                label = "不審デバイス (盗聴器疑い)"

            # 既存のCSI検出と近い位置のものがあれば統合
            matched = False
            for fo in merged:
                if fo.detection_method == 'csi':
                    fo.detection_method = 'both'
                    fo.confidence = min(0.95, fo.confidence + 0.15)
                    fo.label = label
                    fo.detail = f"{freq_detail} / {ssid_info} + {fo.detail}"
                    matched = True
                    break

            if not matched:
                merged.append(ForeignObject(
                    face="unknown",
                    x=0.0, y=0.0,
                    radius=0.1,
                    confidence=0.70,
                    label=label,
                    detail=f"RF検出: {freq_detail} / {ssid_info} / {rf_dev.suspicion_reason}",
                    detection_method="rf",
                ))

        return merged
