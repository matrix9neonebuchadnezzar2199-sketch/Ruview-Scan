"""
RuView Scan - AoA推定 (Angle of Arrival)
=========================================
2×2 MIMO 空間スムージングMUSIC
"""

import logging
from dataclasses import dataclass
from typing import List

import numpy as np

from src.csi.models import CSIFrame
from src.utils.math_utils import (
    build_covariance_matrix, music_spectrum,
    aoa_steering_vector, find_peaks_1d,
)

logger = logging.getLogger(__name__)


@dataclass
class AoAEstimate:
    """推定されたAoA"""
    azimuth: float      # 水平角 (rad) — 0=正面, +π/2=右
    elevation: float    # 仰角 (rad) — 0=水平, +π/2=上
    power: float        # 相対パワー
    confidence: float   # 信頼度 0.0~1.0


class AoAEstimator:
    """2×2 MIMO AoA推定"""

    def __init__(self, method: str = 'music'):
        self.method = method

    def estimate_aoa(self, frames: List[CSIFrame]) -> List[AoAEstimate]:
        """
        CSIフレームからAoAを推定

        2×2 MIMOのため角度分解能は限定的。ToF推定の補助として使用。
        """
        if not frames:
            return []

        ref = frames[0]
        wavelength = 0.125 if ref.frequency_band == '2.4GHz' else 0.06  # m
        n_antennas = ref.n_rx

        if n_antennas < 2:
            logger.warning("AoA推定にはRXアンテナが2本以上必要です")
            return []

        # 各サブキャリアでアンテナ間CSIを収集
        h_matrix = self._build_antenna_matrix(frames)

        # MUSICで方位角推定
        R = build_covariance_matrix(h_matrix)
        n_signals = min(2, n_antennas - 1)

        # 角度探索 (-90° ~ +90°)
        n_search = 361
        angles = np.linspace(-np.pi / 2, np.pi / 2, n_search)

        steering = np.zeros((n_antennas, n_search), dtype=complex)
        for k, theta in enumerate(angles):
            steering[:, k] = aoa_steering_vector(n_antennas, wavelength, theta).flatten()

        spectrum = music_spectrum(R, n_signals, steering)

        # ピーク検出
        peak_indices = find_peaks_1d(spectrum, 4, min_distance=20)

        aoas = []
        max_power = np.max(spectrum) if np.max(spectrum) > 0 else 1.0
        for idx in peak_indices:
            power = float(spectrum[idx] / max_power)
            # 2×2 MIMOでは信頼度が低い
            conf = min(0.7, power * 0.5 + 0.1)

            aoas.append(AoAEstimate(
                azimuth=float(angles[idx]),
                elevation=0.0,  # 垂直面の推定は2×2では困難
                power=round(power, 4),
                confidence=round(conf, 2),
            ))

        return aoas

    def _build_antenna_matrix(self, frames: List[CSIFrame]) -> np.ndarray:
        """
        フレームリストからアンテナ×サブキャリアのCSI行列を構築

        Returns:
            h_matrix: shape (n_rx, n_subcarriers * n_frames_sampled)
        """
        ref = frames[0]
        n_rx = ref.n_rx
        n_tx = ref.n_tx
        n_sc = ref.n_subcarriers

        # フレームのサンプリング (最大100フレーム)
        sample_count = min(len(frames), 100)
        step = max(1, len(frames) // sample_count)
        sampled = frames[::step][:sample_count]

        # 各フレームから RX アンテナごとのCSIを抽出
        columns = []
        for frame in sampled:
            h = frame.complex_csi  # (n_sc, n_tx * n_rx)
            # RXアンテナごとにサブキャリアベクトルを抽出
            for sc_idx in range(0, n_sc, max(1, n_sc // 20)):
                col = np.zeros(n_rx, dtype=complex)
                for rx in range(n_rx):
                    stream_idx = rx * n_tx  # 最初のTXアンテナを使用
                    if stream_idx < h.shape[1]:
                        col[rx] = h[sc_idx, stream_idx]
                columns.append(col)

        if not columns:
            return np.eye(n_rx, dtype=complex)

        h_matrix = np.array(columns).T  # (n_rx, n_snapshots)
        return h_matrix
