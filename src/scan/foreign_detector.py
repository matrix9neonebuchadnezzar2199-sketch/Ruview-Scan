"""
RuView Scan - 異物検出 (RF + CSI統合)
Phase C: 位置推定改善、深度スライダー連動、RF位置割当
"""

import logging
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

import numpy as np
from scipy import ndimage

from src.csi.models import ScanSession
from src.scan.reflection_map import ReflectionMap
from src.scan.structure_detector import DetectedStructure
from src.rf.scanner import RFScanner, RFDevice

logger = logging.getLogger(__name__)

# 測定点の部屋内相対位置 (部屋寸法に対する比率)
MEASURE_POINTS = {
    "north": (0.5, 0.15),   # 北壁寄り
    "east":  (0.85, 0.5),   # 東壁寄り
    "south": (0.5, 0.85),   # 南壁寄り
    "west":  (0.15, 0.5),   # 西壁寄り
    "center": (0.5, 0.5),   # 中央
}

# 各測定点から最も近い面
POINT_NEAREST_FACE = {
    "north": "north",
    "east":  "east",
    "south": "south",
    "west":  "west",
    "center": "floor",
}


@dataclass
class ForeignObject:
    """検出された異物"""
    face: str
    x: float
    y: float
    radius: float
    confidence: float
    label: str
    detail: str
    detection_method: str
    threat_level: str = "medium"  # none / low / medium / high


class ForeignDetector:
    """不審デバイス（盗聴器・隠しAP等）を検出
    
    二段階検出:
      1. RFパッシブスキャン → 不審電波源
      2. CSI残差解析 → 既知構造物以外の反射異常
    両者を統合し、位置・脅威レベルを推定する。
    """

    def __init__(self, rf_scanner: RFScanner,
                 residual_threshold: float = 0.5,
                 min_cluster_size: int = 3,
                 room_width: float = 7.2,
                 room_depth: float = 5.4):
        self.rf_scanner = rf_scanner
        self.residual_threshold = residual_threshold
        self.min_cluster_size = min_cluster_size
        self.room_width = room_width
        self.room_depth = room_depth

    async def detect(
        self,
        session: ScanSession,
        reflection_maps: Dict[str, ReflectionMap],
        structures: List[DetectedStructure]
    ) -> List[ForeignObject]:
        """RF + CSI の二段階検出"""
        logger.info("=== 異物検出開始 ===")

        # 第一段階: RFパッシブスキャン
        suspicious_rf = []
        try:
            rf_devices = await self.rf_scanner.scan()
            suspicious_rf = [d for d in rf_devices if d.is_suspicious]
            logger.info(f"RF検出: 全{len(rf_devices)}台 / 不審{len(suspicious_rf)}台")
        except Exception as e:
            logger.warning(f"RFスキャンスキップ: {e}")

        # 第二段階: CSI残差異常パターン
        residual_objects = self._detect_residual(reflection_maps, structures)
        logger.info(f"CSI残差検出: {len(residual_objects)}件")

        # 統合
        merged = self._merge_detections(suspicious_rf, residual_objects)
        logger.info(f"=== 異物検出完了: {len(merged)}件 ===")
        return merged

    def _detect_residual(
        self,
        reflection_maps: Dict[str, ReflectionMap],
        structures: List[DetectedStructure]
    ) -> List[ForeignObject]:
        """反射マップから既知構造物を除去した残差で異物検出"""
        foreign = []

        for face, rmap in reflection_maps.items():
            grid = rmap.grid.copy()

            # 既知構造物の領域をマスク (ゼロ化)
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
                x_m = float(cx * rmap.resolution)
                y_m = float(cy * rmap.resolution)

                # サイズ推定
                radius = float(np.sqrt(len(coords)) * rmap.resolution / 2)

                # 強度
                intensity = float(np.mean(grid[component]))
                max_intensity = float(np.max(grid[component]))

                # 脅威レベル判定
                threat = self._assess_threat_csi(intensity, max_intensity, len(coords))

                # ラベル生成
                face_jp = {"floor": "床", "ceiling": "天井",
                           "north": "北壁", "south": "南壁",
                           "east": "東壁", "west": "西壁"}.get(face, face)

                foreign.append(ForeignObject(
                    face=face,
                    x=round(x_m, 2),
                    y=round(y_m, 2),
                    radius=round(max(radius, 0.03), 2),
                    confidence=round(min(0.9, intensity * 0.8 + 0.1), 2),
                    label=f"{face_jp}内 不明反射源",
                    detail=f"CSI残差検出 / 強度{intensity:.2f} / "
                           f"サイズ{len(coords)}px / {radius*100:.0f}cm",
                    detection_method="csi",
                    threat_level=threat,
                ))

        return foreign

    def _assess_threat_csi(self, intensity: float, max_intensity: float,
                           pixel_count: int) -> str:
        """CSI残差から脅威レベルを判定"""
        if max_intensity > 0.85 and pixel_count >= 10:
            return "high"
        elif intensity > 0.65 or pixel_count >= 8:
            return "medium"
        elif intensity > 0.5:
            return "low"
        return "low"

    def _assess_threat_rf(self, device: RFDevice) -> str:
        """RFデバイスから脅威レベルを判定"""
        if device.signal > -15:
            return "high"
        elif not device.ssid and device.signal > -30:
            return "high"
        elif device.signal > -30:
            return "medium"
        elif not device.ssid:
            return "medium"
        return "low"

    def _estimate_rf_position(self, device: RFDevice) -> Tuple[str, float, float]:
        """RSSIベースで不審デバイスの位置を最寄り面に割当
        
        信号強度が最も強い = 最も近い壁に設置されている可能性が高い。
        シミュレーション時は信号強度で面と位置を推定。
        """
        signal = device.signal

        # 非常に強い信号 → 壁の中に埋め込まれている可能性
        if signal > -25:
            # 2.4GHz → 透過性が高い → 壁の奥
            # 5GHz → 減衰が大きい → 壁の表面近く
            if device.frequency == "2.4GHz":
                # 北壁の中央付近と推定 (シミュレーション)
                face = "north"
                x = self.room_width * 0.35
                y = 1.2  # 壁面上の高さ方向位置(m)
            else:
                face = "east"
                x = self.room_depth * 0.6
                y = 1.5
        elif signal > -40:
            # 中程度の信号 → 天井裏の可能性
            face = "ceiling"
            x = self.room_width * 0.4
            y = self.room_depth * 0.3
        else:
            # 弱い信号 → 位置特定困難
            face = "unknown"
            x = 0.0
            y = 0.0

        return face, round(x, 2), round(y, 2)

    def _merge_detections(
        self,
        suspicious_rf: List[RFDevice],
        residual_objects: List[ForeignObject]
    ) -> List[ForeignObject]:
        """RF検出結果とCSI残差検出結果を統合"""
        merged = list(residual_objects)

        for rf_dev in suspicious_rf:
            freq_detail = f"{rf_dev.frequency} ch{rf_dev.channel} " \
                          f"信号{rf_dev.signal}dBm"
            ssid_info = f"SSID:{rf_dev.ssid or '非公開'}"
            bssid_short = rf_dev.bssid[-8:]

            # ラベル決定
            if not rf_dev.ssid and rf_dev.signal > -25:
                label = "盗聴器疑い (隠しAP/壁内)"
            elif not rf_dev.ssid:
                label = "不審デバイス (隠しAP)"
            elif rf_dev.signal > -20:
                label = "不審デバイス (近距離/壁内)"
            else:
                label = "不審デバイス"

            # 位置推定
            face, x, y = self._estimate_rf_position(rf_dev)
            threat = self._assess_threat_rf(rf_dev)

            # 既存のCSI検出と近い位置のものがあれば統合
            matched = False
            for fo in merged:
                if fo.face == face and fo.detection_method == "csi":
                    dist = np.sqrt((fo.x - x)**2 + (fo.y - y)**2)
                    if dist < 1.0:  # 1m以内なら同一と判定
                        fo.detection_method = "both"
                        fo.confidence = round(min(0.98, fo.confidence + 0.2), 2)
                        fo.label = label
                        fo.detail = (f"RF+CSI統合検出 / {freq_detail} / "
                                     f"{ssid_info} / BSSID:..{bssid_short} + "
                                     f"{fo.detail}")
                        fo.threat_level = "high"
                        matched = True
                        logger.info(f"RF+CSI統合: {label} @ {face} "
                                    f"({fo.x},{fo.y}) 信頼度{fo.confidence}")
                        break

            if not matched:
                merged.append(ForeignObject(
                    face=face,
                    x=x,
                    y=y,
                    radius=0.08,
                    confidence=0.75,
                    label=label,
                    detail=f"RF検出: {freq_detail} / {ssid_info} / "
                           f"BSSID:..{bssid_short} / {rf_dev.suspicion_reason}",
                    detection_method="rf",
                    threat_level=threat,
                ))
                logger.info(f"RF検出追加: {label} @ {face} ({x},{y})")

        return merged
