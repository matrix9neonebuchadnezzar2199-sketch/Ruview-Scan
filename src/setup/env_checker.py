"""
RuView Scan - Environment Checker
起動時に8項目の環境チェックを実行し、構造化された結果を返す

チェック項目:
  [1] OS:      Linux系か（Debian系推奨）
  [2] Arch:    x86_64 / arm64
  [3] CPU:     コア数・SSE4.2/AVX2対応
  [4] NIC:     AX210/AX211/AX200 検出（lspci）
  [5] FW:      /lib/firmware/iwlwifi-* 存在確認
  [6] Headers: linux-headers-$(uname -r) 存在確認
  [7] FeitCSI: feitcsi バイナリ存在 & ドライバロード状態
  [8] Deps:    ビルド依存パッケージ存在確認
"""
# ERR-F002: env_checker.py - 環境チェックモジュール

import os
import re
import shutil
import subprocess
import platform
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict

from .setup_state import SetupStateManager, EnvironmentInfo


class CheckResult(str, Enum):
    """チェック結果"""
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class CheckItem:
    """個別チェック項目の結果"""
    id: str
    name: str
    result: str = CheckResult.SKIP
    message: str = ""
    detail: str = ""
    fix_hint: str = ""
    can_auto_fix: bool = False

    @property
    def is_ok(self) -> bool:
        return self.result in (CheckResult.OK, CheckResult.WARN, CheckResult.SKIP)

    @property
    def is_critical(self) -> bool:
        return self.result == CheckResult.FAIL


@dataclass
class EnvironmentCheckReport:
    """環境チェック全体のレポート"""
    checks: List[dict] = field(default_factory=list)
    environment: dict = field(default_factory=dict)
    all_passed: bool = False
    can_proceed: bool = False
    simulation_only: bool = False
    summary_message: str = ""

    def add_check(self, item: CheckItem):
        self.checks.append(asdict(item))

    def finalize(self):
        critical_fails = [
            c for c in self.checks if c["result"] == CheckResult.FAIL
        ]
        nic_check = next(
            (c for c in self.checks if c["id"] == "nic"), None
        )

        self.all_passed = len(critical_fails) == 0

        if self.all_passed:
            self.can_proceed = True
            self.simulation_only = False
            self.summary_message = "全チェック通過。実機スキャン可能です。"
        elif nic_check and nic_check["result"] == CheckResult.FAIL:
            nic_only_fail = all(
                c["result"] != CheckResult.FAIL or c["id"] == "nic"
                for c in self.checks
            )
            if nic_only_fail:
                self.can_proceed = True
                self.simulation_only = True
                self.summary_message = (
                    "NIC未検出。シミュレーションモードで起動します。"
                    "実機スキャンにはAX210/AX200のPCIe接続が必要です。"
                )
            else:
                self.can_proceed = False
                self.simulation_only = False
                self.summary_message = (
                    f"{len(critical_fails)}件の問題があります。"
                    "セットアップを実行してください。"
                )
        else:
            self.can_proceed = False
            self.summary_message = (
                f"{len(critical_fails)}件の問題があります。"
                "セットアップを実行してください。"
            )


def _run_cmd(cmd: List[str], timeout: int = 10) -> tuple:
    """コマンド実行ヘルパー。(returncode, stdout, stderr)を返す"""
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
        return -2, "", f"Command timed out: {' '.join(cmd)}"
    except Exception as e:
        return -3, "", str(e)


def _check_file_exists(path: str) -> bool:
    return Path(path).exists()


def _check_command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None


class EnvironmentChecker:
    """環境チェックエンジン"""

    def __init__(self, project_root: Optional[str] = None):
        if project_root is None:
            project_root = str(
                Path(__file__).resolve().parent.parent.parent
            )
        self.project_root = Path(project_root)
        self.setup_dir = self.project_root / "setup"
        self.env_info = EnvironmentInfo()

    def run_all_checks(self) -> EnvironmentCheckReport:
        """全チェックを実行してレポートを返す"""
        report = EnvironmentCheckReport()

        checks = [
            self._check_os,
            self._check_arch,
            self._check_cpu,
            self._check_nic,
            self._check_firmware,
            self._check_linux_headers,
            self._check_feitcsi,
            self._check_build_deps,
        ]

        for check_fn in checks:
            item = check_fn()
            report.add_check(item)

        report.environment = asdict(self.env_info)
        report.finalize()
        return report

    def _check_os(self) -> CheckItem:
        """[1] OS チェック"""
        item = CheckItem(id="os", name="オペレーティングシステム")

        system = platform.system()
        if system != "Linux":
            item.result = CheckResult.FAIL
            item.message = f"Linux以外のOS検出: {system}"
            item.fix_hint = "RuView ScanはLinux上で動作します。"
            return item

        os_info = SetupStateManager.detect_os_info()
        self.env_info.os_name = os_info["os_name"]
        self.env_info.os_version = os_info["os_version"]
        self.env_info.os_id = os_info["os_id"]
        self.env_info.os_id_like = os_info["os_id_like"]

        is_debian_based = (
            self.env_info.os_id in ("debian", "ubuntu", "kali", "linuxmint")
            or "debian" in self.env_info.os_id_like
        )

        if is_debian_based:
            item.result = CheckResult.OK
            item.message = f"{self.env_info.os_name} (Debian系)"
        else:
            item.result = CheckResult.WARN
            item.message = (
                f"{self.env_info.os_name} (非Debian系)。"
                "パッケージインストールに手動対応が必要な場合があります。"
            )

        return item

    def _check_arch(self) -> CheckItem:
        """[2] アーキテクチャチェック"""
        item = CheckItem(id="arch", name="CPUアーキテクチャ")

        arch = platform.machine()
        self.env_info.arch = arch

        if arch in ("x86_64", "AMD64"):
            item.result = CheckResult.OK
            item.message = f"{arch}"
        elif arch in ("aarch64", "arm64"):
            item.result = CheckResult.OK
            item.message = f"{arch} (FeitCSI ARM対応)"
        else:
            item.result = CheckResult.FAIL
            item.message = f"非対応アーキテクチャ: {arch}"
            item.fix_hint = "x86_64 または arm64 が必要です。"

        return item

    def _check_cpu(self) -> CheckItem:
        """[3] CPU チェック"""
        item = CheckItem(id="cpu", name="CPU情報")

        rc, stdout, _ = _run_cmd(["nproc"])
        if rc == 0:
            self.env_info.cpu_cores = int(stdout)
        else:
            self.env_info.cpu_cores = os.cpu_count() or 0

        rc, stdout, _ = _run_cmd(["cat", "/proc/cpuinfo"])
        if rc == 0:
            model_match = re.search(r"model name\s*:\s*(.+)", stdout)
            if model_match:
                self.env_info.cpu_model = model_match.group(1).strip()
            self.env_info.has_sse42 = "sse4_2" in stdout
            self.env_info.has_avx2 = "avx2" in stdout

        item.result = CheckResult.OK
        parts = [f"{self.env_info.cpu_cores}コア"]
        if self.env_info.cpu_model:
            parts.insert(0, self.env_info.cpu_model)
        if self.env_info.has_avx2:
            parts.append("AVX2対応")
        elif self.env_info.has_sse42:
            parts.append("SSE4.2対応")
        item.message = ", ".join(parts)

        return item

    def _check_nic(self) -> CheckItem:
        """[4] NIC チェック（AX210/AX211/AX200）"""
        item = CheckItem(id="nic", name="Wi-Fi NIC (Intel AX210/AX200)")

        # Intel Wi-Fi NIC の PCI ID パターン
        # AX210: 8086:2725
        # AX211: 8086:51f0 / 8086:51f1 / 8086:54f0
        # AX200: 8086:2723
        # AX201: 8086:a0f0 / 8086:02f0
        target_ids = {
            "8086:2725": "AX210",
            "8086:2726": "AX210 (variant)",
            "8086:51f0": "AX211",
            "8086:51f1": "AX211",
            "8086:54f0": "AX211",
            "8086:2723": "AX200",
            "8086:a0f0": "AX201",
            "8086:02f0": "AX201",
        }

        rc, stdout, _ = _run_cmd(["lspci", "-nn"])
        if rc != 0:
            item.result = CheckResult.FAIL
            item.message = "lspciが実行できません"
            item.fix_hint = "pciutils をインストールしてください"
            item.can_auto_fix = True
            return item

        detected = None
        for pci_id, model in target_ids.items():
            if pci_id.lower() in stdout.lower():
                detected = model
                self.env_info.nic_pci_id = pci_id
                break

        if detected:
            self.env_info.nic_detected = True
            self.env_info.nic_model = detected
            item.result = CheckResult.OK
            item.message = f"Intel {detected} 検出"
        else:
            self.env_info.nic_detected = False
            item.result = CheckResult.FAIL
            item.message = "対応NIC未検出"
            item.detail = (
                "Intel AX210/AX211/AX200 がPCIeバスに見つかりません。"
                "仮想環境の場合はPCIパススルーが必要です。"
            )
            item.fix_hint = (
                "シミュレーションモードで続行可能です。"
                "実機スキャンにはAX210をPCIe/M.2で接続してください。"
            )

        return item

    def _check_firmware(self) -> CheckItem:
        """[5] ファームウェアチェック"""
        item = CheckItem(id="firmware", name="iwlwifi ファームウェア")

        fw_dir = Path("/lib/firmware")
        ax210_patterns = [
            "iwlwifi-ty-a0-gf-a0-*.ucode",
            "iwlwifi-ty-a0-gf-a0.pnvm",
        ]

        found = False
        found_path = ""
        if fw_dir.exists():
            for pattern in ax210_patterns:
                matches = list(fw_dir.glob(pattern))
                if matches:
                    found = True
                    found_path = str(matches[0])
                    break

        # setup/firmware/ にも確認
        local_fw = self.setup_dir / "firmware"
        local_found = False
        if local_fw.exists():
            for pattern in ax210_patterns:
                if list(local_fw.glob(pattern)):
                    local_found = True
                    break

        self.env_info.firmware_present = found
        self.env_info.firmware_path = found_path

        if found:
            item.result = CheckResult.OK
            item.message = f"ファームウェア検出: {Path(found_path).name}"
        elif local_found:
            item.result = CheckResult.WARN
            item.message = "setup/firmware/ に同梱あり（未インストール）"
            item.fix_hint = "セットアップ時に自動コピーします"
            item.can_auto_fix = True
        else:
            item.result = CheckResult.FAIL
            item.message = "ファームウェア未検出"
            item.fix_hint = (
                "linux-firmware パッケージのインストール、"
                "または setup/firmware/ にファイルを配置してください"
            )
            item.can_auto_fix = True

        return item

    def _check_linux_headers(self) -> CheckItem:
        """[6] linux-headers チェック"""
        item = CheckItem(id="headers", name="Linux Headers")

        kernel = SetupStateManager.get_current_kernel()
        self.env_info.kernel_version = kernel

        # /lib/modules/{kernel}/build が存在するか
        headers_path = Path(f"/lib/modules/{kernel}/build")

        if headers_path.exists():
            item.result = CheckResult.OK
            item.message = f"linux-headers-{kernel} インストール済み"
        else:
            item.result = CheckResult.FAIL
            item.message = f"linux-headers-{kernel} 未インストール"
            item.fix_hint = (
                f"sudo apt install linux-headers-{kernel} "
                "を実行してください"
            )
            item.can_auto_fix = True
            item.detail = (
                "FeitCSI ドライバのビルドに必要です。"
                "カーネルに対応するヘッダーがインストールされていません。"
            )

        return item

    def _check_feitcsi(self) -> CheckItem:
        """[7] FeitCSI チェック"""
        item = CheckItem(id="feitcsi", name="FeitCSI")

        feitcsi_bin = _check_command_exists("feitcsi")
        feitcsi_local = (self.setup_dir / "feitcsi" / "FeitCSI").exists()

        # ドライバがロードされているか
        rc, stdout, _ = _run_cmd(["lsmod"])
        driver_loaded = False
        if rc == 0:
            driver_loaded = "iwlwifi" in stdout

        if feitcsi_bin:
            item.result = CheckResult.OK
            item.message = "FeitCSI インストール済み"
            if driver_loaded:
                item.message += "、ドライバロード済み"
            else:
                item.message += "（ドライバ未ロード）"
                item.detail = "feitcsi-iwlwifi ドライバの再ロードが必要な可能性があります"
        elif feitcsi_local:
            item.result = CheckResult.WARN
            item.message = "ソースコード同梱済み（未ビルド）"
            item.fix_hint = "セットアップ時に自動ビルドします"
            item.can_auto_fix = True
        else:
            item.result = CheckResult.FAIL
            item.message = "FeitCSI 未インストール・ソース未同梱"
            item.fix_hint = (
                "setup/feitcsi/ にソースを配置するか、"
                "download_packages.sh を実行してください"
            )
            item.can_auto_fix = True

        return item

    def _check_build_deps(self) -> CheckItem:
        """[8] ビルド依存パッケージチェック"""
        item = CheckItem(id="build_deps", name="ビルド依存パッケージ")

        required_commands = {
            "make": "build-essential",
            "gcc": "build-essential",
            "dkms": "dkms",
            "flex": "flex",
        }

        required_libs = [
            ("/usr/include/gtkmm-3.0", "libgtkmm-3.0-dev"),
            ("/usr/include/libnl3/netlink", "libnl-genl-3-dev"),
            ("/usr/include/iwlib.h", "libiw-dev"),
            ("/usr/include/pcap/pcap.h", "libpcap-dev"),
        ]

        missing_cmds = []
        for cmd, pkg in required_commands.items():
            if not _check_command_exists(cmd):
                missing_cmds.append(pkg)

        missing_libs = []
        for path, pkg in required_libs:
            if not Path(path).exists():
                missing_libs.append(pkg)

        all_missing = list(set(missing_cmds + missing_libs))

        # setup/deb/ にオフラインパッケージがあるか確認
        deb_dir = self.setup_dir / "deb"
        has_offline_debs = deb_dir.exists() and any(deb_dir.glob("*.deb"))

        if not all_missing:
            item.result = CheckResult.OK
            item.message = "全依存パッケージ インストール済み"
        elif has_offline_debs:
            item.result = CheckResult.WARN
            item.message = (
                f"{len(all_missing)}個の未インストールパッケージあり"
                "（オフラインパッケージ同梱済み）"
            )
            item.detail = f"未インストール: {', '.join(all_missing)}"
            item.fix_hint = "セットアップ時に自動インストールします"
            item.can_auto_fix = True
        else:
            item.result = CheckResult.FAIL
            item.message = f"{len(all_missing)}個のパッケージが不足"
            item.detail = f"未インストール: {', '.join(all_missing)}"
            item.fix_hint = (
                f"sudo apt install {' '.join(all_missing)} "
                "を実行してください"
            )
            item.can_auto_fix = True

        return item


def print_report(report: EnvironmentCheckReport):
    """レポートをターミナルに表示"""
    ICONS = {
        CheckResult.OK: "✅",
        CheckResult.WARN: "⚠️ ",
        CheckResult.FAIL: "❌",
        CheckResult.SKIP: "⏭️ ",
    }

    print("=" * 60)
    print("  RuView Scan - 環境チェックレポート")
    print("=" * 60)

    for check in report.checks:
        icon = ICONS.get(check["result"], "?")
        print(f"  {icon} [{check['id']:12s}] {check['message']}")
        if check["detail"]:
            print(f"     {check['detail']}")
        if check["fix_hint"] and check["result"] in (
            CheckResult.FAIL, CheckResult.WARN
        ):
            print(f"     💡 {check['fix_hint']}")

    print("-" * 60)
    print(f"  {report.summary_message}")
    if report.simulation_only:
        print("  🔧 シミュレーションモードで起動可能")
    print("=" * 60)


# === CLI テスト用 ===
if __name__ == "__main__":
    checker = EnvironmentChecker()
    report = checker.run_all_checks()
    print_report(report)
