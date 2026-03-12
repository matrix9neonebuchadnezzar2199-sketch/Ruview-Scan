"""
RuView Scan - AoA推定 (Angle of Arrival)
=========================================
2×2 MIMO サブキャリアスムージングMUSIC
Phase F-1a: サブキャリアスムージングで仮想アンテナ数を拡大し角度分解能を向上
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from src.csi.models import CSIFrame
from src.utils.math_utils import (
    build_covariance_matrix, music_spectrum,
    aoa_steering_vector, find_peaks_1d,
    aoa_steering_vector_2d, music_spectrum_2d,
)
from src.utils.geo_utils import Point3D, RoomDimensions, project_to_wall, get_measurement_position



logger = logging.getLogger(__name__)


@dataclass
class AoAEstimate:
    """推定されたAoA"""
    azimuth: float      # 水平角 (rad) — 0=正面, +π/2=右
    elevation: float    # 仰角 (rad) — 0=水平, +π/2=上
    power: float        # 相対パワー
    confidence: float   # 信頼度 0.0~1.0


class AoAEstimator:
    """
    2×2 MIMO AoA推定

    サブキャリアスムージングMUSIC:
      2×2 MIMO (n_rx=2) では物理アンテナ数が不足し MUSIC の角度分解能が低い。
      隣接サブキャリア間の位相勾配がアンテナ間位相差と等価であることを利用し、
      サブキャリア方向にスライディングウィンドウ (サイズ L) を適用して
      仮想的にアンテナ数を n_rx × L に拡大する。
      Forward-backward averaging でコヒーレント信号のデコヒーレンスも行う。

      160MHz (468 sc), L=20 → 実効アンテナ数 = 2 × 20 = 40
      80MHz  (234 sc), L=15 → 実効アンテナ数 = 2 × 15 = 30
      40MHz  (114 sc), L=10 → 実効アンテナ数 = 2 × 10 = 20
    """

    # ERR-AOA-001: サブキャリア数に応じたデフォルトウィンドウサイズ
    DEFAULT_WINDOW_MAP = {
        468: 20,   # 160MHz
        234: 15,   # 80MHz
        114: 10,   # 40MHz
    }

    def __init__(self, method: str = 'music', smoothing_window: Optional[int] = None):
        """
        Args:
            method: 推定手法 ('music')
            smoothing_window: サブキャリアスムージングのウィンドウサイズ
                              None の場合はサブキャリア数から自動決定
        """
        self.method = method
        self.smoothing_window = smoothing_window

    def _get_window_size(self, n_subcarriers: int) -> int:
        """
        サブキャリア数に応じたスムージングウィンドウサイズを決定

        ERR-AOA-002: ウィンドウサイズの自動決定ロジック
        """
        if self.smoothing_window is not None:
            return self.smoothing_window

        # 既知のサブキャリア数に一致する場合
        if n_subcarriers in self.DEFAULT_WINDOW_MAP:
            return self.DEFAULT_WINDOW_MAP[n_subcarriers]

        # 汎用: サブキャリア数の 1/20 を目安に (最小3, 最大30)
        auto_size = max(3, min(30, n_subcarriers // 20))
        return auto_size

    def estimate_aoa(self, frames: List[CSIFrame]) -> List[AoAEstimate]:
        """
        CSIフレームからAoAを推定

        サブキャリア数が十分な場合はサブキャリアスムージングMUSICを使用し、
        不足する場合は従来の2×2 MUSICにフォールバックする。
        """
        if not frames:
            return []

        ref = frames[0]
        wavelength = 0.125 if ref.frequency_band == '2.4GHz' else 0.06  # m
        n_rx = ref.n_rx
        n_tx = ref.n_tx
        n_sc = ref.n_subcarriers

        if n_rx < 2:
            logger.warning("ERR-AOA-003: AoA推定にはRXアンテナが2本以上必要です")
            return []

        # サブキャリアスムージングの適用判定
        window_size = self._get_window_size(n_sc)
        min_sc_for_smoothing = window_size * 2  # 最低でもウィンドウの2倍

        if n_sc >= min_sc_for_smoothing:
            # --- サブキャリアスムージング MUSIC ---
            logger.info(
                f"サブキャリアスムージングMUSIC: "
                f"n_sc={n_sc}, window={window_size}, "
                f"仮想アンテナ数={n_rx * window_size}"
            )
            R, virtual_antennas = self._smoothed_covariance(
                frames, n_rx, n_tx, n_sc, window_size
            )
        else:
            # --- フォールバック: 従来の 2×2 MUSIC ---
            logger.info(
                f"従来MUSIC (サブキャリア不足): "
                f"n_sc={n_sc}, 必要={min_sc_for_smoothing}"
            )
            h_matrix = self._build_antenna_matrix(frames)
            R = build_covariance_matrix(h_matrix)
            virtual_antennas = n_rx

        # 信号数の推定 (仮想アンテナ数に応じて調整)
        n_signals = min(4, max(1, virtual_antennas // 4))

        # 角度探索 (-90° ~ +90°)
        n_search = 361
        angles = np.linspace(-np.pi / 2, np.pi / 2, n_search)

        # ステアリングベクトル生成 (仮想アンテナ数に対応)
        steering = np.zeros((virtual_antennas, n_search), dtype=complex)
        for k, theta in enumerate(angles):
            steering[:, k] = aoa_steering_vector(
                virtual_antennas, wavelength, theta
            ).flatten()

        # MUSIC スペクトル計算
        spectrum = music_spectrum(R, n_signals, steering)

        # ピーク検出
        peak_indices = find_peaks_1d(spectrum, 4, min_distance=15)

        aoas = []
        max_power = np.max(spectrum) if np.max(spectrum) > 0 else 1.0
        mean_power = np.mean(spectrum) if np.mean(spectrum) > 0 else 1.0

        for idx in peak_indices:
            power = float(spectrum[idx] / max_power)

            # 多指標信頼度
            conf = self._compute_confidence(
                spectrum=spectrum,
                peak_idx=idx,
                max_power=max_power,
                mean_power=mean_power,
                virtual_antennas=virtual_antennas,
                n_rx=n_rx,
            )

            aoas.append(AoAEstimate(
                azimuth=float(angles[idx]),
                elevation=0.0,
                power=round(power, 4),
                confidence=round(conf, 2),
            ))

        logger.info(
            f"AoA推定完了: {len(aoas)}パス検出, "
            f"仮想アンテナ={virtual_antennas}, "
            f"方位角={[f'{np.degrees(a.azimuth):.1f}°' for a in aoas]}"
        )

        return aoas


    def _smoothed_covariance(
        self,
        frames: List[CSIFrame],
        n_rx: int,
        n_tx: int,
        n_sc: int,
        window_size: int,
    ) -> tuple:
        """
        サブキャリアスムージングによる拡大共分散行列を構築

        手法:
          1. 各フレームの complex_csi から (n_rx, n_subcarriers) 行列を取得
             (最初の TX アンテナのストリームを使用)
          2. サブキャリア軸に沿ってウィンドウサイズ L でスライド
          3. 各ウィンドウ位置で (n_rx × L, 1) のスナップショットベクトルを構築
          4. Forward-backward averaging で共分散行列を推定

        Args:
            frames: CSIフレームリスト
            n_rx: RXアンテナ数
            n_tx: TXアンテナ数
            n_sc: サブキャリア数
            window_size: スムージングウィンドウサイズ (L)

        Returns:
            (R, virtual_antennas): スムージング済み共分散行列と仮想アンテナ数

        ERR-AOA-004: サブキャリアスムージング実行
        """
        virtual_antennas = n_rx * window_size
        R = np.zeros((virtual_antennas, virtual_antennas), dtype=complex)
        n_snapshots = 0

        # フレームのサンプリング (最大50フレーム)
        sample_count = min(len(frames), 50)
        step = max(1, len(frames) // sample_count)
        sampled = frames[::step][:sample_count]

        # 反転行列 (Forward-backward averaging 用)
        J = np.fliplr(np.eye(virtual_antennas))

        for frame in sampled:
            # complex_csi: shape (n_sc, n_tx * n_rx)
            h = frame.complex_csi

            # RX アンテナごとのサブキャリアベクトルを取得 (最初の TX を使用)
            # h_rx: shape (n_rx, n_sc)
            h_rx = np.zeros((n_rx, n_sc), dtype=complex)
            for rx in range(n_rx):
                stream_idx = rx * n_tx  # TX=0 のストリーム
                if stream_idx < h.shape[1]:
                    h_rx[rx, :] = h[:, stream_idx]

            # サブキャリア方向にスライディングウィンドウ
            n_windows = n_sc - window_size + 1
            for i in range(n_windows):
                # 各RXアンテナの window_size 個のサブキャリアを結合
                # snapshot: shape (n_rx * window_size,)
                snapshot = h_rx[:, i:i + window_size].flatten()

                # Forward contribution
                s = snapshot.reshape(-1, 1)
                R += s @ s.conj().T

                # Backward contribution (FB averaging)
                s_conj = J @ snapshot.conj().reshape(-1, 1)
                R += s_conj @ s_conj.conj().T

                n_snapshots += 2

        # 正規化
        if n_snapshots > 0:
            R /= n_snapshots

        # 対角荷重 (数値安定性)
        R += np.eye(virtual_antennas) * 1e-10

        logger.debug(
            f"スムージング共分散行列: shape={R.shape}, "
            f"snapshots={n_snapshots}, "
            f"rank≈{np.linalg.matrix_rank(R, tol=1e-6)}"
        )

        return R, virtual_antennas

    def _build_antenna_matrix(self, frames: List[CSIFrame]) -> np.ndarray:
        """
        フレームリストからアンテナ×サブキャリアのCSI行列を構築 (従来方式)

        サブキャリア数が少なくスムージングが適用できない場合のフォールバック。

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


    def estimate_aoa_2d(self, frames: List[CSIFrame],
                        az_points: int = 181,
                        el_points: int = 91) -> List[AoAEstimate]:
        """
        2D MUSIC: 方位角 × 仰角 のグリッドサーチによるAoA推定

        天井・床方向の反射パスも検出可能にする。
        サブキャリアスムージングを適用した拡大共分散行列を使用する。

        Args:
            frames: CSIフレームリスト
            az_points: 方位角の探索点数 (デフォルト181 → 1°刻み)
            el_points: 仰角の探索点数 (デフォルト91 → 1°刻み)

        Returns:
            AoAEstimate のリスト (方位角・仰角の両方が設定される)

        ERR-AOA-010: 2D MUSIC 推定
        """
        if not frames:
            return []

        ref = frames[0]
        wavelength = 0.125 if ref.frequency_band == '2.4GHz' else 0.06
        n_rx = ref.n_rx
        n_tx = ref.n_tx
        n_sc = ref.n_subcarriers

        if n_rx < 2:
            logger.warning("ERR-AOA-011: 2D AoA推定にはRXアンテナが2本以上必要です")
            return []

        # サブキャリアスムージング共分散行列を取得
        window_size = self._get_window_size(n_sc)
        min_sc = window_size * 2

        if n_sc >= min_sc:
            R, virtual_antennas = self._smoothed_covariance(
                frames, n_rx, n_tx, n_sc, window_size
            )
        else:
            h_matrix = self._build_antenna_matrix(frames)
            R = build_covariance_matrix(h_matrix)
            virtual_antennas = n_rx

        # 信号数
        n_signals = min(4, max(1, virtual_antennas // 4))

        # 探索グリッド
        azimuth_range = np.linspace(-np.pi / 2, np.pi / 2, az_points)
        elevation_range = np.linspace(-np.pi / 4, np.pi / 4, el_points)

        logger.info(
            f"2D MUSIC: 仮想アンテナ={virtual_antennas}, "
            f"グリッド={az_points}×{el_points}={az_points * el_points}点"
        )

        # 2D MUSIC スペクトル計算
        spectrum_2d = music_spectrum_2d(
            R, n_signals, virtual_antennas, wavelength,
            azimuth_range, elevation_range
        )

        # 2Dピーク検出
        aoas = self._find_2d_peaks(
            spectrum_2d, azimuth_range, elevation_range,
            virtual_antennas, max_peaks=6
        )

        logger.info(
            f"2D AoA推定完了: {len(aoas)}パス検出, "
            f"方位角={[f'{np.degrees(a.azimuth):.1f}°' for a in aoas]}, "
            f"仰角={[f'{np.degrees(a.elevation):.1f}°' for a in aoas]}"
        )

        return aoas

    def _find_2d_peaks(
        self,
        spectrum_2d: np.ndarray,
        azimuth_range: np.ndarray,
        elevation_range: np.ndarray,
        virtual_antennas: int,
        max_peaks: int = 6,
        neighborhood: int = 5,
    ) -> List[AoAEstimate]:
        """
        2Dスペクトルからピークを検出

        局所最大値を検出し、パワー降順でソートして上位 max_peaks 個を返す。

        Args:
            spectrum_2d: shape (N_az, N_el) — 2D MUSICスペクトル
            azimuth_range: 方位角配列
            elevation_range: 仰角配列
            virtual_antennas: 仮想アンテナ数 (信頼度計算用)
            max_peaks: 最大ピーク数
            neighborhood: ピーク検出の近傍サイズ (セル数)

        Returns:
            AoAEstimate のリスト

        ERR-AOA-012: 2D ピーク検出
        """
        from scipy.ndimage import maximum_filter

        # 局所最大値の検出
        local_max = maximum_filter(spectrum_2d, size=neighborhood)
        peaks_mask = (spectrum_2d == local_max) & (spectrum_2d > 0)

        # ピーク位置を取得
        peak_coords = np.argwhere(peaks_mask)  # (n_peaks, 2) — [az_idx, el_idx]

        if len(peak_coords) == 0:
            # フォールバック: 全体の最大値
            flat_idx = np.argmax(spectrum_2d)
            az_idx, el_idx = np.unravel_index(flat_idx, spectrum_2d.shape)
            peak_coords = np.array([[az_idx, el_idx]])

        # パワー値でソート (降順)
        peak_powers = np.array([
            spectrum_2d[az_idx, el_idx]
            for az_idx, el_idx in peak_coords
        ])
        sorted_indices = np.argsort(peak_powers)[::-1]
        peak_coords = peak_coords[sorted_indices]
        peak_powers = peak_powers[sorted_indices]

        # 上位 max_peaks 個を選択
        peak_coords = peak_coords[:max_peaks]
        peak_powers = peak_powers[:max_peaks]

        # 正規化
        max_power = peak_powers[0] if peak_powers[0] > 0 else 1.0

        aoas = []
        for (az_idx, el_idx), power in zip(peak_coords, peak_powers):
            norm_power = float(power / max_power)

            # 信頼度
            if virtual_antennas > 2:
                antenna_factor = min(1.0, virtual_antennas / 40.0)
                conf = min(0.95, norm_power * 0.5 + antenna_factor * 0.3)
            else:
                conf = min(0.6, norm_power * 0.4 + 0.1)

            aoas.append(AoAEstimate(
                azimuth=float(azimuth_range[az_idx]),
                elevation=float(elevation_range[el_idx]),
                power=round(norm_power, 4),
                confidence=round(conf, 2),
            ))

        return aoas


    def estimate_aoa_multiband(
        self,
        band_frames: dict,
        use_2d: bool = False,
    ) -> List[AoAEstimate]:
        """
        マルチバンド AoA 融合

        各バンドで独立に AoA 推定を行い、帯域幅に比例した重みで
        信頼度加重平均により統合する。

        Args:
            band_frames: バンドごとのフレームリスト
                {"2.4GHz": [frames], "5GHz": [frames], "5GHz_160": [frames]}
                キーが存在しないバンドはスキップ
            use_2d: True の場合 estimate_aoa_2d を使用 (方位角+仰角)
                    False の場合 estimate_aoa を使用 (方位角のみ)

        Returns:
            融合された AoAEstimate のリスト

        ERR-AOA-020: マルチバンド AoA 融合
        """
        # 帯域幅に比例した重み (MHz)
        BAND_WEIGHTS = {
            '2.4GHz':   40.0,
            '5GHz':     80.0,
            '5GHz_160': 160.0,
        }

        # 各バンドで独立に推定
        band_results: List[tuple] = []  # [(weight, [AoAEstimate, ...]), ...]

        for band_key, frames in band_frames.items():
            if not frames:
                continue

            weight = BAND_WEIGHTS.get(band_key, 40.0)

            if use_2d:
                estimates = self.estimate_aoa_2d(frames)
            else:
                estimates = self.estimate_aoa(frames)

            if estimates:
                band_results.append((weight, estimates))
                logger.info(
                    f"バンド {band_key} (重み={weight}): "
                    f"{len(estimates)}パス検出"
                )

        if not band_results:
            logger.warning("ERR-AOA-021: 全バンドで AoA 推定結果なし")
            return []

        # 単一バンドの場合はそのまま返す
        if len(band_results) == 1:
            return band_results[0][1]

        # 複数バンドの融合: 方位角の近いピーク同士をマッチングして統合
        fused = self._fuse_multiband(band_results)

        logger.info(
            f"マルチバンド融合完了: {len(fused)}パス, "
            f"入力バンド数={len(band_results)}"
        )

        return fused

    def _fuse_multiband(
        self,
        band_results: List[tuple],
        match_threshold_rad: float = 0.25,
    ) -> List[AoAEstimate]:
        """
        複数バンドの AoA 推定結果を方位角ベースでマッチング・融合

        方位角の差が match_threshold_rad (≈14.3°) 以内のピーク同士を
        同一パスとみなし、帯域幅重み × 信頼度で加重平均する。
        マッチしないピークは単独でそのまま残す。

        Args:
            band_results: [(weight, [AoAEstimate, ...]), ...]
            match_threshold_rad: マッチング閾値 (rad)

        Returns:
            融合された AoAEstimate のリスト

        ERR-AOA-022: バンド間ピークマッチング
        """
        # 全ピークを (weight, estimate) のフラットリストに展開
        all_peaks: List[tuple] = []
        for weight, estimates in band_results:
            for est in estimates:
                all_peaks.append((weight, est))

        if not all_peaks:
            return []

        # 方位角でソート
        all_peaks.sort(key=lambda x: x[1].azimuth)

        # グリーディマッチング: 近い方位角のピークをクラスタリング
        clusters: List[List[tuple]] = []
        used = set()

        for i, (w_i, e_i) in enumerate(all_peaks):
            if i in used:
                continue

            cluster = [(w_i, e_i)]
            used.add(i)

            for j in range(i + 1, len(all_peaks)):
                if j in used:
                    continue
                w_j, e_j = all_peaks[j]

                # 方位角の差をチェック
                az_diff = abs(e_i.azimuth - e_j.azimuth)
                if az_diff <= match_threshold_rad:
                    cluster.append((w_j, e_j))
                    used.add(j)
                elif e_j.azimuth - e_i.azimuth > match_threshold_rad:
                    # ソート済みなのでこれ以降は閾値超え
                    break

            clusters.append(cluster)

        # 各クラスタを加重平均で融合
        fused = []
        total_weight_all = sum(w for w, _ in all_peaks)

        for cluster in clusters:
            if len(cluster) == 1:
                # 単独ピーク: そのまま採用 (ただし信頼度を少し下げる)
                w, est = cluster[0]
                fused.append(AoAEstimate(
                    azimuth=est.azimuth,
                    elevation=est.elevation,
                    power=est.power,
                    confidence=round(est.confidence * 0.8, 2),
                ))
            else:
                # 複数バンドで検出: 加重平均
                weights = np.array([
                    w * est.confidence for w, est in cluster
                ])
                weight_sum = weights.sum()

                if weight_sum <= 0:
                    continue

                az = sum(w * est.confidence * est.azimuth
                         for w, est in cluster) / weight_sum
                el = sum(w * est.confidence * est.elevation
                         for w, est in cluster) / weight_sum
                pw = max(est.power for _, est in cluster)

                # 複数バンドで一致 → 信頼度ブースト
                n_bands = len(cluster)
                base_conf = weight_sum / total_weight_all
                band_boost = min(0.2, n_bands * 0.08)
                conf = min(0.98, base_conf + band_boost + pw * 0.3)

                fused.append(AoAEstimate(
                    azimuth=round(float(az), 4),
                    elevation=round(float(el), 4),
                    power=round(float(pw), 4),
                    confidence=round(float(conf), 2),
                ))

        # 信頼度降順でソート
        fused.sort(key=lambda x: x.confidence, reverse=True)

        return fused


    def aoa_to_wall_position(
        self,
        aoa: AoAEstimate,
        tof_distance: float,
        measurement_point: str,
        room: RoomDimensions,
    ) -> Optional[dict]:
        """
        AoA (方位角, 仰角) + ToF (距離) → 壁面上の反射位置

        Args:
            aoa: AoA推定結果
            tof_distance: ToF推定による片道距離 (m)
            measurement_point: 計測点ID
            room: 部屋寸法

        Returns:
            dict or None:
                {"face", "u", "v", "distance", "azimuth_deg", "elevation_deg", "confidence"}

        ERR-AOA-030: AoA→壁面位置変換
        """
        if tof_distance <= 0:
            logger.warning("ERR-AOA-031: ToF距離が0以下です")
            return None

        if aoa.confidence < 0.1:
            logger.debug("ERR-AOA-032: AoA信頼度が低すぎます (< 0.1)")
            return None

        # 計測点の3D座標を取得
        point = get_measurement_position(measurement_point, room)

        # project_to_wall を使用して壁面に投影
        face, u, v = project_to_wall(
            point=point,
            distance=tof_distance,
            angle_h=aoa.azimuth,
            angle_v=aoa.elevation,
            room=room,
        )

        result = {
            "face": face,
            "u": round(u, 3),
            "v": round(v, 3),
            "distance": round(tof_distance, 3),
            "azimuth_deg": round(float(np.degrees(aoa.azimuth)), 1),
            "elevation_deg": round(float(np.degrees(aoa.elevation)), 1),
            "confidence": aoa.confidence,
        }

        logger.debug(
            f"AoA→壁面: {measurement_point} → {face} "
            f"(u={u:.2f}, v={v:.2f}), "
            f"az={np.degrees(aoa.azimuth):.1f}°, "
            f"el={np.degrees(aoa.elevation):.1f}°, "
            f"dist={tof_distance:.2f}m"
        )

        return result

    def batch_aoa_to_wall(
        self,
        aoas: List[AoAEstimate],
        tof_distances: List[float],
        measurement_point: str,
        room: RoomDimensions,
        min_confidence: float = 0.2,
    ) -> List[dict]:
        """
        複数の AoA 推定結果を一括で壁面位置に変換

        Args:
            aoas: AoA推定結果リスト
            tof_distances: 各パスの ToF 距離リスト (aoas と同じ長さ)
            measurement_point: 計測点ID
            room: 部屋寸法
            min_confidence: 最低信頼度 (これ未満のパスは除外)

        Returns:
            壁面位置 dict のリスト (信頼度降順)

        ERR-AOA-033: バッチ壁面位置変換
        """
        if len(aoas) != len(tof_distances):
            logger.warning(
                f"ERR-AOA-034: AoA数({len(aoas)})とToF距離数({len(tof_distances)})が不一致"
            )
            n = min(len(aoas), len(tof_distances))
            aoas = aoas[:n]
            tof_distances = tof_distances[:n]

        results = []
        for aoa, dist in zip(aoas, tof_distances):
            if aoa.confidence < min_confidence:
                continue

            pos = self.aoa_to_wall_position(aoa, dist, measurement_point, room)
            if pos is not None:
                results.append(pos)

        results.sort(key=lambda x: x["confidence"], reverse=True)

        logger.info(
            f"バッチ壁面変換: {len(results)}/{len(aoas)}パス変換成功 "
            f"(計測点={measurement_point})"
        )

        return results


    def _compute_confidence(
        self,
        spectrum: np.ndarray,
        peak_idx: int,
        max_power: float,
        mean_power: float,
        virtual_antennas: int,
        n_rx: int,
        half_width_threshold: float = 0.5,
    ) -> float:
        """
        多指標による AoA 信頼度スコア計算

        4つの指標の加重平均で信頼度を算出する:
          1. SNR (信号対雑音比)         — 重み 0.30
          2. ピーク鋭さ                 — 重み 0.25
          3. アンテナファクター         — 重み 0.25
          4. ピーク相対パワー           — 重み 0.20

        Args:
            spectrum: MUSICスペクトル配列
            peak_idx: ピークのインデックス
            max_power: スペクトルの最大値
            mean_power: スペクトルの平均値
            virtual_antennas: 仮想アンテナ数
            n_rx: 物理RXアンテナ数
            half_width_threshold: 半値幅の閾値比率

        Returns:
            confidence: 0.0 ~ 1.0

        ERR-AOA-040: 信頼度計算
        """
        # --- 指標1: SNR (ピーク値 / 平均値) ---
        snr_linear = spectrum[peak_idx] / max(mean_power, 1e-15)
        snr_db = 10 * np.log10(max(snr_linear, 1e-10))
        # SNR 0~30dB を 0.0~1.0 にマッピング
        snr_score = float(np.clip(snr_db / 30.0, 0.0, 1.0))

        # --- 指標2: ピーク鋭さ (半値幅の逆数) ---
        peak_val = spectrum[peak_idx]
        half_val = peak_val * half_width_threshold
        # 左方向の半値幅
        left_width = 0
        for k in range(peak_idx - 1, -1, -1):
            if spectrum[k] < half_val:
                break
            left_width += 1
        # 右方向の半値幅
        right_width = 0
        for k in range(peak_idx + 1, len(spectrum)):
            if spectrum[k] < half_val:
                break
            right_width += 1
        total_width = left_width + right_width + 1
        # 幅 1~60 を 1.0~0.1 にマッピング (狭いほど高スコア)
        sharpness_score = float(np.clip(1.0 - (total_width - 1) / 60.0, 0.1, 1.0))

        # --- 指標3: アンテナファクター ---
        if virtual_antennas > n_rx:
            antenna_score = float(np.clip(virtual_antennas / 40.0, 0.2, 1.0))
        else:
            antenna_score = 0.2  # 物理アンテナのみの場合は低スコア

        # --- 指標4: ピーク相対パワー ---
        power_score = float(spectrum[peak_idx] / max(max_power, 1e-15))

        # --- 加重平均 ---
        confidence = (
            0.30 * snr_score +
            0.25 * sharpness_score +
            0.25 * antenna_score +
            0.20 * power_score
        )

        # 最終クリップ
        confidence = float(np.clip(confidence, 0.05, 0.98))

        return confidence
