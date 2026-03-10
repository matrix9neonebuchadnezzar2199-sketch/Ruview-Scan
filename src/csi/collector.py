"""
RuView Scan - DualBandCollector
===============================
2.4GHz→5GHz 逐次チャネル切替によるCSI収集
"""

import asyncio
import logging
import time
from typing import Optional, Callable, Awaitable

from src.csi.models import CSIFrame, DualBandCapture
from src.csi.adapter import CSIAdapter, SimulatedAdapter
from src.csi.calibration import PhaseCalibrator
from src.errors import CSINoDataError, ScanPointError

logger = logging.getLogger(__name__)


class DualBandCollector:
    """
    1計測点で 2.4GHz(30秒) → 5GHz(30秒) を逐次収集する

    シミュレーションモードでは数秒に短縮可能。
    """

    def __init__(self,
                 adapter: CSIAdapter,
                 calibrator: PhaseCalibrator,
                 duration_per_band: float = 30.0,
                 sample_rate: float = 100.0,
                 simulate_speedup: float = 10.0):
        self.adapter = adapter
        self.calibrator = calibrator
        self.duration_per_band = duration_per_band
        self.sample_rate = sample_rate
        self.simulate_speedup = simulate_speedup
        self._is_simulated = isinstance(adapter, SimulatedAdapter)

    async def collect(
        self,
        point_id: str,
        point_label: str,
        position: tuple,
        progress_callback: Optional[Callable] = None
    ) -> DualBandCapture:
        """
        1計測点の2バンドCSIを収集

        Parameters:
            point_id: 'north', 'east', 'south', 'west', 'center'
            point_label: UI表示用ラベル
            position: (x, y, z) 位置
            progress_callback: async def callback(point_id, phase, progress, frame_count, elapsed)
        Returns:
            DualBandCapture
        """
        import datetime
        capture = DualBandCapture(
            point_id=point_id,
            point_label=point_label,
            position=position,
            capture_time=datetime.datetime.now()
        )

        # === 2.4GHz Phase ===
        logger.info(f"[{point_id}] 2.4GHz CSI取得開始")
        if self._is_simulated:
            self.adapter.set_point(point_id, position)
            self.adapter.configure(channel=1, bandwidth=40, num_subcarriers=114)

        capture.frames_24ghz = await self._collect_band(
            band='2.4GHz',
            point_id=point_id,
            progress_callback=progress_callback
        )
        capture.duration_24 = self.duration_per_band
        logger.info(f"[{point_id}] 2.4GHz完了: {len(capture.frames_24ghz)}フレーム")

        # === 5GHz Phase ===
        logger.info(f"[{point_id}] 5GHz CSI取得開始")
        if self._is_simulated:
            self.adapter.configure(channel=36, bandwidth=80, num_subcarriers=234)

        capture.frames_5ghz = await self._collect_band(
            band='5GHz',
            point_id=point_id,
            progress_callback=progress_callback
        )
        capture.duration_5 = self.duration_per_band
        logger.info(f"[{point_id}] 5GHz完了: {len(capture.frames_5ghz)}フレーム")

        return capture

    async def _collect_band(
        self,
        band: str,
        point_id: str,
        progress_callback: Optional[Callable] = None
    ) -> list:
        """1バンド分のフレーム収集"""
        frames = []
        duration = self.duration_per_band
        if self._is_simulated:
            duration = self.duration_per_band / self.simulate_speedup

        start_time = time.time()
        # ⑥修正: target_frames もスピードアップを考慮
        target_frames = int(duration * self.sample_rate)

        try:
            async for frame in self.adapter.stream(timeout=duration + 5):
                elapsed = time.time() - start_time

                # キャリブレーション適用
                calibrated = self.calibrator.calibrate(frame)
                frames.append(calibrated)

                # 進捗報告
                progress = min(100, int((elapsed / duration) * 100))
                if progress_callback:
                    await progress_callback(
                        point_id, band, progress,
                        len(frames), elapsed
                    )

                # 時間経過で終了
                if elapsed >= duration:
                    break

                # 十分なフレーム数で終了
                if len(frames) >= target_frames:
                    break

        except CSINoDataError:
            if len(frames) == 0:
                raise ScanPointError(
                    point_id,
                    f"{band}帯のCSIデータが1フレームも取得できませんでした"
                )
            logger.warning(
                f"[{point_id}] {band}: タイムアウトで終了 "
                f"({len(frames)}/{target_frames}フレーム)"
            )

        # 完了通知
        if progress_callback:
            await progress_callback(
                point_id, band, 100,
                len(frames), time.time() - start_time
            )

        return frames
