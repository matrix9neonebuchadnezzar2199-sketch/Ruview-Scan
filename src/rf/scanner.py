"""
RuView Scan - RFスキャナー (RF PROBEから移植)
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from src.errors import RFScanError

logger = logging.getLogger(__name__)


@dataclass
class RFDevice:
    """検出されたRFデバイス"""
    bssid: str
    ssid: Optional[str]
    channel: int
    signal: float   # dBm
    frequency: str  # '2.4GHz' or '5GHz'
    is_known: bool
    is_suspicious: bool
    suspicion_reason: str = ""


class RFScanner:
    """RFパッシブスキャン (iw dev scan)"""

    def __init__(self, interface: str = "wlan0",
                 known_ssids: List[str] = None):
        self.interface = interface
        self.known_ssids = known_ssids or []
        self._last_devices: List[RFDevice] = []

    async def scan(self) -> List[RFDevice]:
        """RFスキャンを実行"""
        try:
            result = await asyncio.create_subprocess_exec(
                "iw", "dev", self.interface, "scan",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                result.communicate(), timeout=30
            )

            if result.returncode != 0:
                raise RFScanError(f"iw scan failed: {stderr.decode()}")

            devices = self._parse_scan_output(stdout.decode())
            self._last_devices = devices
            return devices

        except FileNotFoundError:
            logger.warning("iw コマンドが見つかりません (Windows?)")
            # シミュレーション: ダミーデバイスを返す
            return self._simulate_scan()
        except asyncio.TimeoutError:
            raise RFScanError("RFスキャンがタイムアウトしました")
        except RFScanError:
            raise
        except Exception as e:
            logger.warning(f"RFスキャンエラー: {e}")
            return self._simulate_scan()

    def _parse_scan_output(self, output: str) -> List[RFDevice]:
        """iw scan の出力をパース"""
        devices = []
        current = {}

        for line in output.split("\n"):
            line = line.strip()

            bss_match = re.match(r"BSS ([0-9a-fA-F:]+)", line)
            if bss_match:
                if current:
                    devices.append(self._create_device(current))
                current = {"bssid": bss_match.group(1)}
                continue

            if "SSID:" in line:
                current["ssid"] = line.split("SSID:", 1)[1].strip()
            elif "signal:" in line:
                sig_match = re.search(r"(-?\d+\.?\d*)\s*dBm", line)
                if sig_match:
                    current["signal"] = float(sig_match.group(1))
            elif "freq:" in line:
                freq_match = re.search(r"freq:\s*(\d+)", line)
                if freq_match:
                    current["freq"] = int(freq_match.group(1))

        if current:
            devices.append(self._create_device(current))

        return devices

    def _create_device(self, data: dict) -> RFDevice:
        """パースデータからRFDeviceを作成"""
        bssid = data.get("bssid", "unknown")
        ssid = data.get("ssid", None)
        signal = data.get("signal", -99.0)
        freq = data.get("freq", 2412)

        channel = self._freq_to_channel(freq)
        freq_band = "2.4GHz" if freq < 5000 else "5GHz"
        is_known = ssid in self.known_ssids if ssid else False

        # 不審判定
        is_suspicious = False
        reason = ""

        if not ssid or ssid == "":
            is_suspicious = True
            reason = "隠しSSID"
        elif signal > -20:
            is_suspicious = True
            reason = f"異常に強い信号 ({signal}dBm)"
        elif not is_known:
            if signal > -40:
                is_suspicious = True
                reason = f"未知のAP / 強信号 ({signal}dBm)"

        return RFDevice(
            bssid=bssid,
            ssid=ssid,
            channel=channel,
            signal=signal,
            frequency=freq_band,
            is_known=is_known,
            is_suspicious=is_suspicious,
            suspicion_reason=reason,
        )

    def _freq_to_channel(self, freq: int) -> int:
        """周波数からチャネル番号を計算"""
        if freq < 5000:
            return (freq - 2412) // 5 + 1
        return (freq - 5180) // 5 + 36

    def _simulate_scan(self) -> List[RFDevice]:
        """シミュレーション用のダミースキャン結果"""
        self._last_devices = [
            RFDevice("AA:BB:CC:DD:EE:01", "自社Wi-Fi", 1, -45.0,
                     "2.4GHz", True, False),
            RFDevice("AA:BB:CC:DD:EE:02", "自社Wi-Fi_5G", 36, -50.0,
                     "5GHz", True, False),
            RFDevice("11:22:33:44:55:66", None, 6, -35.0,
                     "2.4GHz", False, True, "隠しSSID"),
        ]
        return self._last_devices

    def get_suspicious_devices(self) -> List[RFDevice]:
        """不審デバイスのリスト"""
        return [d for d in self._last_devices if d.is_suspicious]
