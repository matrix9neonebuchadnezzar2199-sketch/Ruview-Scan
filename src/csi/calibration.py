"""
RuView Scan - 位相キャリブレーション・サニタイズ
===============================================
"""

import logging
import numpy as np

from src.csi.models import CSIFrame

logger = logging.getLogger(__name__)


class PhaseCalibrator:
    """
    CSI位相データのキャリブレーション

    1. 線形位相除去 (SFO/CFO由来)
    2. アンテナ間位相差正規化
    3. 位相アンラッピング
    """

    def __init__(self):
        self._phase_offset = None  # 学習済み位相オフセット

    def calibrate(self, frame: CSIFrame) -> CSIFrame:
        """フレームの位相をキャリブレーション"""
        calibrated_phase = frame.phase.copy()

        # 1. 位相アンラッピング (各ストリーム独立)
        for s in range(calibrated_phase.shape[1]):
            calibrated_phase[:, s] = np.unwrap(calibrated_phase[:, s])

        # 2. 線形位相除去 (SFO/CFO補正)
        for s in range(calibrated_phase.shape[1]):
            calibrated_phase[:, s] = self._remove_linear_phase(
                calibrated_phase[:, s]
            )

        # 3. アンテナ間位相差正規化 (最初のストリームを基準)
        if calibrated_phase.shape[1] > 1:
            ref_phase = calibrated_phase[:, 0]
            for s in range(1, calibrated_phase.shape[1]):
                calibrated_phase[:, s] -= (
                    np.mean(calibrated_phase[:, s] - ref_phase)
                )

        return CSIFrame(
            timestamp=frame.timestamp,
            source_mac=frame.source_mac,
            channel=frame.channel,
            bandwidth=frame.bandwidth,
            frequency_band=frame.frequency_band,
            rssi=frame.rssi,
            noise_floor=frame.noise_floor,
            n_subcarriers=frame.n_subcarriers,
            n_tx=frame.n_tx,
            n_rx=frame.n_rx,
            amplitude=frame.amplitude.copy(),
            phase=calibrated_phase,
        )

    def _remove_linear_phase(self, phase: np.ndarray) -> np.ndarray:
        """
        線形位相成分を最小二乗法で推定し除去

        SFO (Sampling Frequency Offset) と CFO (Carrier Frequency Offset) が
        位相に線形勾配として現れるため、これを除去する。
        """
        n = len(phase)
        x = np.arange(n)

        # 最小二乗法で線形成分 (a*x + b) をフィット
        A = np.vstack([x, np.ones(n)]).T
        try:
            result = np.linalg.lstsq(A, phase, rcond=None)
            slope, intercept = result[0]
        except np.linalg.LinAlgError:
            return phase

        # 線形成分を除去
        linear_component = slope * x + intercept
        return phase - linear_component
