"""
RuView Scan - CSIデータモデル
(RF PROBE v2.0 CSIFrame を継承 + RuView Scan 固有のモデルを追加)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime

import numpy as np
from pydantic import BaseModel, Field


@dataclass
class CSIFrame:
    """1フレーム分のCSIデータ (RF PROBE v2.0 から継承)"""
    timestamp: float                    # Unix timestamp (秒、小数点以下μs)
    source_mac: str                     # 送信元MACアドレス
    channel: int                        # Wi-Fiチャネル番号
    bandwidth: int                      # MHz (20, 40, 80, 160)
    frequency_band: str                 # '2.4GHz', '5GHz', or '5GHz_160'
    rssi: float                         # dBm
    noise_floor: float                  # dBm
    n_subcarriers: int                  # サブキャリア数
    n_tx: int                           # TX アンテナ数
    n_rx: int                           # RX アンテナ数
    amplitude: np.ndarray               # shape: (n_subcarriers, n_tx * n_rx)
    phase: np.ndarray                   # shape: (n_subcarriers, n_tx * n_rx)

    def __post_init__(self):
        """バリデーション"""
        expected_shape = (self.n_subcarriers, self.n_tx * self.n_rx)
        if self.amplitude.shape != expected_shape:
            raise ValueError(
                f"E-CSI-004: amplitude shape不整合 "
                f"期待: {expected_shape}, 実際: {self.amplitude.shape}"
            )
        if self.phase.shape != expected_shape:
            raise ValueError(
                f"E-CSI-004: phase shape不整合 "
                f"期待: {expected_shape}, 実際: {self.phase.shape}"
            )

    @property
    def complex_csi(self) -> np.ndarray:
        """複素CSI (H = |H| * e^{jφ})"""
        return self.amplitude * np.exp(1j * self.phase)

    @property
    def total_power(self) -> float:
        """全サブキャリアの合計パワー"""
        return float(np.sum(self.amplitude ** 2))

    @property
    def mean_amplitude(self) -> np.ndarray:
        """全アンテナペアの平均振幅 shape: (n_subcarriers,)"""
        return np.mean(self.amplitude, axis=1)

    def flatten(self) -> np.ndarray:
        """全ストリームを1次元に展開"""
        return self.amplitude.flatten()


@dataclass
class DualBandCapture:
    """1計測点の2バンドデータ"""
    point_id: str           # 'north', 'east', 'south', 'west', 'center'
    point_label: str
    position: Tuple[float, float, float]  # 推定位置 (x, y, z) メートル
    frames_24ghz: List[CSIFrame] = field(default_factory=list)  # 2.4GHz フレーム
    frames_5ghz: List[CSIFrame] = field(default_factory=list)   # 5GHz フレーム
    frames_160mhz: List[CSIFrame] = field(default_factory=list)  # 5GHz 160MHz フレーム
    capture_time: Optional[datetime] = None
    duration_24: float = 0.0    # 秒
    duration_5: float = 0.0     # 秒
    duration_160: float = 0.0   # 秒

    @property
    def is_complete(self) -> bool:
        """必須2バンド(2.4GHz+5GHz)が取得済みか (160MHzはオプション)"""
        return len(self.frames_24ghz) > 0 and len(self.frames_5ghz) > 0

    @property
    def total_frames(self) -> int:
        return len(self.frames_24ghz) + len(self.frames_5ghz) + len(self.frames_160mhz)


@dataclass
class ScanSession:
    """5箇所分の計測セッション"""
    session_id: str
    room_name: str
    captures: Dict[str, DualBandCapture] = field(default_factory=dict)
    router_position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    created_at: Optional[datetime] = None

    @property
    def completed_points(self) -> List[str]:
        return [pid for pid, cap in self.captures.items() if cap.is_complete]

    @property
    def is_complete(self) -> bool:
        required = {'north', 'east', 'south', 'west', 'center'}
        return required.issubset(set(self.completed_points))

    @property
    def progress(self) -> float:
        """完了率 0.0 ~ 1.0 (必須5点 + オプション4点 = 最大9点)"""
        return len(self.completed_points) / 9.0


class ScanProgressDTO(BaseModel):
    """スキャン進捗のAPI転送用DTO"""
    point_id: str
    phase: str              # '2.4GHz' or '5GHz'
    progress: int           # 0-100
    frame_count: int
    elapsed_sec: float


class RoomResultDTO(BaseModel):
    """部屋推定結果のAPI転送用DTO"""
    width: float
    depth: float
    height: float
    area: float
    volume: float


class SessionInfoDTO(BaseModel):
    """セッション情報のAPI転送用DTO"""
    session_id: str
    room_name: str
    created_at: str
    completed_points: List[str]
    is_complete: bool
    progress: float
