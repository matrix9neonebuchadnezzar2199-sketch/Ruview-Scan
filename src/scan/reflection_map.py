"""
RuView Scan - 反射強度ヒートマップ生成 (Phase B: スライドバー深度調整方式)
============================================================================
CSI振幅を各面のグリッドに直接マッピングする。
シミュレーション/実機の区別なく同一ロジックで動作。

方式:
  各計測点の各CSIフレームについて:
    1. 全サブキャリア振幅の平均値を取得
    2. 計測点の位置から各面グリッドセルへの距離を計算
    3. 距離に応じたガウシアン重みで振幅をグリッドに加算
  全面を 0.0〜1.0 に正規化し、ガウシアンフィルタで平滑化。
  表示閾値の制御はフロントエンドのスライドバーに委ねる。
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
from scipy.ndimage import gaussian_filter

from src.csi.models import ScanSession, CSIFrame
from src.utils.geo_utils import RoomDimensions, get_measurement_position

logger = logging.getLogger(__name__)


@dataclass
class ReflectionMap:
    """1面の反射強度マップ"""
    face: str
    width_m: float
    height_m: float
    grid: np.ndarray       # 正規化済み 0.0〜1.0
    resolution: float      # メートル/セル
    band: str


class ReflectionMapGenerator:
    """5箇所のCSIデータから反射強度ヒートマップを生成 (直接マッピング方式)"""

    # ERR-B01: 面仕様定義
    FACE_SPECS = {
        'floor':   {'axes': ('x', 'y'), 'fixed_axis': 'z', 'fixed_val': 0.0},
        'ceiling': {'axes': ('x', 'y'), 'fixed_axis': 'z', 'fixed_val': 'height'},
        'north':   {'axes': ('x', 'z'), 'fixed_axis': 'y', 'fixed_val': 0.0},
        'south':   {'axes': ('x', 'z'), 'fixed_axis': 'y', 'fixed_val': 'depth'},
        'west':    {'axes': ('y', 'z'), 'fixed_axis': 'x', 'fixed_val': 0.0},
        'east':    {'axes': ('y', 'z'), 'fixed_axis': 'x', 'fixed_val': 'width'},
    }

    def __init__(self, room_dims: RoomDimensions,
                 grid_resolution: float = 0.05,
                 gaussian_sigma: float = 2.0,
                 spread_sigma_m: float = 1.5):
        """
        Args:
            room_dims: 部屋寸法
            grid_resolution: グリッド解像度 (m/セル)
            gaussian_sigma: 最終平滑化のガウシアンσ (セル単位)
            spread_sigma_m: 振幅の空間拡散σ (メートル単位)
        """
        self.room = room_dims
        self.grid_resolution = grid_resolution
        self.gaussian_sigma = gaussian_sigma
        self.spread_sigma_m = spread_sigma_m

    def generate(self, session: ScanSession,
                 band: str = 'mix',
                 aoa_positions: Optional[List[dict]] = None) -> Dict[str, ReflectionMap]:

        """6面それぞれの ReflectionMap を生成"""

        # ERR-B02: 計測点ごとのCSI振幅統計を集約
        point_amplitudes = self._extract_amplitudes(session, band)

        if not point_amplitudes:
            logger.warning("ERR-B03: 有効なCSIデータがありません")
            return self._generate_empty_maps(band)

        logger.info(
            f"CSI振幅抽出完了: {len(point_amplitudes)}計測点, "
            f"band={band}"
        )

        # ERR-B04: 各面のグリッドを生成
        # AoA位置データの有無をログ
        if aoa_positions:
            logger.info(f"AoA壁面位置データ: {len(aoa_positions)}件を統合")

        maps = {}
        for face in self.FACE_SPECS:
            grid, fw, fh = self._build_face_grid(face, point_amplitudes)
            # AoA による追加重み
            if aoa_positions:
                grid = self._apply_aoa_weights(grid, face, fw, fh, aoa_positions)

            # 正規化
            if grid.max() > 0:
                grid = grid / grid.max()

            # ガウシアン平滑化
            grid = gaussian_filter(grid, sigma=self.gaussian_sigma)
            grid = np.clip(grid, 0.0, 1.0)

            # 再正規化 (フィルタ後に最大値が1.0になるように)
            if grid.max() > 0:
                grid = grid / grid.max()

            n_active = int(np.sum(grid >= 0.3))
            logger.info(
                f"  {face}: shape={grid.shape}, "
                f"max={grid.max():.3f}, active(>=0.3)={n_active}cells"
            )

        # === 背景差分マップの生成 ===
        # 散乱体なしのベースライン（壁反射のみ）を計算し、差分を取る
        try:
            baseline_amplitudes = self._extract_baseline_amplitudes(point_amplitudes)

            diff_maps = {}
            enhanced_maps = {}

            for face in self.FACE_SPECS:
                if face not in maps:
                    continue

                fw, fh = self._get_face_dimensions(face)

                # ベースラインマップ（壁反射のみの寄与）
                baseline_grid, _, _ = self._build_face_grid(face, baseline_amplitudes)
                if baseline_grid.max() > 0:
                    baseline_grid = baseline_grid / baseline_grid.max()
                baseline_grid = gaussian_filter(baseline_grid, sigma=self.gaussian_sigma)
                if baseline_grid.max() > 0:
                    baseline_grid = baseline_grid / baseline_grid.max()

                # 差分マップ: 通常 - ベースライン
                raw_grid = maps[face].grid.copy()
                diff_grid = np.clip(raw_grid - baseline_grid * 0.85, 0.0, None)
                if diff_grid.max() > 0:
                    diff_grid = diff_grid / diff_grid.max()

                diff_maps[face] = ReflectionMap(
                    face=face,
                    width_m=fw,
                    height_m=fh,
                    grid=diff_grid,
                    resolution=self.grid_resolution,
                    band=f"{band}_diff",
                )

                # 構造物強調マップ: 差分 + コントラスト強調 (ガンマ補正)
                enhanced_grid = np.power(diff_grid, 0.5)  # ガンマ0.5で暗部を持ち上げ
                if enhanced_grid.max() > 0:
                    enhanced_grid = enhanced_grid / enhanced_grid.max()

                enhanced_maps[face] = ReflectionMap(
                    face=face,
                    width_m=fw,
                    height_m=fh,
                    grid=enhanced_grid,
                    resolution=self.grid_resolution,
                    band=f"{band}_enhanced",
                )

            # 差分・強調マップをメインのmaps辞書に追加
            for face in diff_maps:
                maps[f"{face}_diff"] = diff_maps[face]
            for face in enhanced_maps:
                maps[f"{face}_enhanced"] = enhanced_maps[face]

            logger.info(
                f"背景差分マップ・構造物強調マップ生成完了 "
                f"(diff: {len(diff_maps)}面, enhanced: {len(enhanced_maps)}面)"
            )

        except Exception as e:
            logger.warning(f"背景差分マップ生成失敗（通常マップは正常）: {e}", exc_info=True)


        except Exception as e:
            logger.warning(f"背景差分マップ生成失敗（通常マップは正常）: {e}")


            maps[face] = ReflectionMap(
                face=face,
                width_m=fw,
                height_m=fh,
                grid=grid,
                resolution=self.grid_resolution,
                band=band,
            )

        return maps

    def _extract_amplitudes(
        self, session: ScanSession, band: str
    ) -> Dict[str, List[float]]:
        """
        各計測点のCSIフレームから振幅平均値のリストを抽出。

        Returns:
            { point_id: [amp_mean_frame1, amp_mean_frame2, ...] }
        """
        point_amplitudes: Dict[str, List[float]] = {}

        for point_id, capture in session.captures.items():
            amps = []

            # ERR-B05: バンド選択 (Phase D: 160MHz対応)
            frames_to_use: List[CSIFrame] = []
            if band in ('24', 'mix') and capture.frames_24ghz:
                frames_to_use.extend(capture.frames_24ghz)
            if band in ('5', 'mix') and capture.frames_5ghz:
                frames_to_use.extend(capture.frames_5ghz)
            if band in ('160', 'mix') and capture.frames_160mhz:
                frames_to_use.extend(capture.frames_160mhz)

            for frame in frames_to_use:
                # 全サブキャリア × 全ストリームの振幅平均
                amp_mean = float(np.mean(frame.amplitude))
                amps.append(amp_mean)

            if amps:
                point_amplitudes[point_id] = amps
                logger.debug(
                    f"  {point_id}: {len(amps)} frames, "
                    f"amp_mean={np.mean(amps):.4f}, "
                    f"amp_std={np.std(amps):.4f}"
                )

        return point_amplitudes

    def _extract_baseline_amplitudes(
        self, point_amplitudes: Dict[str, List[float]]
    ) -> Dict[str, List[float]]:
        """
        背景ベースライン用の振幅を生成。

        各計測点の振幅分布から「安定成分」（=壁反射）のみを抽出する。
        壁反射は時間的に安定（分散小）、散乱体は位置依存で変動が大きい。
        
        方法: 各計測点の振幅から分散成分を除去し、中央値のみを残す。
        これにより直接波+壁反射のベースラインが得られる。

        Returns:
            { point_id: [baseline_amp, baseline_amp, ...] }  (全フレーム同値)
        """
        baseline = {}

        for point_id, amps in point_amplitudes.items():
            if not amps:
                continue

            # 中央値 = 安定成分（直接波 + 壁反射）
            median_amp = float(np.median(amps))

            # 分散の小さいフレーム（=壁反射が支配的）のみ抽出
            amp_array = np.array(amps)
            std = np.std(amp_array)

            # 中央値 ± 0.5σ 以内のフレームのみ → 安定成分
            mask = np.abs(amp_array - median_amp) < (std * 0.5 + 1e-9)
            stable_amps = amp_array[mask]

            if len(stable_amps) > 0:
                baseline_val = float(np.mean(stable_amps))
            else:
                baseline_val = median_amp

            # 全フレーム数分の同値リストとして返す（_build_face_grid互換）
            baseline[point_id] = [baseline_val] * len(amps)

            logger.debug(
                f"  ベースライン {point_id}: "
                f"median={median_amp:.4f}, baseline={baseline_val:.4f}, "
                f"stable_ratio={len(stable_amps)}/{len(amps)}"
            )

        return baseline


    def _build_face_grid(
        self, face: str, point_amplitudes: Dict[str, List[float]]
    ) -> tuple:
        """
        1面のグリッドを構築。

        各計測点の平均振幅を、計測点から面上グリッドセルへの
        距離に応じたガウシアン重みで分配する。

        Returns:
            (grid, face_width_m, face_height_m)
        """
        spec = self.FACE_SPECS[face]
        fw, fh = self._get_face_dimensions(face)
        n_cols = max(1, int(fw / self.grid_resolution))
        n_rows = max(1, int(fh / self.grid_resolution))
        grid = np.zeros((n_rows, n_cols))

        # 面上の各セルの3D座標を事前計算
        u_centers = np.linspace(
            self.grid_resolution / 2,
            fw - self.grid_resolution / 2,
            n_cols
        )
        v_centers = np.linspace(
            self.grid_resolution / 2,
            fh - self.grid_resolution / 2,
            n_rows
        )
        uu, vv = np.meshgrid(u_centers, v_centers)  # (n_rows, n_cols)
        face_xyz = self._face_uv_to_xyz(face, uu, vv)  # (n_rows, n_cols, 3)

        # ERR-B06: 各計測点からの寄与を加算
        spread_var = 2.0 * (self.spread_sigma_m ** 2)

        for point_id, amps in point_amplitudes.items():
            pos = get_measurement_position(point_id, self.room)
            pos_arr = np.array([pos.x, pos.y, pos.z])

            # 計測点から面上各セルまでの距離
            diff = face_xyz - pos_arr[np.newaxis, np.newaxis, :]
            dist_sq = np.sum(diff ** 2, axis=2)  # (n_rows, n_cols)

            # ガウシアン重み: 近いセルほど高い寄与
            weight = np.exp(-dist_sq / spread_var)

            # この計測点の代表振幅 (全フレームの平均)
            amp_representative = float(np.mean(amps))

            # フレーム間の分散も活用 (分散が大きい = 動的散乱体がある)
            amp_variance = float(np.std(amps))

            # 寄与 = 代表振幅 × 空間重み
            # 分散項を加えることで、静的な壁反射と区別しやすくする
            contribution = (amp_representative + amp_variance * 2.0) * weight
            grid += contribution

        return grid, fw, fh

    def _get_face_dimensions(self, face: str) -> tuple:
        """面の (幅m, 高さm) を返す"""
        if face in ('floor', 'ceiling'):
            return (self.room.width, self.room.depth)
        elif face in ('north', 'south'):
            return (self.room.width, self.room.height)
        elif face in ('east', 'west'):
            return (self.room.depth, self.room.height)
        # ERR-B07: 未知の面名
        raise ValueError(f"ERR-B07: Unknown face name: {face}")

    def _face_uv_to_xyz(self, face: str, uu: np.ndarray, vv: np.ndarray) -> np.ndarray:
        """
        面上の (u, v) 座標を部屋内の3D座標 (x, y, z) に変換。

        座標系:
          x: 東西 (0=西壁, width=東壁)
          y: 南北 (0=北壁, depth=南壁)
          z: 上下 (0=床, height=天井)

        面とUV軸の対応:
          floor:   u=x, v=y, z=0
          ceiling: u=x, v=y, z=height
          north:   u=x, v=z, y=0
          south:   u=x, v=z, y=depth
          west:    u=y, v=z, x=0
          east:    u=y, v=z, x=width
        """
        shape = uu.shape
        xyz = np.zeros((*shape, 3))

        if face == 'floor':
            xyz[..., 0] = uu
            xyz[..., 1] = vv
            xyz[..., 2] = 0.0
        elif face == 'ceiling':
            xyz[..., 0] = uu
            xyz[..., 1] = vv
            xyz[..., 2] = self.room.height
        elif face == 'north':
            xyz[..., 0] = uu
            xyz[..., 1] = 0.0
            xyz[..., 2] = vv
        elif face == 'south':
            xyz[..., 0] = uu
            xyz[..., 1] = self.room.depth
            xyz[..., 2] = vv
        elif face == 'west':
            xyz[..., 0] = 0.0
            xyz[..., 1] = uu
            xyz[..., 2] = vv
        elif face == 'east':
            xyz[..., 0] = self.room.width
            xyz[..., 1] = uu
            xyz[..., 2] = vv

        return xyz


    def _apply_aoa_weights(
        self,
        grid: np.ndarray,
        face: str,
        face_width: float,
        face_height: float,
        aoa_positions: List[dict],
        aoa_sigma_m: float = 0.5,
        aoa_weight: float = 3.0,
    ) -> np.ndarray:
        """
        AoA で特定された壁面位置にガウスカーネルで追加重みを配分

        AoA の信頼度が低い場合は自動的に重みが小さくなり、
        ToF のみの結果に近づく (グレースフルフォールバック)。

        Args:
            grid: 現在のグリッド shape (n_rows, n_cols)
            face: 壁面名
            face_width: 壁面幅 (m)
            face_height: 壁面高さ (m)
            aoa_positions: AoA壁面位置リスト
                [{"face": "north", "u": 2.3, "v": 1.5, "confidence": 0.65}, ...]
            aoa_sigma_m: AoAガウスカーネルの標準偏差 (m)
            aoa_weight: AoA重みの倍率

        Returns:
            更新されたグリッド

        ERR-AOA-G01: AoA重み適用
        """
        n_rows, n_cols = grid.shape

        # この面に該当するAoA位置のみフィルタ
        face_positions = [p for p in aoa_positions if p.get("face") == face]

        if not face_positions:
            return grid

        # グリッドセルの中心座標 (メートル)
        u_centers = np.linspace(
            self.grid_resolution / 2,
            face_width - self.grid_resolution / 2,
            n_cols
        )
        v_centers = np.linspace(
            self.grid_resolution / 2,
            face_height - self.grid_resolution / 2,
            n_rows
        )
        uu, vv = np.meshgrid(u_centers, v_centers)  # (n_rows, n_cols)

        aoa_sigma_sq = 2.0 * (aoa_sigma_m ** 2)

        for pos in face_positions:
            u_pos = pos.get("u", 0.0)
            v_pos = pos.get("v", 0.0)
            confidence = pos.get("confidence", 0.5)

            # 位置が壁面範囲外なら無視
            if u_pos < 0 or u_pos > face_width or v_pos < 0 or v_pos > face_height:
                continue

            # ガウスカーネル: AoA位置からの距離に基づく
            dist_sq = (uu - u_pos) ** 2 + (vv - v_pos) ** 2
            kernel = np.exp(-dist_sq / aoa_sigma_sq)

            # 信頼度 × 倍率で重み付け
            contribution = kernel * confidence * aoa_weight
            grid += contribution

        logger.debug(
            f"AoA重み適用: {face} に {len(face_positions)}点, "
            f"sigma={aoa_sigma_m}m, weight={aoa_weight}"
        )

        return grid


    def _generate_empty_maps(self, band: str) -> Dict[str, ReflectionMap]:
        """データなし時の空マップを生成"""
        maps = {}
        for face in self.FACE_SPECS:
            fw, fh = self._get_face_dimensions(face)
            n_cols = max(1, int(fw / self.grid_resolution))
            n_rows = max(1, int(fh / self.grid_resolution))
            maps[face] = ReflectionMap(
                face=face,
                width_m=fw,
                height_m=fh,
                grid=np.zeros((n_rows, n_cols)),
                resolution=self.grid_resolution,
                band=band,
            )
        return maps
