"""
RuView Scan - FeitCSI UDP Bridge
FeitCSI の UDP ソケットインターフェース (port 8008) と通信し、
CSI測定の制御とデータ受信を行うブリッジモジュール

プロトコル:
  送信: コマンド文字列をUDPで送信
  受信: 272バイトヘッダー + CSIデータ（バイナリ）
"""
# ERR-F008: feitcsi_bridge.py - FeitCSI UDP通信ブリッジ

import socket
import struct
import time
import threading
from dataclasses import dataclass
from typing import Optional, Callable, List
from queue import Queue, Full


FEITCSI_HOST = "127.0.0.1"
FEITCSI_PORT = 8008
HEADER_SIZE = 272
RECV_BUFFER = 65536


@dataclass
class FeitCSIConfig:
    """FeitCSI 測定パラメータ"""
    frequency: int = 2412       # MHz (2412-7125)
    channel_width: int = 20     # 20/40/80/160
    format: str = "HT"          # NOHT/HT/VHT/HESU
    mode: str = "measure"       # measure/inject/measureinject
    antenna: int = 1            # 1/2/12
    mcs: int = 0                # 0-11
    spatial_streams: int = 1    # 1/2
    coding: str = "LDPC"        # BCC/LDPC
    tx_power: int = 10          # 1-22 dBm
    inject_delay: int = 100000  # us

    def to_command(self) -> str:
        """FeitCSI コマンド文字列を生成"""
        cmd = (
            f"feitcsi"
            f" --frequency {self.frequency}"
            f" --channel-width {self.channel_width}"
            f" --format {self.format}"
            f" --mode {self.mode}"
            f" --antenna {self.antenna}"
            f" --mcs {self.mcs}"
            f" --spatial-streams {self.spatial_streams}"
            f" --coding {self.coding}"
        )
        if "inject" in self.mode:
            cmd += f" --tx-power {self.tx_power}"
            cmd += f" --inject-delay {self.inject_delay}"
        return cmd

    @classmethod
    def for_band(cls, band: str) -> "FeitCSIConfig":
        """バンドプリセットから設定を生成"""
        presets = {
            "2.4G": cls(frequency=2412, channel_width=20, format="HT"),
            "5G-80": cls(frequency=5180, channel_width=80, format="VHT"),
            "5G-160": cls(frequency=5180, channel_width=160, format="HESU"),
            "6G": cls(frequency=5955, channel_width=160, format="HESU"),
        }
        return presets.get(band, presets["2.4G"])


@dataclass
class CSIFrame:
    """パース済みCSIフレーム"""
    timestamp_us: int = 0
    num_rx: int = 0
    num_tx: int = 0
    num_subcarriers: int = 0
    rssi_tx1: int = 0
    rssi_tx2: int = 0
    source_mac: str = ""
    rate_format: str = ""
    channel_width: int = 0
    mcs: int = 0
    csi_real: list = None       # [num_subcarriers] float
    csi_imag: list = None       # [num_subcarriers] float
    csi_amplitude: list = None  # [num_subcarriers] float
    csi_phase: list = None      # [num_subcarriers] float
    raw_header: bytes = None
    raw_csi: bytes = None


class FeitCSIBridge:
    """FeitCSI UDP通信ブリッジ"""

    def __init__(
        self,
        host: str = FEITCSI_HOST,
        port: int = FEITCSI_PORT,
        queue_size: int = 100,
    ):
        self.host = host
        self.port = port
        self._sock: Optional[socket.socket] = None
        self._recv_thread: Optional[threading.Thread] = None
        self._running = False
        self._frame_queue: Queue[CSIFrame] = Queue(maxsize=queue_size)
        self._callback: Optional[Callable[[CSIFrame], None]] = None
        self._frame_count = 0
        self._error_count = 0

    def connect(self) -> bool:
        """UDPソケットを開設"""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(2.0)
            return True
        except OSError as e:
            print(f"[FeitCSI Bridge] ソケット作成失敗: {e}")
            return False

    def disconnect(self):
        """ソケットを閉じる"""
        self._running = False
        if self._recv_thread and self._recv_thread.is_alive():
            self._recv_thread.join(timeout=3)
        if self._sock:
            self._sock.close()
            self._sock = None

    def send_command(self, command: str) -> bool:
        """FeitCSI にコマンドを送信"""
        if not self._sock:
            if not self.connect():
                return False
        try:
            self._sock.sendto(
                command.encode("utf-8"),
                (self.host, self.port),
            )
            return True
        except OSError as e:
            print(f"[FeitCSI Bridge] コマンド送信失敗: {e}")
            return False

    def stop_measurement(self) -> bool:
        """測定を停止"""
        return self.send_command("stop")

    def start_measurement(self, config: FeitCSIConfig) -> bool:
        """測定を開始"""
        # まず停止
        self.stop_measurement()
        time.sleep(0.5)

        # コマンド送信
        cmd = config.to_command()
        print(f"[FeitCSI Bridge] 測定開始: {cmd}")
        return self.send_command(cmd)

    def start_receiving(
        self,
        callback: Optional[Callable[[CSIFrame], None]] = None,
    ):
        """CSIデータの受信ループを開始（別スレッド）"""
        self._callback = callback
        self._running = True
        self._recv_thread = threading.Thread(
            target=self._receive_loop,
            daemon=True,
            name="feitcsi-recv",
        )
        self._recv_thread.start()

    def stop_receiving(self):
        """受信ループを停止"""
        self._running = False
        if self._recv_thread:
            self._recv_thread.join(timeout=3)

    def get_frame(self, timeout: float = 1.0) -> Optional[CSIFrame]:
        """キューからCSIフレームを取得"""
        try:
            return self._frame_queue.get(timeout=timeout)
        except Exception:
            return None

    def _receive_loop(self):
        """CSIデータ受信ループ（スレッド内で実行）"""
        if not self._sock:
            return

        # 受信用に別ソケットを作成（データ受信用）
        recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        recv_sock.settimeout(1.0)
        recv_sock.bind(("", 0))  # 空きポートにバインド

        while self._running:
            try:
                data, addr = recv_sock.recvfrom(RECV_BUFFER)
                if len(data) < HEADER_SIZE:
                    continue

                frame = self._parse_frame(data)
                if frame:
                    self._frame_count += 1

                    # コールバック
                    if self._callback:
                        self._callback(frame)

                    # キューに追加
                    try:
                        self._frame_queue.put_nowait(frame)
                    except Full:
                        # 古いフレームを捨てて新しいものを入れる
                        try:
                            self._frame_queue.get_nowait()
                        except Exception:
                            pass
                        self._frame_queue.put_nowait(frame)

            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    self._error_count += 1
                    time.sleep(0.1)

        recv_sock.close()

    def _parse_frame(self, data: bytes) -> Optional[CSIFrame]:
        """FeitCSI バイナリデータをパース"""
        if len(data) < HEADER_SIZE:
            return None

        try:
            header = data[:HEADER_SIZE]
            frame = CSIFrame()
            frame.raw_header = header

            # ヘッダーパース
            csi_data_size = struct.unpack_from("<I", header, 0)[0]
            frame.timestamp_us = struct.unpack_from("<Q", header, 12)[0]
            frame.num_rx = header[46]
            frame.num_tx = header[47]
            frame.num_subcarriers = struct.unpack_from("<I", header, 52)[0]
            frame.rssi_tx1 = struct.unpack_from("<i", header, 60)[0]
            frame.rssi_tx2 = struct.unpack_from("<i", header, 64)[0]

            # MACアドレス (68-73)
            mac_bytes = header[68:74]
            frame.source_mac = ":".join(f"{b:02x}" for b in mac_bytes)

            # レートフラグ (92-95)
            rate_flags = struct.unpack_from("<I", header, 92)[0]
            frame.mcs = rate_flags & 0x0F
            rate_fmt = (rate_flags >> 8) & 0x07
            fmt_map = {0: "CCK", 1: "OFDM", 2: "HT", 3: "VHT", 4: "HE", 5: "EHT"}
            frame.rate_format = fmt_map.get(rate_fmt, f"unknown({rate_fmt})")
            cw = (rate_flags >> 11) & 0x07
            cw_map = {0: 20, 1: 40, 2: 80, 3: 160, 4: 320}
            frame.channel_width = cw_map.get(cw, 0)

            # CSIデータパース
            csi_bytes = data[HEADER_SIZE:HEADER_SIZE + csi_data_size]
            frame.raw_csi = csi_bytes

            expected_size = 4 * frame.num_rx * frame.num_tx * frame.num_subcarriers
            if len(csi_bytes) < expected_size:
                return frame  # ヘッダーのみ返す

            # IQ データ展開
            num_values = frame.num_rx * frame.num_tx * frame.num_subcarriers
            real_list = []
            imag_list = []
            amp_list = []
            phase_list = []

            import math
            for i in range(num_values):
                offset = i * 4
                real_val = struct.unpack_from("<h", csi_bytes, offset)[0]
                imag_val = struct.unpack_from("<h", csi_bytes, offset + 2)[0]
                real_list.append(real_val)
                imag_list.append(imag_val)
                amp = math.sqrt(real_val ** 2 + imag_val ** 2)
                amp_list.append(amp)
                phase_list.append(math.atan2(imag_val, real_val))

            frame.csi_real = real_list
            frame.csi_imag = imag_list
            frame.csi_amplitude = amp_list
            frame.csi_phase = phase_list

            return frame

        except (struct.error, IndexError, ValueError) as e:
            self._error_count += 1
            return None

    @property
    def stats(self) -> dict:
        """統計情報"""
        return {
            "frames_received": self._frame_count,
            "errors": self._error_count,
            "queue_size": self._frame_queue.qsize(),
            "connected": self._sock is not None,
            "receiving": self._running,
        }


if __name__ == "__main__":
    bridge = FeitCSIBridge()
    if bridge.connect():
        print("FeitCSI Bridge: 接続OK")
        config = FeitCSIConfig.for_band("2.4G")
        print(f"コマンド: {config.to_command()}")
        bridge.disconnect()
    else:
        print("FeitCSI Bridge: 接続失敗")
