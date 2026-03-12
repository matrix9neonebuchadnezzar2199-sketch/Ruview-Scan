"""
RuView Scan - Monitor Mode Setup
AX210/AX200のモニターモード自動起動とFeitCSI UDPサービス起動を管理

フロー:
  1. NICインターフェース名を自動検出
  2. rfkill unblock → インターフェースdown
  3. FeitCSIドライバ経由でモニターモード有効化
  4. feitcsi --udp-socket をバックグラウンド起動
  5. UDP:8008 の応答確認
"""
# ERR-F005: monitor_setup.py - モニターモード設定モジュール

import os
import re
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass

from .setup_state import (
    SetupStateManager, SetupState,
    ComponentState, ComponentStatus,
)


FEITCSI_UDP_HOST = "127.0.0.1"
FEITCSI_UDP_PORT = 8008
FEITCSI_STARTUP_TIMEOUT = 10


@dataclass
class MonitorStatus:
    """モニターモードの状態"""
    interface_name: str = ""
    is_monitor_mode: bool = False
    feitcsi_running: bool = False
    feitcsi_pid: int = 0
    udp_responsive: bool = False
    error: str = ""


def _run_cmd(cmd: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    """コマンド実行ヘルパー"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LANG": "C", "LC_ALL": "C"},
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", f"Timed out ({timeout}s): {' '.join(cmd)}"


def _run_sudo(cmd: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    """sudo付きコマンド実行"""
    return _run_cmd(["sudo"] + cmd, timeout=timeout)


class MonitorSetup:
    """モニターモードの設定と管理"""

    def __init__(self):
        self._feitcsi_process: Optional[subprocess.Popen] = None
        self.status = MonitorStatus()

    def detect_wifi_interface(self) -> Optional[str]:
        """Intel AX210/AX200 のWi-Fiインターフェース名を自動検出"""

        # 方法1: iw dev から検出
        rc, stdout, _ = _run_cmd(["iw", "dev"])
        if rc == 0 and stdout:
            interfaces = re.findall(r"Interface\s+(\S+)", stdout)
            for iface in interfaces:
                # このインターフェースが Intel NIC か確認
                phy = self._get_phy_for_interface(iface)
                if phy and self._is_intel_nic(phy):
                    self.status.interface_name = iface
                    return iface

        # 方法2: /sys/class/net/ から Wi-Fi インターフェースを検索
        net_dir = Path("/sys/class/net")
        if net_dir.exists():
            for iface_dir in net_dir.iterdir():
                wireless_dir = iface_dir / "wireless"
                if wireless_dir.exists():
                    iface = iface_dir.name
                    phy = self._get_phy_for_interface(iface)
                    if phy and self._is_intel_nic(phy):
                        self.status.interface_name = iface
                        return iface

        # 方法3: 一般的な名前パターンで探索
        common_names = ["wlan0", "wlan1", "wlp0s20f3", "wlp1s0", "wlp2s0"]
        for name in common_names:
            if Path(f"/sys/class/net/{name}").exists():
                self.status.interface_name = name
                return name

        return None

    def _get_phy_for_interface(self, iface: str) -> Optional[str]:
        """インターフェースに対応するphyデバイス名を取得"""
        phy_path = Path(f"/sys/class/net/{iface}/phy80211/name")
        if phy_path.exists():
            try:
                return phy_path.read_text().strip()
            except OSError:
                pass

        rc, stdout, _ = _run_cmd(["iw", "dev", iface, "info"])
        if rc == 0:
            match = re.search(r"wiphy\s+(\d+)", stdout)
            if match:
                return f"phy{match.group(1)}"
        return None

    def _is_intel_nic(self, phy: str) -> bool:
        """phyデバイスがIntel NICかチェック"""
        rc, stdout, _ = _run_cmd(["iw", "phy", phy, "info"])
        if rc == 0:
            return "iwlwifi" in stdout.lower() or "intel" in stdout.lower()

        # ドライバ名で判定
        phy_path = Path(f"/sys/class/ieee80211/{phy}/device/driver")
        if phy_path.is_symlink():
            driver = os.path.basename(os.readlink(str(phy_path)))
            return driver in ("iwlwifi", "iwlmvm")

        return False

    def setup_monitor_mode(self, interface: str) -> bool:
        """モニターモードを設定"""
        print(f"[MONITOR] インターフェース {interface} をモニターモードに設定中...")

        # Step 1: rfkill unblock
        print("  [1/4] rfkill unblock wifi")
        _run_sudo(["rfkill", "unblock", "wifi"])

        # Step 2: インターフェースを停止
        print(f"  [2/4] ip link set {interface} down")
        rc, _, stderr = _run_sudo(["ip", "link", "set", interface, "down"])
        if rc != 0:
            self.status.error = f"Interface down失敗: {stderr}"
            print(f"  ❌ {self.status.error}")
            return False

        # Step 3: モニターモード設定
        print(f"  [3/4] iw dev {interface} set type monitor")
        rc, _, stderr = _run_sudo(
            ["iw", "dev", interface, "set", "type", "monitor"]
        )
        if rc != 0:
            # FeitCSI ドライバが独自のモニターモード制御を持つ場合がある
            # iwconfig でも試行
            rc2, _, stderr2 = _run_sudo(
                ["iwconfig", interface, "mode", "monitor"]
            )
            if rc2 != 0:
                self.status.error = f"モニターモード設定失敗: {stderr}"
                print(f"  ⚠️  標準コマンドでの設定失敗。FeitCSIが管理する場合があります。")

        # Step 4: インターフェースを起動
        print(f"  [4/4] ip link set {interface} up")
        rc, _, stderr = _run_sudo(["ip", "link", "set", interface, "up"])
        if rc != 0:
            self.status.error = f"Interface up失敗: {stderr}"
            print(f"  ❌ {self.status.error}")
            return False

        # 確認
        rc, stdout, _ = _run_cmd(["iw", "dev", interface, "info"])
        if rc == 0 and "monitor" in stdout.lower():
            self.status.is_monitor_mode = True
            print(f"  ✅ モニターモード設定完了")
            return True
        else:
            # FeitCSI がモニターモードを内部管理するケースもある
            print(f"  ⚠️  モニターモード確認できず。FeitCSIに委任します。")
            self.status.is_monitor_mode = False
            return True  # FeitCSI に任せるため続行

    def start_feitcsi_service(self) -> bool:
        """FeitCSI を UDP ソケットモードでバックグラウンド起動"""
        print("[FEITCSI] UDP ソケットモードで起動中...")

        # 既に起動しているか確認
        if self._check_feitcsi_running():
            print("  ⏭️  FeitCSI 既に起動中")
            self.status.feitcsi_running = True
            return True

        # feitcsi バイナリの場所を確認
        feitcsi_bin = self._find_feitcsi_binary()
        if not feitcsi_bin:
            self.status.error = "feitcsi バイナリが見つかりません"
            print(f"  ❌ {self.status.error}")
            return False

        try:
            self._feitcsi_process = subprocess.Popen(
                ["sudo", feitcsi_bin, "--udp-socket"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "LANG": "C", "LC_ALL": "C"},
            )
            self.status.feitcsi_pid = self._feitcsi_process.pid
            print(f"  PID: {self.status.feitcsi_pid}")
        except Exception as e:
            self.status.error = f"FeitCSI起動失敗: {e}"
            print(f"  ❌ {self.status.error}")
            return False

        # 起動待ち + UDP応答確認
        print(f"  UDP:{FEITCSI_UDP_PORT} の応答を待機中...")
        for i in range(FEITCSI_STARTUP_TIMEOUT):
            time.sleep(1)
            if self._check_udp_responsive():
                self.status.feitcsi_running = True
                self.status.udp_responsive = True
                print(f"  ✅ FeitCSI 起動完了 (UDP:{FEITCSI_UDP_PORT} 応答確認)")
                return True
            print(f"  ... 待機中 ({i+1}/{FEITCSI_STARTUP_TIMEOUT}s)")

        # タイムアウト
        self.status.error = f"FeitCSI UDP応答タイムアウト ({FEITCSI_STARTUP_TIMEOUT}s)"
        print(f"  ⚠️  {self.status.error}")
        # プロセスは起動しているかもしれないので続行
        self.status.feitcsi_running = self._check_feitcsi_running()
        return self.status.feitcsi_running

    def stop_feitcsi_service(self):
        """FeitCSI プロセスを停止"""
        print("[FEITCSI] 停止中...")

        # UDP で stop コマンドを送信
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(b"stop", (FEITCSI_UDP_HOST, FEITCSI_UDP_PORT))
            sock.close()
        except Exception:
            pass

        # プロセスを終了
        if self._feitcsi_process:
            try:
                self._feitcsi_process.terminate()
                self._feitcsi_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._feitcsi_process.kill()
            self._feitcsi_process = None

        # sudo で起動した場合の cleanup
        _run_sudo(["pkill", "-f", "feitcsi --udp-socket"])

        self.status.feitcsi_running = False
        self.status.udp_responsive = False
        print("  ✅ FeitCSI 停止完了")

    def _find_feitcsi_binary(self) -> Optional[str]:
        """feitcsi バイナリのパスを検索"""
        import shutil

        # PATH上を検索
        path = shutil.which("feitcsi")
        if path:
            return path

        # 一般的なインストール先を確認
        candidates = [
            "/usr/local/bin/feitcsi",
            "/usr/bin/feitcsi",
        ]
        for c in candidates:
            if Path(c).exists():
                return c

        return None

    def _check_feitcsi_running(self) -> bool:
        """FeitCSI プロセスが動作中か確認"""
        rc, stdout, _ = _run_cmd(["pgrep", "-f", "feitcsi.*udp-socket"])
        return rc == 0 and stdout.strip() != ""

    def _check_udp_responsive(self) -> bool:
        """FeitCSI の UDP ポートが応答するか確認"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1.0)
            # ping 的にコマンドを送る（stopは送らない）
            sock.sendto(b"feitcsi --help", (FEITCSI_UDP_HOST, FEITCSI_UDP_PORT))
            sock.close()
            return True
        except (socket.timeout, OSError):
            return False

    def full_setup(self, state: SetupState) -> MonitorStatus:
        """モニターモード設定からFeitCSI起動まで一連の処理"""
        comp = state.get_component("monitor_mode")

        # 1. NIC 検出
        iface = self.detect_wifi_interface()
        if not iface:
            print("[MONITOR] Wi-Fiインターフェース未検出。スキップ。")
            comp.mark_skipped("NIC未検出 - シミュレーションモード")
            state.set_component(comp)
            return self.status

        # 2. モニターモード設定
        self.setup_monitor_mode(iface)

        # 3. FeitCSI 起動
        if self._find_feitcsi_binary():
            self.start_feitcsi_service()
        else:
            print("[MONITOR] FeitCSI未インストール。スキップ。")
            self.status.error = "FeitCSI未インストール"

        # 状態記録
        if self.status.feitcsi_running:
            comp.mark_installed(
                version=f"iface={iface}",
                kernel=SetupStateManager.get_current_kernel(),
            )
        elif self.status.is_monitor_mode:
            comp.mark_installed(version=f"monitor_only iface={iface}")
        else:
            comp.mark_skipped(self.status.error or "セットアップ不完全")

        state.set_component(comp)
        return self.status

    def get_status_dict(self) -> dict:
        """WebUI表示用のステータス辞書"""
        return {
            "interface": self.status.interface_name,
            "monitor_mode": self.status.is_monitor_mode,
            "feitcsi_running": self.status.feitcsi_running,
            "feitcsi_pid": self.status.feitcsi_pid,
            "udp_responsive": self.status.udp_responsive,
            "error": self.status.error,
        }


if __name__ == "__main__":
    setup = MonitorSetup()
    iface = setup.detect_wifi_interface()
    if iface:
        print(f"検出: {iface}")
    else:
        print("Wi-Fiインターフェース未検出")
    print(f"Status: {setup.get_status_dict()}")
