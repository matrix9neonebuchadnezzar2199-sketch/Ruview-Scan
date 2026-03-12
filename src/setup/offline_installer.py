"""
RuView Scan - Offline Installer
setup/ フォルダに同梱されたパッケージをオフラインでインストールする

対象:
  - setup/deb/*.deb          → dpkg -i でインストール
  - setup/firmware/*.ucode   → /lib/firmware/ にコピー
  - setup/python_wheels/*.whl → pip install でインストール
"""
# ERR-F003: offline_installer.py - オフラインインストールモジュール

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass

from .setup_state import (
    SetupStateManager, SetupState,
    ComponentState, ComponentStatus,
)


@dataclass
class InstallResult:
    """インストール結果"""
    component: str
    success: bool
    message: str
    installed_items: List[str]
    failed_items: List[str]


def _run_sudo(cmd: List[str], timeout: int = 120) -> Tuple[int, str, str]:
    """sudo付きコマンド実行"""
    try:
        result = subprocess.run(
            ["sudo"] + cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LANG": "C", "LC_ALL": "C", "DEBIAN_FRONTEND": "noninteractive"},
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", f"Command timed out ({timeout}s): {' '.join(cmd)}"


def _run_cmd(cmd: List[str], timeout: int = 60) -> Tuple[int, str, str]:
    """通常コマンド実行"""
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
        return -2, "", f"Command timed out ({timeout}s): {' '.join(cmd)}"


class OfflineInstaller:
    """オフライン同梱パッケージのインストーラー"""

    def __init__(self, project_root: Optional[str] = None):
        if project_root is None:
            project_root = str(
                Path(__file__).resolve().parent.parent.parent
            )
        self.project_root = Path(project_root)
        self.setup_dir = self.project_root / "setup"
        self.deb_dir = self.setup_dir / "deb"
        self.firmware_dir = self.setup_dir / "firmware"
        self.wheels_dir = self.setup_dir / "python_wheels"

    def install_system_deps(self, state: SetupState) -> InstallResult:
        """setup/deb/ の .deb パッケージをインストール"""
        result = InstallResult(
            component="system_deps",
            success=False,
            message="",
            installed_items=[],
            failed_items=[],
        )

        if not self.deb_dir.exists():
            result.message = "setup/deb/ ディレクトリが存在しません"
            return result

        deb_files = sorted(self.deb_dir.glob("*.deb"))
        if not deb_files:
            result.message = "setup/deb/ に .deb ファイルがありません"
            return result

        print(f"[SETUP] {len(deb_files)}個の.debパッケージをインストール中...")

        for deb in deb_files:
            # 既にインストール済みかチェック（パッケージ名を抽出）
            pkg_name = deb.stem.split("_")[0] if "_" in deb.stem else deb.stem
            rc, stdout, _ = _run_cmd(["dpkg", "-s", pkg_name])
            if rc == 0 and "Status: install ok installed" in stdout:
                result.installed_items.append(f"{pkg_name} (既存)")
                continue

            print(f"  Installing: {deb.name}")
            rc, stdout, stderr = _run_sudo(["dpkg", "-i", str(deb)])
            if rc == 0:
                result.installed_items.append(deb.name)
            else:
                # 依存関係エラーの場合は apt -f install で修復を試行
                rc2, _, stderr2 = _run_sudo(["apt-get", "-f", "install", "-y"])
                if rc2 == 0:
                    result.installed_items.append(f"{deb.name} (依存解決後)")
                else:
                    result.failed_items.append(f"{deb.name}: {stderr[:100]}")

        comp = state.get_component("system_deps")
        if not result.failed_items:
            result.success = True
            result.message = f"{len(result.installed_items)}個インストール完了"
            comp.mark_installed(version=f"{len(result.installed_items)} packages")
        else:
            result.message = (
                f"{len(result.installed_items)}個成功, "
                f"{len(result.failed_items)}個失敗"
            )
            comp.mark_failed(result.message)

        state.set_component(comp)
        return result

    def install_firmware(self, state: SetupState) -> InstallResult:
        """setup/firmware/ のファームウェアを /lib/firmware/ にコピー"""
        result = InstallResult(
            component="firmware",
            success=False,
            message="",
            installed_items=[],
            failed_items=[],
        )

        if not self.firmware_dir.exists():
            result.message = "setup/firmware/ ディレクトリが存在しません"
            return result

        fw_files = list(self.firmware_dir.glob("iwlwifi-*"))
        if not fw_files:
            result.message = "setup/firmware/ にファームウェアがありません"
            return result

        target_dir = Path("/lib/firmware")
        if not target_dir.exists():
            result.message = "/lib/firmware/ が存在しません"
            return result

        print(f"[SETUP] {len(fw_files)}個のファームウェアをコピー中...")

        for fw in fw_files:
            target = target_dir / fw.name
            if target.exists():
                result.installed_items.append(f"{fw.name} (既存)")
                continue

            print(f"  Copying: {fw.name}")
            rc, _, stderr = _run_sudo(["cp", str(fw), str(target)])
            if rc == 0:
                result.installed_items.append(fw.name)
            else:
                result.failed_items.append(f"{fw.name}: {stderr[:100]}")

        comp = state.get_component("firmware")
        if not result.failed_items:
            result.success = True
            result.message = f"{len(result.installed_items)}個コピー完了"
            comp.mark_installed(version=f"{len(fw_files)} files")
        else:
            result.message = (
                f"{len(result.installed_items)}個成功, "
                f"{len(result.failed_items)}個失敗"
            )
            comp.mark_failed(result.message)

        state.set_component(comp)
        return result

    def install_linux_headers(self, state: SetupState) -> InstallResult:
        """linux-headers をインストール（オフラインdeb → apt fallback）"""
        result = InstallResult(
            component="linux_headers",
            success=False,
            message="",
            installed_items=[],
            failed_items=[],
        )

        kernel = SetupStateManager.get_current_kernel()
        headers_path = Path(f"/lib/modules/{kernel}/build")

        if headers_path.exists():
            result.success = True
            result.message = f"linux-headers-{kernel} インストール済み"
            result.installed_items.append(f"linux-headers-{kernel}")
            comp = state.get_component("linux_headers")
            comp.mark_installed(version=kernel, kernel=kernel)
            state.set_component(comp)
            return result

        print(f"[SETUP] linux-headers-{kernel} をインストール中...")

        # 1. オフライン deb を探す
        if self.deb_dir.exists():
            header_debs = list(self.deb_dir.glob(f"linux-headers*{kernel}*.deb"))
            if header_debs:
                for deb in header_debs:
                    rc, _, stderr = _run_sudo(["dpkg", "-i", str(deb)])
                    if rc == 0:
                        result.installed_items.append(deb.name)

                if headers_path.exists():
                    result.success = True
                    result.message = f"オフラインからインストール完了"
                    comp = state.get_component("linux_headers")
                    comp.mark_installed(version=kernel, kernel=kernel)
                    state.set_component(comp)
                    return result

        # 2. apt install にフォールバック
        print(f"  オフラインパッケージなし。apt install を試行...")

        # Debian系ディストリで異なるパッケージ名を試行
        candidates = [
            f"linux-headers-{kernel}",
            "linux-headers-generic",
            "linux-headers-amd64",
        ]

        for pkg in candidates:
            rc, _, stderr = _run_sudo(
                ["apt-get", "install", "-y", pkg], timeout=300
            )
            if rc == 0 and headers_path.exists():
                result.success = True
                result.message = f"{pkg} をaptからインストール完了"
                result.installed_items.append(pkg)
                comp = state.get_component("linux_headers")
                comp.mark_installed(version=kernel, kernel=kernel)
                state.set_component(comp)
                return result

        result.message = (
            f"linux-headers-{kernel} のインストールに失敗。"
            "手動でインストールしてください。"
        )
        result.failed_items.append(f"linux-headers-{kernel}")
        comp = state.get_component("linux_headers")
        comp.mark_failed(result.message)
        state.set_component(comp)
        return result

    def install_python_deps(self, state: SetupState) -> InstallResult:
        """setup/python_wheels/ のPythonパッケージをインストール"""
        result = InstallResult(
            component="python_deps",
            success=False,
            message="",
            installed_items=[],
            failed_items=[],
        )

        # requirements.txt の存在確認
        req_file = self.project_root / "requirements.txt"

        # 1. wheels ディレクトリがある場合はオフラインインストール
        if self.wheels_dir.exists() and any(self.wheels_dir.glob("*.whl")):
            print("[SETUP] オフラインPythonパッケージをインストール中...")
            cmd = [
                sys.executable, "-m", "pip", "install",
                "--no-index",
                "--find-links", str(self.wheels_dir),
            ]
            if req_file.exists():
                cmd += ["-r", str(req_file)]
            else:
                # wheel ファイルを直接指定
                for whl in self.wheels_dir.glob("*.whl"):
                    cmd.append(str(whl))

            rc, stdout, stderr = _run_cmd(cmd, timeout=300)
            if rc == 0:
                result.success = True
                result.message = "オフラインPythonパッケージ インストール完了"
                result.installed_items.append("python_wheels (offline)")
            else:
                result.failed_items.append(f"pip offline: {stderr[:200]}")

        # 2. オフラインで失敗 or wheels がない場合は pip install にフォールバック
        if not result.success and req_file.exists():
            print("[SETUP] pip install (オンライン) を試行中...")
            rc, stdout, stderr = _run_cmd(
                [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
                timeout=300,
            )
            if rc == 0:
                result.success = True
                result.message = "Pythonパッケージ インストール完了 (online)"
                result.installed_items.append("requirements.txt (online)")
            else:
                result.failed_items.append(f"pip online: {stderr[:200]}")

        if not result.success and not req_file.exists():
            result.message = (
                "requirements.txt が見つかりません。"
                "Python依存パッケージの確認ができません。"
            )

        comp = state.get_component("python_deps")
        if result.success:
            comp.mark_installed()
        elif result.failed_items:
            comp.mark_failed("; ".join(result.failed_items))
        state.set_component(comp)
        return result

    def run_all(self, state: SetupState) -> List[InstallResult]:
        """全オフラインインストールを順次実行"""
        results = []

        steps = [
            ("システム依存パッケージ", self.install_system_deps),
            ("ファームウェア", self.install_firmware),
            ("Linux Headers", self.install_linux_headers),
            ("Python依存パッケージ", self.install_python_deps),
        ]

        for name, func in steps:
            print(f"\n{'='*50}")
            print(f"  {name}")
            print(f"{'='*50}")
            result = func(state)
            results.append(result)

            icon = "✅" if result.success else "❌"
            print(f"  {icon} {result.message}")

            if result.failed_items:
                for item in result.failed_items:
                    print(f"     ❌ {item}")

        return results


if __name__ == "__main__":
    manager = SetupStateManager()
    state_obj = manager.load()
    installer = OfflineInstaller()
    all_results = installer.run_all(state_obj)
    manager.save(state_obj)

    print("\n" + "=" * 50)
    print("  インストール結果サマリー")
    print("=" * 50)
    for r in all_results:
        icon = "✅" if r.success else "❌"
        print(f"  {icon} {r.component}: {r.message}")
