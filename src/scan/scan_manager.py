"""
RuView Scan - 5箇所計測セッション管理
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, Callable

from src.csi.models import DualBandCapture, ScanSession
from src.csi.collector import DualBandCollector
from src.errors import ScanSessionError, ScanAlreadyRunningError, ScanPointError

logger = logging.getLogger(__name__)

POINT_IDS = ['north', 'east', 'south', 'west', 'center']
POINT_LABELS = {
    'north': '① 北壁側 (pos.1)',
    'east': '② 東壁側 (pos.2)',
    'south': '③ 南壁側 (pos.3)',
    'west': '④ 西壁側 (pos.4)',
    'center': '⑤ 中心 (pos.5)',
}


class ScanManager:
    """5箇所の逐次計測セッションを管理"""

    def __init__(self, collector: DualBandCollector):
        self.collector = collector
        self.current_session: Optional[ScanSession] = None
        self._scanning_point: Optional[str] = None
        self._scan_task: Optional[asyncio.Task] = None

    def create_session(self, room_name: str = "untitled") -> ScanSession:
        """新規セッション作成"""
        session = ScanSession(
            session_id=str(uuid.uuid4())[:8],
            room_name=room_name,
            created_at=datetime.now()
        )
        self.current_session = session
        logger.info(f"新規セッション作成: {session.session_id}")
        return session

    @property
    def is_scanning(self) -> bool:
        return self._scanning_point is not None

    def get_status(self) -> dict:
        """現在の状態を返す"""
        if self.current_session is None:
            return {
                'session': None,
                'scanning': False,
                'scanning_point': None,
                'completed': [],
                'remaining': POINT_IDS.copy(),
            }

        return {
            'session': self.current_session.session_id,
            'scanning': self.is_scanning,
            'scanning_point': self._scanning_point,
            'completed': self.current_session.completed_points,
            'remaining': [
                p for p in POINT_IDS
                if p not in self.current_session.completed_points
            ],
            'progress': self.current_session.progress,
        }

    async def start_point_scan(
        self,
        point_id: str,
        progress_callback: Optional[Callable] = None
    ) -> DualBandCapture:
        """
        1計測点のスキャンを開始

        Parameters:
            point_id: 'north', 'east', 'south', 'west', 'center'
            progress_callback: WebSocket進捗通知用コールバック
        Returns:
            DualBandCapture
        """
        if point_id not in POINT_IDS:
            raise ScanPointError(point_id, f"無効な計測点ID: {point_id}")

        if self.is_scanning:
            raise ScanAlreadyRunningError()

        if self.current_session is None:
            self.create_session()

        self._scanning_point = point_id
        label = POINT_LABELS.get(point_id, point_id)

        # 仮の位置 (推定前なので概算)
        position = self._get_approximate_position(point_id)

        try:
            logger.info(f"計測開始: {label}")
            capture = await self.collector.collect(
                point_id=point_id,
                point_label=label,
                position=position,
                progress_callback=progress_callback,
            )

            self.current_session.captures[point_id] = capture
            logger.info(
                f"計測完了: {label} "
                f"(2.4GHz:{len(capture.frames_24ghz)}fr, "
                f"5GHz:{len(capture.frames_5ghz)}fr)"
            )

            return capture

        except Exception as e:
            logger.error(f"計測エラー ({label}): {e}")
            raise
        finally:
            self._scanning_point = None

    def _get_approximate_position(self, point_id: str) -> tuple:
        """計測点の概算位置 (推定前の仮位置)"""
        # 仮の部屋サイズで概算
        w, d = 5.0, 4.0
        h = 0.75  # ノートPC高さ
        positions = {
            'north': (w / 2, 1.0, h),
            'east': (w - 1.0, d / 2, h),
            'south': (w / 2, d - 1.0, h),
            'west': (1.0, d / 2, h),
            'center': (w / 2, d / 2, h),
        }
        return positions.get(point_id, (w / 2, d / 2, h))

    def reset(self):
        """セッションをリセット"""
        if self.is_scanning:
            if self._scan_task and not self._scan_task.done():
                self._scan_task.cancel()
            self._scanning_point = None

        self.current_session = None
        logger.info("セッションリセット")
