"""
RuView Scan - 不審デバイス分類
"""

import logging
from typing import List

from src.rf.scanner import RFDevice

logger = logging.getLogger(__name__)


class DeviceClassifier:
    """RFデバイスの分類・リスク評価"""

    def __init__(self):
        # 既知の安全なOUIプレフィックス
        self.safe_oui_prefixes = [
            "00:0C:29",  # VMware
            "00:50:56",  # VMware
        ]

    def classify(self, device: RFDevice) -> dict:
        """デバイスの脅威レベルを評価"""
        threat_level = "none"
        threat_type = ""
        description = ""

        if not device.is_suspicious:
            return {
                "threat_level": "none",
                "threat_type": "",
                "description": "正常なデバイス",
            }

        # 隠しSSID
        if not device.ssid:
            threat_level = "medium"
            threat_type = "hidden_ap"
            description = "SSID非公開のアクセスポイント"

        # 異常に強い信号
        if device.signal > -20:
            threat_level = "high"
            threat_type = "proximity_device"
            description = f"壁内設置の疑い (信号: {device.signal}dBm)"

        # 未知のデバイスかつ強信号
        if not device.is_known and device.signal > -40:
            threat_level = "high"
            threat_type = "unknown_strong"
            description = f"未知の強信号AP (SSID:{device.ssid or '非公開'})"

        return {
            "threat_level": threat_level,
            "threat_type": threat_type,
            "description": description,
            "bssid": device.bssid,
            "signal": device.signal,
            "frequency": device.frequency,
        }

    def classify_all(self, devices: List[RFDevice]) -> List[dict]:
        """全デバイスを分類"""
        return [self.classify(d) for d in devices if d.is_suspicious]
