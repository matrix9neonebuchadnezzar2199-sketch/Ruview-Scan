"""
RuView Scan - ToF推定 (Time of Flight)
======================================
CSI位相勾配からマルチパスのToFを推定
"""

import logging
from dataclasses import dataclass
from typing import List

import numpy as np

from src.csi.models import CSIFrame
from src.utils.math_utils import (
    build_covariance_matrix, music_spectrum,
    tof_steering_vector, find_peaks_1d,
    spatial_smoothing, get_subcarrier_frequencies,
)
from src.utils.geo_utils import SPEED_OF_LIGHT, channel_to_freq

logger = logging.getLogger(__name__)


@dataclass
class PathEstimate:
    """推定されたマルチパス成分"""
    tof: float              # 秒
    distance: float         # メートル (c × τ / 2)
    amplitude: float        # 反射強度
    phase: float            # 位相
    path_type: str          # 'direct', 'wall', 'object', 'multi-bounce'


class ToFEstimator:
    """CSI位相勾配からToFを推定"""

    def __init__(self, method: str = 'music', n_paths: int = 5):
        self.method = method    # 'ifft', 'music', 'esprit'
        self.n_paths = n_paths

    def estimate_tof(self, frames: List[CSIFrame]) -> List[PathEstimate]:
        """
        複数フレームからマルチパスのToFを推定

        Parameters:
            frames: CSIフレームリスト (同一バンド)
        Returns:
            paths: PathEstimate のリスト (距離順)
        """
        if not frames:
            return []

        # フレーム情報から周波数パラメータを設定
        ref = frames[0]
        center_freq = channel_to_freq(ref.channel)
        bw_mhz = ref.bandwidth
        n_sc = ref.n_subcarriers

        # CSI行列を構築・平均化 (static scene)
        csi_avg = self._average_csi(frames)

        if self.method == 'music':
            return self._music_tof(csi_avg, center_freq, bw_mhz, n_sc)
        else:
            return self._ifft_tof(csi_avg, center_freq, bw_mhz, n_sc)

    def _average_csi(self, frames: List[CSIFrame]) -> np.ndarray:
        """
        フレームのCSIを時間方向に平均化

        Returns:
            csi_avg: shape (n_subcarriers,) — 平均複素CSI
        """
        csi_stack = []
        for frame in frames:
            # 複素CSI、全ストリームの平均
            h = frame.complex_csi  # (n_sc, n_streams)
            h_mean = np.mean(h, axis=1)  # (n_sc,)
            csi_stack.append(h_mean)

        csi_matrix = np.array(csi_stack)  # (n_frames, n_sc)
        csi_avg = np.mean(csi_matrix, axis=0)  # (n_sc,)
        return csi_avg

    def _ifft_tof(self, csi_avg: np.ndarray, center_freq: float,
                  bw_mhz: int, n_sc: int) -> List[PathEstimate]:
        """IFFT→CIR→ピーク検出による基本的なToF推定"""
        # ゼロパディングで分解能向上
        n_fft = n_sc * 4
        cir = np.fft.ifft(csi_avg, n=n_fft)
        cir_mag = np.abs(cir)

        # レンジ軸の構築
        delta_t = 1.0 / (bw_mhz * 1e6)
        max_range = SPEED_OF_LIGHT * delta_t * n_fft / 2

        # ピーク検出
        peak_indices = find_peaks_1d(cir_mag[:n_fft // 2], self.n_paths, min_distance=3)

        paths = []
        for idx in peak_indices:
            tof = idx * delta_t / 4  # ゼロパディング分を考慮
            distance = SPEED_OF_LIGHT * tof / 2
            amp = float(cir_mag[idx])
            ph = float(np.angle(cir[idx]))

            # パスタイプの分類
            if len(paths) == 0:
                path_type = 'direct'
            elif distance < 5.0:
                path_type = 'wall'
            elif distance < 15.0:
                path_type = 'object'
            else:
                path_type = 'multi-bounce'

            paths.append(PathEstimate(
                tof=tof,
                distance=round(distance, 3),
                amplitude=round(amp, 4),
                phase=round(ph, 4),
                path_type=path_type,
            ))

        return sorted(paths, key=lambda p: p.distance)

    def _music_tof(self, csi_avg: np.ndarray, center_freq: float,
                   bw_mhz: int, n_sc: int) -> List[PathEstimate]:
        """MUSICアルゴリズムによるToF超解像推定"""
        # 空間スムージング
        subarray_size = max(n_sc // 3, 10)
        R = spatial_smoothing(csi_avg, subarray_size)

        # 固有値分解で信号数を推定
        eigenvalues = np.linalg.eigvalsh(R)
        eigenvalues = np.sort(eigenvalues)[::-1]

        n_signals = min(self.n_paths, subarray_size - 2)

        # ステアリングベクトルの構築
        subcarrier_freqs = get_subcarrier_frequencies(center_freq, bw_mhz, subarray_size)
        delta_f = subcarrier_freqs[1] - subcarrier_freqs[0]

        # 探索範囲: 0m ~ 20m
        max_tof = 2 * 20.0 / SPEED_OF_LIGHT
        n_search = 1000
        tof_candidates = np.linspace(0, max_tof, n_search)

        steering = np.zeros((subarray_size, n_search), dtype=complex)
        for k, tau in enumerate(tof_candidates):
            steering[:, k] = tof_steering_vector(subcarrier_freqs, tau).flatten()

        # MUSICスペクトル
        spectrum = music_spectrum(R, n_signals, steering)

        # ピーク検出
        peak_indices = find_peaks_1d(spectrum, self.n_paths, min_distance=10)

        paths = []
        for idx in peak_indices:
            tof = tof_candidates[idx]
            distance = SPEED_OF_LIGHT * tof / 2
            amp = float(np.sqrt(spectrum[idx] / np.max(spectrum)))

            if len(paths) == 0:
                path_type = 'direct'
            elif distance < 5.0:
                path_type = 'wall'
            elif distance < 15.0:
                path_type = 'object'
            else:
                path_type = 'multi-bounce'

            paths.append(PathEstimate(
                tof=tof,
                distance=round(distance, 3),
                amplitude=round(amp, 4),
                phase=0.0,
                path_type=path_type,
            ))

        return sorted(paths, key=lambda p: p.distance)
