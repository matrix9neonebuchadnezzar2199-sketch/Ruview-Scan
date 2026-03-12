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
        bandwidth = obj.get('bandwidth', 20)
        if channel <= 14:
            freq_band = '2.4GHz'
        elif bandwidth >= 160:
            freq_band = '5GHz_160'
        else:
            freq_band = '5GHz'

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
            # Phase D: 4隅の追加測定点
            'northeast': (w - 1.0, 1.0, mh),
            'southeast': (w - 1.0, d - 1.0, mh),
            'southwest': (1.0, d - 1.0, mh),
            'northwest': (1.0, 1.0, mh),
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
        if self.channel <= 14:
            freq_band = '2.4GHz'
        elif self.bandwidth >= 160:
            freq_band = '5GHz_160'
        else:
            freq_band = '5GHz'
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

        if self.channel <= 14:
            freq_band = '2.4GHz'
        elif self.bandwidth >= 160:
            freq_band = '5GHz_160'
        else:
            freq_band = '5GHz'

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


# ============================================================
# FeitCSI Adapter (F-0j で追加)
# ============================================================

class FeitCSIAdapter(CSIAdapter):
    """
    FeitCSI UDP Bridge 経由で CSI を取得するアダプタ
    FeitCSI デーモン (port 8008) と UDP で通信し、リアルタイム CSI を受信する
    """

    def __init__(self, config: dict):
        self.host = config.get("feitcsi_host", "127.0.0.1")
        self.port = config.get("feitcsi_port", 8008)
        self.frequency = config.get("frequency", 5180)
        self.bandwidth = config.get("bandwidth", 160)
        self.format = config.get("format", "HESU")
        self.mode = config.get("mode", "measure")
        self.antenna = config.get("antenna", "12")
        self.tx_power = config.get("tx_power", 10)
        self.output_file = config.get("output_file", "/tmp/ruview_csi.dat")

        self._sock: Optional[socket.socket] = None
        self._connected = False
        self._recv_buffer = bytearray()
        self._frame_count = 0
        self._last_frame_time = 0.0

        # FeitCSI ヘッダサイズ (固定 272 bytes)
        self.HEADER_SIZE = 272

    async def connect(self) -> None:
        """FeitCSI UDP デーモンに接続し、測定コマンドを送信"""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(5.0)
            self._sock.setblocking(False)

            # 測定開始コマンドを構築
            cmd = self._build_command()
            logger.info(f"FeitCSI 接続: {self.host}:{self.port}")
            logger.info(f"FeitCSI コマンド: {cmd}")

            # コマンド送信
            self._sock.sendto(
                cmd.encode('utf-8'),
                (self.host, self.port)
            )
            self._connected = True
            logger.info("FeitCSI 測定開始コマンド送信完了")

        except Exception as e:
            raise CSISourceError(f"FeitCSI 接続失敗: {e}")

    async def disconnect(self) -> None:
        """FeitCSI 測定を停止し、ソケットを閉じる"""
        if self._sock:
            try:
                # stop コマンド送信
                self._sock.sendto(
                    b"stop",
                    (self.host, self.port)
                )
                logger.info("FeitCSI 停止コマンド送信")
            except Exception:
                pass
            finally:
                self._sock.close()
                self._sock = None
                self._connected = False
                logger.info("FeitCSI 切断完了")

    async def read_frame(self) -> CSIFrame:
        """
        FeitCSI から 1 フレーム分の CSI データを読み取る
        FeitCSI バイナリフォーマット: 272-byte header + CSI data
        """
        if not self._connected or not self._sock:
            raise CSISourceError("FeitCSI 未接続")

        try:
            # 非同期でデータ受信を待つ
            loop = asyncio.get_event_loop()
            data = await asyncio.wait_for(
                loop.sock_recv(self._sock, 65536),
                timeout=5.0
            )

            if not data:
                raise CSINoDataError("FeitCSI からデータなし")

            self._recv_buffer.extend(data)

            # バッファからフレームを抽出
            frame = self._parse_buffer()
            if frame is None:
                raise CSINoDataError("完全なフレームがまだ揃っていません")

            self._frame_count += 1
            self._last_frame_time = time.time()
            return frame

        except asyncio.TimeoutError:
            raise CSINoDataError("FeitCSI 受信タイムアウト (5s)")
        except (CSISourceError, CSINoDataError):
            raise
        except Exception as e:
            raise CSIParseError(f"FeitCSI フレーム読み取りエラー: {e}")

    def _build_command(self) -> str:
        """FeitCSI コマンド文字列を構築"""
        parts = [
            "feitcsi",
            f"-f {self.frequency}",
            f"-w {self.bandwidth}",
            f"-r {self.format}",
            f"-i {self.mode}",
            f"-a {self.antenna}",
            f"-t {self.tx_power}",
            f"-o {self.output_file}",
        ]
        return " ".join(parts)

    def _parse_buffer(self) -> Optional[CSIFrame]:
        """
        受信バッファから FeitCSI フレームを 1 つパースする
        Header: 272 bytes (固定)
          bytes 0-3:   CSI データサイズ (uint32)
          bytes 12-19: タイムスタンプ (uint64, μs)
          bytes 46:    RX アンテナ数 (uint8)
          bytes 47:    TX アンテナ数 (uint8)
          bytes 52-55: サブキャリア数 (uint32)
          bytes 60-63: RSSI TX1 (int32)
          bytes 64-67: RSSI TX2 (int32)
          bytes 68-73: ソース MAC (6 bytes)
        CSI Data: 4 × RX × TX × subcarriers bytes
          各エントリ: int16 real + int16 imag
        """
        min_size = self.HEADER_SIZE + 4  # ヘッダ + 最小 CSI
        if len(self._recv_buffer) < min_size:
            return None

        # CSI データサイズを読み取り
        csi_data_size = struct.unpack_from('<I', self._recv_buffer, 0)[0]
        total_frame_size = self.HEADER_SIZE + csi_data_size

        if len(self._recv_buffer) < total_frame_size:
            return None

        # ヘッダ解析
        header = bytes(self._recv_buffer[:self.HEADER_SIZE])
        timestamp_us = struct.unpack_from('<Q', header, 12)[0]
        n_rx = header[46]
        n_tx = header[47]
        n_subcarriers = struct.unpack_from('<I', header, 52)[0]
        rssi_1 = struct.unpack_from('<i', header, 60)[0]
        rssi_2 = struct.unpack_from('<i', header, 64)[0]
        source_mac = ':'.join(f'{b:02x}' for b in header[68:74])

        # RSSI: 2 アンテナの平均 (dBm)
        if rssi_2 != 0:
            rssi = (rssi_1 + rssi_2) / 2.0
        else:
            rssi = float(rssi_1)

        # CSI データ解析
        csi_raw = bytes(self._recv_buffer[self.HEADER_SIZE:total_frame_size])

        expected_size = 4 * n_rx * n_tx * n_subcarriers
        if csi_data_size < expected_size:
            logger.warning(
                f"CSI データサイズ不整合: {csi_data_size} < {expected_size} "
                f"(RX={n_rx}, TX={n_tx}, SC={n_subcarriers})"
            )
            # バッファを進める
            self._recv_buffer = self._recv_buffer[total_frame_size:]
            return None

        # int16 配列として解釈 → complex に変換
        iq_array = np.frombuffer(csi_raw[:expected_size], dtype=np.int16)
        iq_complex = iq_array[0::2] + 1j * iq_array[1::2]

        # shape: (n_rx, n_tx, n_subcarriers)
        try:
            csi_matrix = iq_complex.reshape(n_rx, n_tx, n_subcarriers)
        except ValueError:
            logger.warning(f"CSI reshape 失敗: {iq_complex.shape} → ({n_rx},{n_tx},{n_subcarriers})")
            self._recv_buffer = self._recv_buffer[total_frame_size:]
            return None

        # バッファを消費
        self._recv_buffer = self._recv_buffer[total_frame_size:]

        # 振幅・位相
        amplitude = np.abs(csi_matrix).flatten().tolist()
        phase = np.angle(csi_matrix).flatten().tolist()

        # サブキャリア周波数 (中心周波数 ± 帯域幅/2)
        center_freq = self.frequency * 1e6
        bw_hz = self.bandwidth * 1e6
        subcarrier_spacing = bw_hz / n_subcarriers
        subcarrier_freqs = [
            center_freq - bw_hz / 2 + subcarrier_spacing * (i + 0.5)
            for i in range(n_subcarriers)
        ]

        # CSIFrame 生成
        frame = CSIFrame(
            timestamp=timestamp_us / 1e6,  # μs → s
            subcarrier_freqs=subcarrier_freqs,
            amplitude=amplitude,
            phase=phase,
            rssi=rssi,
            noise_floor=-90.0,  # FeitCSI ヘッダに noise floor なし → デフォルト
            metadata={
                "source": "feitcsi",
                "source_mac": source_mac,
                "n_rx": n_rx,
                "n_tx": n_tx,
                "n_subcarriers": n_subcarriers,
                "rssi_tx1": rssi_1,
                "rssi_tx2": rssi_2,
                "frequency_mhz": self.frequency,
                "bandwidth_mhz": self.bandwidth,
                "format": self.format,
                "frame_index": self._frame_count,
            },
        )
        return frame

    def get_stats(self) -> dict:
        """FeitCSI アダプタの統計情報"""
        return {
            "adapter": "feitcsi",
            "connected": self._connected,
            "frame_count": self._frame_count,
            "last_frame_time": self._last_frame_time,
            "frequency": self.frequency,
            "bandwidth": self.bandwidth,
            "format": self.format,
            "buffer_size": len(self._recv_buffer),
        }


# ============================================================
# ファクトリ関数 (改修版)
# ============================================================

def create_adapter(config: Optional[dict] = None) -> CSIAdapter:
    """
    設定に基づいて適切な CSI アダプタを生成するファクトリ関数

    config["csi_source"]:
        "feitcsi"    → FeitCSIAdapter (推奨・デフォルト)
        "picoscenes" → PicoScenesAdapter (レガシー)
        "simulate"   → SimulatedCSIAdapter
    """
    import os

    if config is None:
        config = {}

    # 環境変数によるオーバーライド
    source = os.environ.get(
        'RUVIEW_CSI_SOURCE',
        config.get('csi_source', 'feitcsi')
    )

    logger.info(f"CSI ソース選択: {source}")

    if source == "feitcsi":
        return FeitCSIAdapter(config)
    elif source == "picoscenes":
        return PicoScenesAdapter(config)
    elif source == "simulate":
        return _create_simulated(config)
    else:
        logger.warning(f"不明な CSI ソース '{source}' → シミュレーションにフォールバック")
        return _create_simulated(config)


def _create_simulated(config: dict) -> SimulatedAdapter:
    """config dict から SimulatedAdapter の個別引数を展開して生成"""
    return SimulatedAdapter(
        channel=config.get("channel", 36),
        bandwidth=config.get("bandwidth", 80),
        num_subcarriers=config.get("num_subcarriers", 234),
        num_tx=config.get("num_tx", 2),
        num_rx=config.get("num_rx", 2),
        sample_rate=config.get("sample_rate", 100.0),
        room_dims=tuple(config.get("room_dims", (7.2, 5.4, 2.7))),
        point_id=config.get("point_id", "center"),
    )