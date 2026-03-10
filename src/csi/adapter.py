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
from src.utils.geo_utils import channel_to_freq

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
    """
    テスト・デモ用 物理ベース シミュレーションCSIアダプタ

    マルチパスモデル:
        H(f_k) = Σ α_n · exp(-j 2π f_k τ_n)
    ここで α_n は反射強度、τ_n = 2·d_n / c は往復遅延。
    計測点(point_id)ごとに壁までの距離が異なるため、
    ToF推定→部屋寸法推定が意味のある値を返す。
    """

    SPEED_OF_LIGHT = 299_792_458.0

    # 部屋内のシミュレーション配管/配線の位置 (x, y, z, material, radius)
    PIPE_SCATTERERS = [
        (1.0, 2.5, 0.1, 'metal', 0.15),   # 床下金属管 (東西方向)
        (5.5, 2.5, 0.1, 'metal', 0.12),
        (3.0, 1.5, 2.65, 'wire', 0.08),   # 天井裏配線
        (3.5, 3.5, 2.65, 'wire', 0.06),
        (5.5, 1.5, 1.3, 'pvc', 0.10),     # 壁内塩ビ管
    ]

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
        self.room_dims = room_dims       # (width, depth, height)
        self.point_id = point_id
        self._position = self._point_to_position(point_id)
        # ルーター位置 = 部屋中央, 床上0.8m
        self._router_pos = (room_dims[0] / 2, room_dims[1] / 2, 0.8)
        self._connected = False
        self._frame_count = 0

    def _point_to_position(self, point_id: str) -> tuple:
        """計測点IDから部屋内の絶対座標を返す"""
        w, d, h = self.room_dims
        mh = 0.75  # ノートPC高さ
        positions = {
            'north':  (w / 2, 1.0, mh),
            'east':   (w - 1.0, d / 2, mh),
            'south':  (w / 2, d - 1.0, mh),
            'west':   (1.0, d / 2, mh),
            'center': (w / 2, d / 2, mh),
        }
        return positions.get(point_id, (w / 2, d / 2, mh))

    def set_point(self, point_id: str, position: tuple = None):
        """計測点を切り替える (DualBandCollector から呼ばれる)"""
        self.point_id = point_id
        self._position = position if position else self._point_to_position(point_id)
        self._frame_count = 0
        logger.info(f"シミュレーション計測点変更: {point_id} → pos={self._position}")

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

    def _build_multipath_components(self) -> list:
        """
        計測点とルーター位置に基づくマルチパス成分を構築

        Returns:
            list of (distance_m, amplitude, label)
            distance は片道距離 (ToFはこれの2倍/c で計算)
        """
        px, py, pz = self._position
        rx, ry, rz = self._router_pos
        w, d, h = self.room_dims

        paths = []

        # 0. 直接波: PC ↔ ルーター
        d_direct = np.sqrt((px-rx)**2 + (py-ry)**2 + (pz-rz)**2)
        paths.append((d_direct, 1.0, 'direct'))

        # 1. 壁反射 (鏡像法: ルーターの鏡像からPCまでの距離)
        # 北壁 (y=0): ルーターのy鏡像 = -ry
        d_north = np.sqrt((px-rx)**2 + (py-(-ry))**2 + (pz-rz)**2)
        paths.append((d_north, 0.65, 'north_wall'))

        # 南壁 (y=d): ルーターのy鏡像 = 2d - ry
        d_south = np.sqrt((px-rx)**2 + (py-(2*d-ry))**2 + (pz-rz)**2)
        paths.append((d_south, 0.65, 'south_wall'))

        # 西壁 (x=0): ルーターのx鏡像 = -rx
        d_west = np.sqrt(((-rx)-px)**2 + (py-ry)**2 + (pz-rz)**2)
        paths.append((d_west, 0.60, 'west_wall'))

        # 東壁 (x=w): ルーターのx鏡像 = 2w - rx
        d_east = np.sqrt(((2*w-rx)-px)**2 + (py-ry)**2 + (pz-rz)**2)
        paths.append((d_east, 0.60, 'east_wall'))

        # 天井 (z=h): ルーターのz鏡像 = 2h - rz
        d_ceil = np.sqrt((px-rx)**2 + (py-ry)**2 + (pz-(2*h-rz))**2)
        paths.append((d_ceil, 0.50, 'ceiling'))

        # 床 (z=0): ルーターのz鏡像 = -rz
        d_floor = np.sqrt((px-rx)**2 + (py-ry)**2 + (pz-(-rz))**2)
        paths.append((d_floor, 0.50, 'floor'))

        # 2. 配管・配線の散乱
        for (sx, sy, sz, material, rad) in self.PIPE_SCATTERERS:
            # PC→散乱体→ルーターの往復距離
            d_pc_scat = np.sqrt((px-sx)**2 + (py-sy)**2 + (pz-sz)**2)
            d_scat_rt = np.sqrt((rx-sx)**2 + (ry-sy)**2 + (rz-sz)**2)
            d_total = d_pc_scat + d_scat_rt
            # 材質による反射強度
            amp = {'metal': 0.45, 'wire': 0.20, 'pvc': 0.15}.get(material, 0.10)
            # 距離減衰
            amp *= min(1.0, 2.0 / max(d_total, 0.5))
            paths.append((d_total, amp, f'pipe_{material}'))

        return paths

    async def read_frame(self) -> Optional[CSIFrame]:
        if not self._connected:
            return None

        await asyncio.sleep(1.0 / self.sample_rate)
        self._frame_count += 1

        n_streams = self.num_tx * self.num_rx

        # サブキャリア周波数を構築
        center_freq = channel_to_freq(self.channel)
        bw_hz = self.bandwidth * 1e6
        delta_f = bw_hz / self.num_sc
        subcarrier_freqs = (center_freq - bw_hz / 2 + delta_f / 2
                            + np.arange(self.num_sc) * delta_f)

        # マルチパス成分を取得 (計測点依存)
        paths = self._build_multipath_components()

        # H(f_k) = Σ α_n · exp(-j 2π f_k τ_n) をストリームごとに計算
        amplitude = np.zeros((self.num_sc, n_streams))
        phase = np.zeros((self.num_sc, n_streams))

        for stream in range(n_streams):
            h = np.zeros(self.num_sc, dtype=complex)
            for dist, amp, label in paths:
                tau = 2.0 * dist / self.SPEED_OF_LIGHT  # 往復遅延
                # ストリームごとの微小位相差 (アンテナ間隔)
                stream_phase = stream * 0.3
                alpha = amp * np.exp(1j * stream_phase)
                h += alpha * np.exp(-1j * 2 * np.pi * subcarrier_freqs * tau)

            # 微小ノイズ (熱雑音 + 量子化ノイズ)
            noise = (np.random.normal(0, 0.015, self.num_sc) +
                     1j * np.random.normal(0, 0.015, self.num_sc))
            h += noise

            # 時間変動 (小さなフェージング)
            h *= (1 + 0.005 * np.sin(self._frame_count * 0.01 + stream * 0.5))

            amplitude[:, stream] = np.abs(h)
            phase[:, stream] = np.angle(h)

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
            amplitude=amplitude.astype(np.float64),
            phase=phase.astype(np.float64),
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
