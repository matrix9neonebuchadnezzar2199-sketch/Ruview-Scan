"""
RuView Scan - AoA推定 動作検証スクリプト
=========================================
SimulatedAdapter でCSIを生成し、AoAEstimator の各機能を検証する。
Phase F-1h: サブキャリアスムージング・2D MUSIC・マルチバンド融合・壁面マッピングの統合テスト

実行: python tests/test_aoa.py
"""

import asyncio
import sys
import os
import numpy as np

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.csi.adapter import SimulatedAdapter
from src.scan.aoa_estimator import AoAEstimator, AoAEstimate
from src.utils.geo_utils import RoomDimensions


# テスト用の部屋寸法
ROOM = RoomDimensions(width=7.2, depth=5.4, height=2.7)
ROOM_TUPLE = (7.2, 5.4, 2.7)


async def collect_frames(adapter: SimulatedAdapter, n_frames: int = 50):
    """アダプタからフレームを収集"""
    await adapter.connect()
    frames = []
    for _ in range(n_frames):
        frame = await adapter.read_frame()
        if frame:
            frames.append(frame)
    await adapter.disconnect()
    return frames


def test_subcarrier_smoothing():
    """F-1a: サブキャリアスムージングMUSIC"""
    print("\n" + "=" * 60)
    print("TEST 1: サブキャリアスムージング MUSIC")
    print("=" * 60)

    estimator = AoAEstimator(smoothing_window=20)

    for point_id in ['north', 'east', 'south', 'west', 'center']:
        adapter = SimulatedAdapter(
            channel=36, bandwidth=160, num_subcarriers=468,
            num_tx=2, num_rx=2, sample_rate=1000.0,
            room_dims=ROOM_TUPLE, point_id=point_id,
        )
        frames = asyncio.run(collect_frames(adapter, 50))

        aoas = estimator.estimate_aoa(frames)

        print(f"\n  計測点: {point_id}")
        print(f"  フレーム数: {len(frames)}")
        for i, a in enumerate(aoas):
            print(
                f"    パス{i+1}: 方位角={np.degrees(a.azimuth):+7.1f}°, "
                f"パワー={a.power:.3f}, 信頼度={a.confidence:.2f}"
            )

    print("\n  [OK] サブキャリアスムージング MUSIC 完了")


def test_2d_music():
    """F-1c: 2D MUSIC (方位角 + 仰角)"""
    print("\n" + "=" * 60)
    print("TEST 2: 2D MUSIC (方位角 + 仰角)")
    print("=" * 60)

    estimator = AoAEstimator(smoothing_window=15)

    adapter = SimulatedAdapter(
        channel=36, bandwidth=160, num_subcarriers=468,
        num_tx=2, num_rx=2, sample_rate=1000.0,
        room_dims=ROOM_TUPLE, point_id='center',
    )
    frames = asyncio.run(collect_frames(adapter, 50))

    aoas = estimator.estimate_aoa_2d(frames, az_points=91, el_points=45)

    print(f"\n  計測点: center")
    print(f"  フレーム数: {len(frames)}")
    for i, a in enumerate(aoas):
        print(
            f"    パス{i+1}: 方位角={np.degrees(a.azimuth):+7.1f}°, "
            f"仰角={np.degrees(a.elevation):+6.1f}°, "
            f"パワー={a.power:.3f}, 信頼度={a.confidence:.2f}"
        )

    print("\n  [OK] 2D MUSIC 完了")


def test_multiband_fusion():
    """F-1d: マルチバンド AoA 融合"""
    print("\n" + "=" * 60)
    print("TEST 3: マルチバンド AoA 融合")
    print("=" * 60)

    estimator = AoAEstimator()

    # 3バンドのフレームを生成
    band_configs = {
        '2.4GHz':   {'channel': 1,  'bandwidth': 40,  'num_subcarriers': 114},
        '5GHz':     {'channel': 36, 'bandwidth': 80,  'num_subcarriers': 234},
        '5GHz_160': {'channel': 36, 'bandwidth': 160, 'num_subcarriers': 468},
    }

    band_frames = {}
    for band_key, cfg in band_configs.items():
        adapter = SimulatedAdapter(
            channel=cfg['channel'],
            bandwidth=cfg['bandwidth'],
            num_subcarriers=cfg['num_subcarriers'],
            num_tx=2, num_rx=2, sample_rate=1000.0,
            room_dims=ROOM_TUPLE, point_id='north',
        )
        band_frames[band_key] = asyncio.run(collect_frames(adapter, 30))
        print(f"  {band_key}: {len(band_frames[band_key])} frames")

    fused = estimator.estimate_aoa_multiband(band_frames)

    print(f"\n  融合結果:")
    for i, a in enumerate(fused):
        print(
            f"    パス{i+1}: 方位角={np.degrees(a.azimuth):+7.1f}°, "
            f"パワー={a.power:.3f}, 信頼度={a.confidence:.2f}"
        )

    print("\n  [OK] マルチバンド融合 完了")


def test_wall_mapping():
    """F-1e: AoA → 壁面位置マッピング"""
    print("\n" + "=" * 60)
    print("TEST 4: AoA → 壁面位置マッピング")
    print("=" * 60)

    estimator = AoAEstimator(smoothing_window=20)

    for point_id in ['north', 'east', 'south', 'west']:
        adapter = SimulatedAdapter(
            channel=36, bandwidth=160, num_subcarriers=468,
            num_tx=2, num_rx=2, sample_rate=1000.0,
            room_dims=ROOM_TUPLE, point_id=point_id,
        )
        frames = asyncio.run(collect_frames(adapter, 50))

        aoas = estimator.estimate_aoa(frames)

        # ToF距離のダミー (各パスに2~5mのランダム距離を割り当て)
        tof_dists = [np.random.uniform(2.0, 5.0) for _ in aoas]

        positions = estimator.batch_aoa_to_wall(
            aoas, tof_dists, point_id, ROOM
        )

        print(f"\n  計測点: {point_id}")
        for p in positions:
            print(
                f"    → {p['face']}: u={p['u']:.2f}m, v={p['v']:.2f}m, "
                f"az={p['azimuth_deg']:+.1f}°, conf={p['confidence']:.2f}"
            )

    print("\n  [OK] 壁面マッピング 完了")


def test_confidence():
    """F-1f: 信頼度評価"""
    print("\n" + "=" * 60)
    print("TEST 5: 信頼度評価 (スムージング有無の比較)")
    print("=" * 60)

    adapter_160 = SimulatedAdapter(
        channel=36, bandwidth=160, num_subcarriers=468,
        num_tx=2, num_rx=2, sample_rate=1000.0,
        room_dims=ROOM_TUPLE, point_id='center',
    )
    frames_160 = asyncio.run(collect_frames(adapter_160, 50))

    # スムージングあり
    est_smooth = AoAEstimator(smoothing_window=20)
    aoas_smooth = est_smooth.estimate_aoa(frames_160)

    # スムージングなし (ウィンドウ=1 → フォールバック)
    est_legacy = AoAEstimator(smoothing_window=1)
    aoas_legacy = est_legacy.estimate_aoa(frames_160)

    print(f"\n  スムージングあり (window=20):")
    for a in aoas_smooth[:3]:
        print(f"    az={np.degrees(a.azimuth):+7.1f}°, conf={a.confidence:.2f}")

    print(f"\n  スムージングなし (従来):")
    for a in aoas_legacy[:3]:
        print(f"    az={np.degrees(a.azimuth):+7.1f}°, conf={a.confidence:.2f}")

    if aoas_smooth and aoas_legacy:
        smooth_conf = max(a.confidence for a in aoas_smooth)
        legacy_conf = max(a.confidence for a in aoas_legacy)
        print(f"\n  最大信頼度: スムージング={smooth_conf:.2f}, 従来={legacy_conf:.2f}")
        if smooth_conf > legacy_conf:
            print("  → スムージングにより信頼度が向上 ✓")

    print("\n  [OK] 信頼度評価 完了")


if __name__ == '__main__':
    print("=" * 60)
    print("  RuView Scan - AoA推定 統合テスト (Phase F-1)")
    print("=" * 60)

    test_subcarrier_smoothing()
    test_2d_music()
    test_multiband_fusion()
    test_wall_mapping()
    test_confidence()

    print("\n" + "=" * 60)
    print("  全テスト完了")
    print("=" * 60)
