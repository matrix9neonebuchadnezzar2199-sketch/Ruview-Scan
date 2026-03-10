"""
RuView Scan - CSI入力アダプタ
================================
PicoScenes, シミュレーションの各ソースからCSIを統一形式で取得する
(RF PROBE v2.0 から継承)
"""

import asyncio
import json
import logging
import socket
import struct
import time
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional

import numpy as np

from src.csi.models import CSIFrame
from src.errors import CSISourceError, CSIParseError, CSINoDataError

logger = logging.getLogger(__name__)


class CSIAdapter(ABC):
    """CSI入力アダプタの基底クラス"""

    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    @abstractmethod
    async def read_frame(self) -> Optional[CSIFrame]:
        pass

    async def stream(self, timeout: float = 5.0) -> AsyncGenerator[CSIFrame, None]:
        """CSIフレームのストリーミング"""
        no_data_since = time.time()

        while True:
            try:
                frame = await asyncio.wait_for(
                    self.read_frame(),
                    timeout=timeout
                )
                if frame is not None:
                    no_data_since = time.time()
                    yield frame
                else:
                    elapsed = time.time() - no_data_since
                    if elapsed > timeout:
                        raise CSINoDataError(timeout_sec=elapsed)
                    await asyncio.sleep(0.001)

            except asyncio.TimeoutError:
                raise CSINoDataError(timeout_sec=timeout)
            except (CSISourceError, CSIParseError, CSINoDataError):
                raise
            except Exception as e:
                logger.error(f"CSI読み取りエラー: {type(e).__name__}: {e}")
                raise CSISourceError(
                    source=self.__class__.__name__,
                    detail=str(e)
                )


class PicoScenesAdapter(CSIAdapter):
    """PicoScenes UDP転送からCSIを受信するアダプタ"""

    def __init__(self, udp_port: int = 5500, bind_addr: str = "0.0.0.0"):
        self.udp_port = udp_port
        self.bind_addr = bind_addr
        self.sock: Optional[socket.socket] = None
        self._connected = False

    async def connect(self) -> None:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self.bind_addr, self.udp_port))
            self.sock.setblocking(False)
            self._connected = True
            logger.info(f"PicoScenes UDPリスナー起動: {self.bind_addr}:{self.udp_port}")
        except OSError as e:
            raise CSISourceError(
                source="PicoScenes",
                detail=f"UDPバインド失敗 ({self.bind_addr}:{self.udp_port}): {e}"
            )

    async def disconnect(self) -> None:
        if self.sock:
            self.sock.close()
            self._connected = False
            logger.info("PicoScenes UDPリスナー停止")

    async def read_frame(self) -> Optional[CSIFrame]:
        if not self._connected or not self.sock:
            raise CSISourceError("PicoScenes", "未接続状態です")

        loop = asyncio.get_event_loop()
        try:
            data, addr = await loop.sock_recvfrom(self.sock, 65535)
            return self._parse_picoscenes_packet(data)
        except BlockingIOError:
            return None
        except Exception as e:
            raise CSIParseError(f"PicoScenesパケット処理失敗: {e}")

    def _parse_picoscenes_packet(self, data: bytes) -> CSIFrame:
        """PicoScenesのUDP転送パケットをパース"""
        try:
            if len(data) < 20:
                raise CSIParseError(f"パケットサイズ不足: {len(data)} bytes")

            if data[0:1] == b'{':
                return self._parse_json_packet(data)

            raise CSIParseError(
                "バイナリパケットの解析は未実装です。"
                "PicoScenesのUDP ForwarderをJSONモードで起動してください"
            )
        except (json.JSONDecodeError, struct.error, KeyError, IndexError) as e:
            raise CSIParseError(f"パケットパース失敗: {type(e).__name__}: {e}")

    def _parse_json_packet(self, data: bytes) -> CSIFrame:
        """JSON形式のCSIパケットをパース"""
        obj = json.loads(data)

        num_sc = obj.get("numSubcarriers", 0)
        num_tx = obj.get("numTx", 1)
        num_rx = obj.get("numRx", 1)
        channel = obj.get("channel", 0)

        if num_sc == 0:
            raise CSIParseError("サブキャリア数が0です")

        csi_raw = obj.get("csi", [])
        if not csi_raw:
            raise CSIParseError("CSIデータが空です")

        try:
            csi_array = np.array(csi_raw, dtype=np.complex128)
            csi_array = csi_array.reshape(num_sc, num_tx * num_rx)
        except (ValueError, TypeError) as e:
            raise CSIParseError(f"CSI配列再構成失敗: {e}")

        # 周波数帯を判定
        freq_band = '2.4GHz' if channel <= 14 else '5GHz'

        return CSIFrame(
            timestamp=obj.get("timestamp", time.time()),
            source_mac=obj.get("sourceMac", "unknown"),
            channel=channel,
            bandwidth=obj.get("bandwidth", 20),
            frequency_band=freq_band,
            rssi=obj.get("rssi", -99.0),
            noise_floor=obj.get("noiseFloor", -95.0),
            n_subcarriers=num_sc,
            n_tx=num_tx,
            n_rx=num_rx,
            amplitude=np.abs(csi_array),
            phase=np.angle(csi_array),
        )


class SimulatedAdapter(CSIAdapter):
    """テスト・デモ用シミュレーションCSIアダプタ"""

    def __init__(self, channel: int = 36, bandwidth: int = 80,
                 num_subcarriers: int = 234, num_tx: int = 2,
                 num_rx: int = 2, sample_rate: float = 100.0,
                 room_dims: tuple = (7.2, 5.4, 2.7),
                 point_id: str = 'center'):
        self.channel = channel
        self.bandwidth = bandwidth
        self.num_sc = num_subcarriers
        self.num_tx = num_tx
        self.num_rx = num_rx
        self.sample_rate = sample_rate
        self.room_dims = room_dims
        self.point_id = point_id
        self._connected = False
        self._frame_count = 0

    async def connect(self) -> None:
        self._connected = True
        self._frame_count = 0
        freq_band = '2.4GHz' if self.channel <= 14 else '5GHz'
        logger.info(
            f"シミュレーションCSI起動: "
            f"{freq_band} ch{self.channel} {self.bandwidth}MHz "
            f"{self.num_sc}sc × {self.num_tx}tx × {self.num_rx}rx @ {self.sample_rate}Hz"
        )

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("シミュレーションCSI停止")

    def configure(self, channel: int, bandwidth: int, num_subcarriers: int):
        """チャネル・帯域幅・サブキャリア数を動的に変更"""
        self.channel = channel
        self.bandwidth = bandwidth
        self.num_sc = num_subcarriers
        self._frame_count = 0

    async def read_frame(self) -> Optional[CSIFrame]:
        if not self._connected:
            return None

        await asyncio.sleep(1.0 / self.sample_rate)
        self._frame_count += 1

        n_streams = self.num_tx * self.num_rx

        # ベース信号: マルチパス伝搬をシミュレーション
        # 直接波 + 壁反射(4面) + 天井/床反射
        base_amp = np.ones((self.num_sc, n_streams)) * 0.8

        # 周波数依存のフェージング
        freq_idx = np.arange(self.num_sc)
        for stream in range(n_streams):
            # 壁反射による周期的パターン
            base_amp[:, stream] += 0.15 * np.sin(freq_idx * 0.2 + stream * 0.5)
            base_amp[:, stream] += 0.08 * np.cos(freq_idx * 0.05 + self._frame_count * 0.001)

        # 配管・配線による局所的反射
        pipe_positions = [0.2, 0.45, 0.7]  # 正規化位置
        for pos in pipe_positions:
            center = int(pos * self.num_sc)
            width = max(3, self.num_sc // 30)
            start = max(0, center - width)
            end = min(self.num_sc, center + width)
            intensity = 0.3 + 0.05 * np.sin(self._frame_count * 0.01)
            base_amp[start:end, :] += intensity

        # ノイズ
        base_amp += np.random.normal(0, 0.02, (self.num_sc, n_streams))
        base_amp = np.clip(base_amp, 0.01, 5.0)

        # 位相: 距離に対応する線形位相 + ノイズ
        base_phase = np.zeros((self.num_sc, n_streams))
        for stream in range(n_streams):
            base_phase[:, stream] = (
                -2 * np.pi * freq_idx * 0.01  # 直接波の位相勾配
                + 0.3 * np.sin(freq_idx * 0.15)  # 反射波
                + np.random.normal(0, 0.1, self.num_sc)
            )

        freq_band = '2.4GHz' if self.channel <= 14 else '5GHz'

        return CSIFrame(
            timestamp=time.time(),
            source_mac="AA:BB:CC:DD:EE:FF",
            channel=self.channel,
            bandwidth=self.bandwidth,
            frequency_band=freq_band,
            rssi=-45.0 + np.random.normal(0, 1),
            noise_floor=-95.0,
            n_subcarriers=self.num_sc,
            n_tx=self.num_tx,
            n_rx=self.num_rx,
            amplitude=base_amp.astype(np.float64),
            phase=base_phase.astype(np.float64),
        )


def create_adapter(source: str, config: dict) -> CSIAdapter:
    """設定に基づきCSIアダプタを生成するファクトリ"""
    if source == "picoscenes":
        return PicoScenesAdapter(
            udp_port=config.get("udp_port", 5500)
        )
    elif source == "simulate":
        return SimulatedAdapter(
            sample_rate=config.get("sample_rate", 100)
        )
    else:
        raise CSISourceError(
            source=source,
            detail=f"未知のCSIソース: '{source}' (対応: picoscenes, simulate)"
        )
