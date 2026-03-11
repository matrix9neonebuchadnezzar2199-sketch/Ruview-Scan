"""
RuView Scan - 構造物検出 (配管・配線)
"""

import logging
from dataclasses import dataclass
from typing import List

import numpy as np
from scipy import ndimage

from src.scan.reflection_map import ReflectionMap

logger = logging.getLogger(__name__)


@dataclass
class DetectedStructure:
    """検出された構造物"""
    face: str
    x1: float; y1: float; x2: float; y2: float   # 面上の座標(m)
    material: str           # 'metal', 'wire', 'pvc', 'stud'
    confidence: float       # 0.0~1.0
    intensity: float        # 平均反射強度
    label: str              # 自動生成ラベル


class StructureDetector:
    """反射マップから配管・配線・構造物を検出"""

    def __init__(self,
                 metal_threshold: float = 0.6,
                 nonmetal_threshold: float = 0.35,
                 min_length_m: float = 0.3):
        self.metal_threshold = metal_threshold
        self.nonmetal_threshold = nonmetal_threshold
        self.min_length_m = min_length_m

    def detect(self, rmap: ReflectionMap) -> List[DetectedStructure]:
        """ヒートマップからライン状・点状の構造物を検出"""
        structures = []
        grid = rmap.grid

        # 1. 金属構造物 (高反射)
        metal_mask = grid >= self.metal_threshold
        metal_structures = self._detect_connected(
            metal_mask, grid, rmap, 'metal'
        )
        structures.extend(metal_structures)

        # 2. 非金属構造物 (中反射)
        nonmetal_mask = (grid >= self.nonmetal_threshold) & (~metal_mask)
        nonmetal_structures = self._detect_connected(
            nonmetal_mask, grid, rmap, 'nonmetal'
        )
        structures.extend(nonmetal_structures)

        return structures

    def _detect_connected(
        self, mask: np.ndarray, grid: np.ndarray,
        rmap: ReflectionMap, category: str
    ) -> List[DetectedStructure]:
        """連結成分解析で構造物を検出"""
        labeled, num_features = ndimage.label(mask)
        structures = []

        for i in range(1, num_features + 1):
            component = labeled == i
            coords = np.argwhere(component)

            if len(coords) < 3:
                continue

            # バウンディングボックス (m)
            row_min, col_min = coords.min(axis=0)
            row_max, col_max = coords.max(axis=0)

            x1_raw = col_min * rmap.resolution
            y1_raw = row_min * rmap.resolution
            x2_raw = col_max * rmap.resolution
            y2_raw = row_max * rmap.resolution

            # 配管は水平か垂直に走る (建築基準)
            # バウンディングボックスのアスペクト比で方向を判定
            dx = x2_raw - x1_raw
            dy = y2_raw - y1_raw
            if dx >= dy:
                # 横長 → 水平線 (y座標を中心に揃える)
                y_center = (y1_raw + y2_raw) / 2
                x1 = x1_raw
                y1 = y_center
                x2 = x2_raw
                y2 = y_center
            else:
                # 縦長 → 垂直線 (x座標を中心に揃える)
                x_center = (x1_raw + x2_raw) / 2
                x1 = x_center
                y1 = y1_raw
                x2 = x_center
                y2 = y2_raw

            # 長さチェック
            length = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            if length < self.min_length_m:
                continue

            # 平均反射強度
            intensity = float(np.mean(grid[component]))

            # 材質分類
            material = self._classify_material(intensity, length, x2 - x1, y2 - y1)

            # 信頼度
            confidence = self._calculate_confidence(intensity, len(coords), material)

            # ラベル生成
            label = self._generate_label(material, rmap.face)

            structures.append(DetectedStructure(
                face=rmap.face,
                x1=round(x1, 2), y1=round(y1, 2),
                x2=round(x2, 2), y2=round(y2, 2),
                material=material,
                confidence=round(confidence, 2),
                intensity=round(intensity, 3),
                label=label,
            ))

        return structures

    def _classify_material(self, intensity: float, length: float,
                           dx: float, dy: float) -> str:
        """
        反射強度と形状から材質を分類

        NOTE: detect() の metal_threshold(0.6) / nonmetal_threshold(0.35) は
        連結成分マスクの閾値（粗いフィルタ）。
        ここでの 0.7/0.5/0.35 は成分内の平均強度に基づく細分類閾値。
        意図的な多段分類: 例えば強度0.6~0.7 の metal_mask 成分は
        アスペクト比で wire/metal に再分類される。
        """
        if intensity >= 0.7:
            return 'metal'
        elif intensity >= 0.5:
            # アスペクト比で判別
            aspect = max(dx, dy) / (min(dx, dy) + 0.01)
            if aspect > 5:
                return 'wire'
            return 'metal'
        elif intensity >= 0.35:
            aspect = max(dx, dy) / (min(dx, dy) + 0.01)
            if aspect < 2:
                return 'stud'
            return 'pvc'
        else:
            return 'stud'

    def _calculate_confidence(self, intensity: float, pixel_count: int,
                              material: str) -> float:
        """信頼度を算出"""
        base = {
            'metal': 0.85,
            'wire': 0.70,
            'pvc': 0.55,
            'stud': 0.65,
        }.get(material, 0.5)

        # ピクセル数による補正
        size_factor = min(1.0, pixel_count / 50.0)
        # 強度による補正
        intensity_factor = min(1.0, intensity / 0.8)

        return min(0.99, base * 0.6 + size_factor * 0.2 + intensity_factor * 0.2)

    def _generate_label(self, material: str, face: str) -> str:
        """材質と面から自動ラベルを生成"""
        material_names = {
            'metal': '金属管',
            'wire': '電気配線',
            'pvc': '塩ビ管',
            'stud': '間柱',
        }
        face_names = {
            'floor': '床下',
            'ceiling': '天井裏',
            'north': '北壁内',
            'south': '南壁内',
            'east': '東壁内',
            'west': '西壁内',
        }
        mat_name = material_names.get(material, material)
        face_name = face_names.get(face, face)
        return f"{face_name}{mat_name}"

