"""
RuView Scan - 数学・信号処理ユーティリティ
==========================================
共分散行列構築、固有値分解、MUSIC スペクトル計算、ピーク検出
"""

import numpy as np
from scipy import signal as sp_signal
from typing import List, Tuple


def build_covariance_matrix(data: np.ndarray) -> np.ndarray:
    """
    データ行列から空間共分散行列を構築

    Parameters:
        data: shape (M, N) — M: 素子数(サブキャリア), N: スナップショット数
    Returns:
        R: shape (M, M) — 共分散行列
    """
    N = data.shape[1]
    R = (data @ data.conj().T) / N
    return R


def music_spectrum(R: np.ndarray, n_signals: int, steering_vectors: np.ndarray) -> np.ndarray:
    """
    MUSICスペクトルを計算

    Parameters:
        R: shape (M, M) — 共分散行列
        n_signals: 信号源数 (信号部分空間の次元)
        steering_vectors: shape (M, K) — 各候補パラメータのステアリングベクトル
    Returns:
        spectrum: shape (K,) — MUSICスペクトル値
    """
    eigenvalues, eigenvectors = np.linalg.eigh(R)

    # 固有値を降順にソート
    idx = np.argsort(eigenvalues)[::-1]
    eigenvectors = eigenvectors[:, idx]

    # ノイズ部分空間
    En = eigenvectors[:, n_signals:]

    # MUSIC スペクトル: P(θ) = 1 / |a(θ)^H * En * En^H * a(θ)|
    spectrum = np.zeros(steering_vectors.shape[1])
    En_EnH = En @ En.conj().T

    for k in range(steering_vectors.shape[1]):
        a = steering_vectors[:, k:k+1]
        denom = np.abs(a.conj().T @ En_EnH @ a).item()
        spectrum[k] = 1.0 / max(denom, 1e-15)

    return spectrum


def tof_steering_vector(subcarrier_freqs: np.ndarray, tau: float) -> np.ndarray:
    """
    ToF推定用のステアリングベクトルを生成

    Parameters:
        subcarrier_freqs: shape (M,) — サブキャリア周波数 (Hz)
        tau: 遅延 (秒)
    Returns:
        a: shape (M, 1) — ステアリングベクトル
    """
    a = np.exp(-1j * 2 * np.pi * subcarrier_freqs * tau)
    return a.reshape(-1, 1)


def aoa_steering_vector(n_antennas: int, wavelength: float, theta: float,
                        d: float = None) -> np.ndarray:
    """
    AoA推定用のステアリングベクトルを生成

    Parameters:
        n_antennas: アンテナ数
        wavelength: 波長 (m)
        theta: 到来角 (rad)
        d: アンテナ間距離 (m) — デフォルトは λ/2
    Returns:
        a: shape (n_antennas, 1) — ステアリングベクトル
    """
    if d is None:
        d = wavelength / 2
    n = np.arange(n_antennas)
    a = np.exp(-1j * 2 * np.pi * d * np.sin(theta) / wavelength * n)
    return a.reshape(-1, 1)


def find_peaks_1d(spectrum: np.ndarray, n_peaks: int,
                  min_distance: int = 5) -> List[int]:
    """
    1Dスペクトルからピーク位置を検出

    Parameters:
        spectrum: スペクトル配列
        n_peaks: 検出するピーク数
        min_distance: ピーク間の最小距離 (サンプル数)
    Returns:
        peak_indices: ピーク位置のインデックスリスト (値の降順)
    """
    peaks, properties = sp_signal.find_peaks(
        spectrum,
        distance=min_distance,
        height=0
    )

    if len(peaks) == 0:
        # フォールバック: 最大値の位置
        return [int(np.argmax(spectrum))]

    # 振幅の降順でソート
    heights = properties["peak_heights"]
    sorted_idx = np.argsort(heights)[::-1]
    peaks = peaks[sorted_idx]

    return peaks[:n_peaks].tolist()


def spatial_smoothing(csi: np.ndarray, subarray_size: int) -> np.ndarray:
    """
    空間スムージングによる共分散行列のデコヒーレンス

    Parameters:
        csi: shape (M,) — 1次元CSIベクトル
        subarray_size: サブアレイサイズ
    Returns:
        R: shape (subarray_size, subarray_size) — スムージング済み共分散行列
    """
    M = len(csi)
    num_subarrays = M - subarray_size + 1

    R = np.zeros((subarray_size, subarray_size), dtype=complex)
    for i in range(num_subarrays):
        sub = csi[i:i + subarray_size].reshape(-1, 1)
        R += sub @ sub.conj().T

    R /= num_subarrays
    return R


def estimate_signal_count(eigenvalues: np.ndarray, threshold_ratio: float = 0.1) -> int:
    """
    MDL/AIC的な手法で信号源数を推定 (簡易版)

    Parameters:
        eigenvalues: 降順ソート済みの固有値
        threshold_ratio: 最大固有値に対する閾値比率
    Returns:
        n_signals: 推定信号源数
    """
    if len(eigenvalues) == 0:
        return 0

    threshold = eigenvalues[0] * threshold_ratio
    n_signals = int(np.sum(eigenvalues > threshold))
    return max(1, min(n_signals, len(eigenvalues) - 1))


def get_subcarrier_frequencies(center_freq_hz: float, bandwidth_mhz: int,
                                n_subcarriers: int) -> np.ndarray:
    """
    サブキャリア周波数配列を生成

    Parameters:
        center_freq_hz: 中心周波数 (Hz)
        bandwidth_mhz: 帯域幅 (MHz)
        n_subcarriers: サブキャリア数
    Returns:
        freqs: shape (n_subcarriers,) — 各サブキャリアの周波数 (Hz)
    """
    bw_hz = bandwidth_mhz * 1e6
    delta_f = bw_hz / n_subcarriers
    start_freq = center_freq_hz - bw_hz / 2 + delta_f / 2
    freqs = start_freq + np.arange(n_subcarriers) * delta_f
    return freqs



def aoa_steering_vector_2d(n_antennas: int, wavelength: float,
                           theta: float, phi: float,
                           d: float = None) -> np.ndarray:
    """
    2D AoA推定用ステアリングベクトル (方位角 + 仰角)

    ULA (Uniform Linear Array) を仮定し、方位角と仰角の両方を考慮した
    位相差ベクトルを生成する。

    Parameters:
        n_antennas: アンテナ数 (仮想アンテナ数を含む)
        wavelength: 波長 (m)
        theta: 方位角 (rad) — -π/2 ~ +π/2
        phi: 仰角 (rad) — -π/4 ~ +π/4
        d: アンテナ間距離 (m) — デフォルトは λ/2
    Returns:
        a: shape (n_antennas, 1) — ステアリングベクトル
    """
    if d is None:
        d = wavelength / 2
    n = np.arange(n_antennas)
    # ULAの場合、仰角は sin(theta)*cos(phi) として影響
    spatial_freq = d * np.sin(theta) * np.cos(phi) / wavelength
    a = np.exp(-1j * 2 * np.pi * spatial_freq * n)
    return a.reshape(-1, 1)


def music_spectrum_2d(R: np.ndarray, n_signals: int,
                      n_antennas: int, wavelength: float,
                      azimuth_range: np.ndarray,
                      elevation_range: np.ndarray,
                      d: float = None) -> np.ndarray:
    """
    2D MUSICスペクトルを計算 (方位角 × 仰角)

    ベクトル化により高速に計算する。

    Parameters:
        R: shape (M, M) — 共分散行列
        n_signals: 信号源数
        n_antennas: アンテナ数 (M)
        wavelength: 波長 (m)
        azimuth_range: shape (N_az,) — 方位角候補 (rad)
        elevation_range: shape (N_el,) — 仰角候補 (rad)
        d: アンテナ間距離 (m) — デフォルト λ/2
    Returns:
        spectrum: shape (N_az, N_el) — 2D MUSICスペクトル
    """
    if d is None:
        d = wavelength / 2

    # 固有値分解 → ノイズ部分空間
    eigenvalues, eigenvectors = np.linalg.eigh(R)
    idx = np.argsort(eigenvalues)[::-1]
    eigenvectors = eigenvectors[:, idx]
    En = eigenvectors[:, n_signals:]
    En_EnH = En @ En.conj().T

    n_az = len(azimuth_range)
    n_el = len(elevation_range)
    spectrum = np.zeros((n_az, n_el))

    # アンテナインデックス
    n = np.arange(n_antennas)

    # 方位角ごとにベクトル化 (仰角方向は一括計算)
    for i, theta in enumerate(azimuth_range):
        sin_theta = np.sin(theta)
        # cos(phi) を仰角候補全体で一括計算
        cos_phi = np.cos(elevation_range)  # (N_el,)
        # 空間周波数: (N_el,) の各値に対して n_antennas 個の位相
        spatial_freq = d * sin_theta * cos_phi / wavelength  # (N_el,)
        # ステアリング行列: (n_antennas, N_el)
        phase_matrix = -1j * 2 * np.pi * np.outer(n, spatial_freq)
        A = np.exp(phase_matrix)  # (n_antennas, N_el)

        # MUSIC: P = 1 / |a^H En En^H a| を一括計算
        # En_EnH @ A: (n_antennas, N_el)
        tmp = En_EnH @ A  # (n_antennas, N_el)
        # 各列の内積: sum(A.conj() * tmp, axis=0)
        denom = np.abs(np.sum(A.conj() * tmp, axis=0))  # (N_el,)
        spectrum[i, :] = 1.0 / np.maximum(denom, 1e-15)

    return spectrum
