"""
RuView Scan - NIC検出・検証ユーティリティ
(RF PROBE v2.0 から移植)
"""

import subprocess
import re
import logging
from dataclasses import dataclass
from typing import Optional, List

from src.errors import (
    NICNotFoundError, NICNotCSICapableError,
    MonitorModeError, NICBusyError
)

logger = logging.getLogger(__name__)

# CSI対応NICのパターン (PicoScenes/IAX)
CSI_CAPABLE_PATTERNS = [
    r"AX210", r"AX211", r"AX200", r"AX201",
    r"Wi-Fi 6E", r"Wi-Fi 6",
    r"Wireless.?Link.?5300", r"IWL5300",
    r"AR9300", r"QCA9300",
]


@dataclass
class NICInfo:
    """NIC情報"""
    interface: str
    driver: str
    chipset: str
    phy: str
    mac_address: str
    csi_capable: bool
    monitor_capable: bool
    supported_bands: List[str]


def run_command(cmd: List[str], timeout: int = 10) -> subprocess.CompletedProcess:
    """コマンド実行ラッパー (エラーハンドリング付き)"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result
    except subprocess.TimeoutExpired:
        logger.error(f"コマンドタイムアウト: {' '.join(cmd)}")
        raise
    except FileNotFoundError:
        logger.error(f"コマンドが見つかりません: {cmd[0]}")
        raise


def detect_wireless_interfaces() -> List[str]:
    """無線インターフェースの一覧を取得"""
    result = run_command(["iw", "dev"])
    if result.returncode != 0:
        logger.warning(f"iw dev 失敗: {result.stderr}")
        return []

    interfaces = re.findall(r"Interface\s+(\S+)", result.stdout)
    logger.info(f"検出された無線IF: {interfaces}")
    return interfaces


def get_nic_info(interface: str) -> NICInfo:
    """指定インターフェースのNIC情報を取得"""

    driver = "unknown"
    chipset = "unknown"
    try:
        ethtool_result = run_command(["ethtool", "-i", interface])
        if ethtool_result.returncode == 0:
            driver_match = re.search(r"driver:\s+(\S+)", ethtool_result.stdout)
            if driver_match:
                driver = driver_match.group(1)
    except FileNotFoundError:
        pass

    try:
        lspci_result = run_command(["lspci", "-v"])
        if lspci_result.returncode == 0:
            for line in lspci_result.stdout.split("\n"):
                if any(kw in line.lower() for kw in ["network", "wireless", "wifi"]):
                    chipset = line.strip()
                    break
    except FileNotFoundError:
        pass

    phy = "unknown"
    mac = "unknown"
    try:
        phy_result = run_command(["iw", "dev", interface, "info"])
        if phy_result.returncode == 0:
            phy_match = re.search(r"wiphy\s+(\d+)", phy_result.stdout)
            if phy_match:
                phy = f"phy{phy_match.group(1)}"
            mac_match = re.search(r"addr\s+([0-9a-fA-F:]{17})", phy_result.stdout)
            if mac_match:
                mac = mac_match.group(1)
    except FileNotFoundError:
        pass

    csi_capable = any(
        re.search(pattern, chipset, re.IGNORECASE)
        for pattern in CSI_CAPABLE_PATTERNS
    )

    monitor_capable = False
    try:
        if phy != "unknown":
            phy_info_result = run_command(["iw", "phy", phy, "info"])
            if phy_info_result.returncode == 0:
                monitor_capable = "monitor" in phy_info_result.stdout
    except FileNotFoundError:
        pass

    bands = []

    info = NICInfo(
        interface=interface,
        driver=driver,
        chipset=chipset,
        phy=phy,
        mac_address=mac,
        csi_capable=csi_capable,
        monitor_capable=monitor_capable,
        supported_bands=bands
    )

    logger.info(f"NIC情報: {info}")
    return info


def find_best_nic() -> NICInfo:
    """CSI対応の最適なNICを自動選択"""
    interfaces = detect_wireless_interfaces()

    if not interfaces:
        raise NICNotFoundError("iw dev でインターフェースが見つかりません")

    nic_list = []
    for iface in interfaces:
        try:
            info = get_nic_info(iface)
            nic_list.append(info)
        except Exception as e:
            logger.warning(f"NIC情報取得失敗 ({iface}): {e}")

    if not nic_list:
        raise NICNotFoundError("有効な無線NICが見つかりません")

    csi_nics = [n for n in nic_list if n.csi_capable]
    if csi_nics:
        def band_score(nic: NICInfo) -> int:
            score = 0
            if "6GHz" in nic.supported_bands:
                score += 4
            if "5GHz" in nic.supported_bands:
                score += 2
            if "2.4GHz" in nic.supported_bands:
                score += 1
            return score

        best = max(csi_nics, key=band_score)
        logger.info(f"最適NIC選択: {best.interface} ({best.chipset})")
        return best

    logger.warning("CSI対応NICが見つかりません。シミュレーションモードになる可能性があります")
    return nic_list[0]


def enable_monitor_mode(interface: str) -> str:
    """モニターモードを有効化し、モニター用インターフェース名を返す"""
    logger.info(f"モニターモード有効化: {interface}")

    check_result = run_command(["airmon-ng", "check"])
    if check_result.returncode == 0 and "PID" in check_result.stdout:
        lines = check_result.stdout.strip().split("\n")
        processes = [l for l in lines if l.strip() and "PID" not in l and "---" not in l]
        if processes:
            logger.warning(f"競合プロセス検出: {processes}")
            kill_result = run_command(["airmon-ng", "check", "kill"])
            if kill_result.returncode != 0:
                raise NICBusyError(interface, "\n".join(processes))

    start_result = run_command(["airmon-ng", "start", interface])
    if start_result.returncode != 0:
        raise MonitorModeError(
            interface,
            f"airmon-ng start 失敗: {start_result.stderr}"
        )

    new_interfaces = detect_wireless_interfaces()
    mon_candidates = [i for i in new_interfaces if "mon" in i]

    if mon_candidates:
        mon_if = mon_candidates[0]
        logger.info(f"モニターIF作成成功: {mon_if}")
        return mon_if

    if interface in new_interfaces:
        iw_result = run_command(["iw", "dev", interface, "info"])
        if "type monitor" in iw_result.stdout:
            logger.info(f"モニターモード確認 (同名IF): {interface}")
            return interface

    raise MonitorModeError(
        interface,
        "モニターインターフェースが見つかりません"
    )


def disable_monitor_mode(mon_interface: str) -> None:
    """モニターモードを無効化"""
    logger.info(f"モニターモード解除: {mon_interface}")
    run_command(["airmon-ng", "stop", mon_interface])
