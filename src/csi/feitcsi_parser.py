"""
RuView Scan - FeitCSI File Parser
FeitCSI の .dat ファイルを読み込み、CSIフレームのリストを返すパーサー

ファイル構造:
  [header(272B) + csi_data(可変)] × N フレーム

既存の adapter.py / collector.py との統合に使用
"""
# ERR-F009: feitcsi_parser.py - FeitCSI .datファイルパーサー

import math
import struct
from pathlib import Path
from typing import List, Optional, BinaryIO
from dataclasses import dataclass, field


HEADER_SIZE = 272


@dataclass
class ParsedCSIFrame:
    """パース済みCSIフレーム（ファイル読み込み用）"""
    frame_index: int = 0
    csi_data_size: int = 0
    ftm_clock: int = 0
    timestamp_us: int = 0
    num_rx: int = 0
    num_tx: int = 0
    num_subcarriers: int = 0
    rssi_tx1: int = 0
    rssi_tx2: int = 0
    source_mac: str = ""
    mcs: int = 0
    rate_format: str = ""
    channel_width: int = 0
    antenna_a: bool = False
    antenna_b: bool = False
    ldpc: bool = False
    spatial_streams: int = 1
    beamforming: bool = False
    csi_real: List[float] = field(default_factory=list)
    csi_imag: List[float] = field(default_factory=list)
    csi_amplitude: List[float] = field(default_factory=list)
    csi_phase: List[float] = field(default_factory=list)


def _parse_rate_flags(flags: int) -> dict:
    """レートフラグをパース"""
    mcs = flags & 0x0F
    rate_fmt_val = (flags >> 8) & 0x07
    fmt_map = {0: "CCK", 1: "OFDM", 2: "HT", 3: "VHT", 4: "HE", 5: "EHT"}
    rate_format = fmt_map.get(rate_fmt_val, f"unknown({rate_fmt_val})")

    cw_val = (flags >> 11) & 0x07
    cw_map = {0: 20, 1: 40, 2: 80, 3: 160, 4: 320}
    channel_width = cw_map.get(cw_val, 0)

    antenna_a = bool((flags >> 14) & 0x01)
    antenna_b = bool((flags >> 15) & 0x01)
    ldpc = bool((flags >> 16) & 0x01)
    spatial_streams = 2 if ((flags >> 17) & 0x01) else 1
    beamforming = bool((flags >> 19) & 0x01)

    return {
        "mcs": mcs,
        "rate_format": rate_format,
        "channel_width": channel_width,
        "antenna_a": antenna_a,
        "antenna_b": antenna_b,
        "ldpc": ldpc,
        "spatial_streams": spatial_streams,
        "beamforming": beamforming,
    }


def parse_header(header: bytes) -> Optional[ParsedCSIFrame]:
    """272バイトヘッダーをパース"""
    if len(header) < HEADER_SIZE:
        return None

    try:
        frame = ParsedCSIFrame()
        frame.csi_data_size = struct.unpack_from("<I", header, 0)[0]
        frame.ftm_clock = struct.unpack_from("<I", header, 8)[0]
        frame.timestamp_us = struct.unpack_from("<Q", header, 12)[0]
        frame.num_rx = header[46]
        frame.num_tx = header[47]
        frame.num_subcarriers = struct.unpack_from("<I", header, 52)[0]
        frame.rssi_tx1 = struct.unpack_from("<i", header, 60)[0]
        frame.rssi_tx2 = struct.unpack_from("<i", header, 64)[0]

        mac_bytes = header[68:74]
        frame.source_mac = ":".join(f"{b:02x}" for b in mac_bytes)

        rate_flags = struct.unpack_from("<I", header, 92)[0]
        rf = _parse_rate_flags(rate_flags)
        frame.mcs = rf["mcs"]
        frame.rate_format = rf["rate_format"]
        frame.channel_width = rf["channel_width"]
        frame.antenna_a = rf["antenna_a"]
        frame.antenna_b = rf["antenna_b"]
        frame.ldpc = rf["ldpc"]
        frame.spatial_streams = rf["spatial_streams"]
        frame.beamforming = rf["beamforming"]

        return frame

    except (struct.error, IndexError):
        return None


def parse_csi_data(frame: ParsedCSIFrame, csi_bytes: bytes) -> bool:
    """CSIバイナリデータを振幅・位相に変換"""
    expected = 4 * frame.num_rx * frame.num_tx * frame.num_subcarriers
    if len(csi_bytes) < expected:
        return False

    num_values = frame.num_rx * frame.num_tx * frame.num_subcarriers
    real_list = []
    imag_list = []
    amp_list = []
    phase_list = []

    for i in range(num_values):
        offset = i * 4
        real_val = struct.unpack_from("<h", csi_bytes, offset)[0]
        imag_val = struct.unpack_from("<h", csi_bytes, offset + 2)[0]
        real_list.append(float(real_val))
        imag_list.append(float(imag_val))
        amp = math.sqrt(real_val ** 2 + imag_val ** 2)
        amp_list.append(amp)
        phase_list.append(math.atan2(imag_val, real_val))

    frame.csi_real = real_list
    frame.csi_imag = imag_list
    frame.csi_amplitude = amp_list
    frame.csi_phase = phase_list
    return True


def parse_file(filepath: str, max_frames: int = 0) -> List[ParsedCSIFrame]:
    """FeitCSI .dat ファイルを全フレームパース"""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    file_size = path.stat().st_size
    frames = []
    frame_index = 0

    with open(path, "rb") as f:
        pos = 0
        while pos < file_size:
            # ヘッダー読み込み
            header_bytes = f.read(HEADER_SIZE)
            if len(header_bytes) < HEADER_SIZE:
                break

            frame = parse_header(header_bytes)
            if frame is None:
                break

            frame.frame_index = frame_index

            # CSIデータ読み込み
            csi_bytes = f.read(frame.csi_data_size)
            if len(csi_bytes) < frame.csi_data_size:
                break

            parse_csi_data(frame, csi_bytes)
            frames.append(frame)

            pos += HEADER_SIZE + frame.csi_data_size
            frame_index += 1

            if max_frames > 0 and frame_index >= max_frames:
                break

    return frames


def get_subcarrier_count(channel_width: int, rate_format: str) -> int:
    """帯域幅とフォーマットから期待サブキャリア数を返す"""
    table = {
        ("HT", 20): 56,
        ("HT", 40): 114,
        ("VHT", 20): 56,
        ("VHT", 40): 114,
        ("VHT", 80): 242,
        ("VHT", 160): 484,
        ("HE", 20): 242,
        ("HE", 40): 484,
        ("HE", 80): 996,
        ("HE", 160): 1992,
        ("OFDM", 20): 52,
    }
    return table.get((rate_format, channel_width), 0)


def print_file_summary(filepath: str, max_frames: int = 5):
    """ファイルのサマリーを表示"""
    frames = parse_file(filepath, max_frames=max_frames)
    total = parse_file(filepath)

    print(f"File: {filepath}")
    print(f"Total frames: {len(total)}")
    print(f"Showing first {min(max_frames, len(frames))} frames:")
    print("-" * 70)
    print(f"{'#':>4} {'Time(us)':>14} {'RxTx':>5} {'SC':>5} "
          f"{'BW':>4} {'Fmt':>5} {'MCS':>3} {'RSSI':>5} {'MAC':>17}")
    print("-" * 70)

    for fr in frames:
        print(
            f"{fr.frame_index:4d} "
            f"{fr.timestamp_us:14d} "
            f"{fr.num_rx}x{fr.num_tx:>3} "
            f"{fr.num_subcarriers:5d} "
            f"{fr.channel_width:4d} "
            f"{fr.rate_format:>5} "
            f"{fr.mcs:3d} "
            f"{fr.rssi_tx1:5d} "
            f"{fr.source_mac:>17}"
        )


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print_file_summary(sys.argv[1])
    else:
        print("Usage: python feitcsi_parser.py <file.dat>")
        print("FeitCSI .dat file parser for RuView Scan")
