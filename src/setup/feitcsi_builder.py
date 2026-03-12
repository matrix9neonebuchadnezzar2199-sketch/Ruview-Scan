"""
RuView Scan - FeitCSI Builder
FeitCSI ドライバとメインプログラムのソースビルドを自動化する

ビルド対象:
  1. FeitCSI-iwlwifi（カスタムiwlwifiドライバ）→ dkms経由で自動再コンパイル対応
  2. FeitCSI（CSI測定メインプログラム）

ソース配置先: setup/feitcsi/FeitCSI-iwlwifi/ , setup/feitcsi/FeitCSI/
"""
# ERR-F004: feitcsi_builder.py - FeitCSIビルドモジュール

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List

from .setup_state import (
    SetupStateManager, SetupState,
    ComponentState, ComponentStatus,
)


def _run_cmd(
    cmd: List[str],
    cwd: Optional[str] = None,
    timeout: int = 600,
    use_sudo: bool = False,
) -> Tuple[int, str, str]:
    """コマンド実行ヘルパー"""
    full_cmd = (["sudo"] + cmd) if use_sudo else cmd
    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env={**os.environ, "LANG": "C", "LC_ALL": "C"},
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return -1, "", f"Command not found: {full_cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", f"Build timed out ({timeout}s)"


class FeitCSIBuilder:
    """FeitCSI のソースビルドを管理"""

    def __init__(self, project_root: Optional[str] = None):
        if project_root is None:
            project_root = str(
                Path(__file__).resolve().parent.parent.parent
            )
        self.project_root = Path(project_root)
        self.setup_dir = self.project_root / "setup"
        self.feitcsi_dir = self.setup_dir / "feitcsi"
        self.driver_src = self.feitcsi_dir / "FeitCSI-iwlwifi"
        self.main_src = self.feitcsi_dir / "FeitCSI"

    def check_sources_exist(self) -> dict:
        """ソースコードの存在確認"""
        return {
            "driver_src": self.driver_src.exists(),
            "driver_makefile": (self.driver_src / "Makefile").exists(),
            "main_src": self.main_src.exists(),
            "main_makefile": (self.main_src / "Makefile").exists(),
        }

    def check_build_prerequisites(self) -> Tuple[bool, List[str]]:
        """ビルドの前提条件を確認"""
        missing = []

        # 必須コマンド
        for cmd in ["make", "gcc", "dkms"]:
            if not shutil.which(cmd):
                missing.append(cmd)

        # linux-headers
        kernel = SetupStateManager.get_current_kernel()
        headers_path = Path(f"/lib/modules/{kernel}/build")
        if not headers_path.exists():
            missing.append(f"linux-headers-{kernel}")

        # FeitCSI メインプログラムの依存ライブラリ
        lib_checks = [
            ("/usr/include/gtkmm-3.0", "libgtkmm-3.0-dev"),
            ("/usr/include/libnl3/netlink", "libnl-genl-3-dev"),
            ("/usr/include/iwlib.h", "libiw-dev"),
            ("/usr/include/pcap/pcap.h", "libpcap-dev"),
        ]
        for path, pkg in lib_checks:
            if not Path(path).exists():
                missing.append(pkg)

        return len(missing) == 0, missing

    def build_driver(self, state: SetupState) -> bool:
        """FeitCSI-iwlwifi ドライバをビルド＆インストール"""
        comp = state.get_component("feitcsi_iwlwifi")
        kernel = SetupStateManager.get_current_kernel()

        print(f"[BUILD] FeitCSI-iwlwifi ドライバ ビルド開始")
        print(f"        カーネル: {kernel}")
        print(f"        ソース:   {self.driver_src}")

        if not self.driver_src.exists():
            comp.mark_failed("ドライバソースが見つかりません")
            state.set_component(comp)
            print(f"  ❌ {self.driver_src} が存在しません")
            return False

        # カーネル版が一致していればスキップ
        if (comp.status == ComponentStatus.INSTALLED
                and comp.build_kernel == kernel):
            print(f"  ⏭️  カーネル {kernel} 用ビルド済み。スキップ。")
            return True

        # Step 1: make defconfig-iwlwifi-public
        print("  [1/3] make defconfig-iwlwifi-public")
        rc, stdout, stderr = _run_cmd(
            ["make", "defconfig-iwlwifi-public"],
            cwd=str(self.driver_src),
        )
        if rc != 0:
            comp.mark_failed(f"defconfig失敗: {stderr[:200]}")
            state.set_component(comp)
            state.add_build_record(kernel, "failed", f"defconfig: {stderr[:100]}")
            print(f"  ❌ defconfig失敗: {stderr[:200]}")
            return False

        # Step 2: make
        print("  [2/3] make (コンパイル中...)")
        cpu_count = os.cpu_count() or 2
        rc, stdout, stderr = _run_cmd(
            ["make", f"-j{cpu_count}"],
            cwd=str(self.driver_src),
            timeout=600,
        )
        if rc != 0:
            comp.mark_failed(f"make失敗: {stderr[:200]}")
            state.set_component(comp)
            state.add_build_record(kernel, "failed", f"make: {stderr[:100]}")
            print(f"  ❌ make失敗: {stderr[:200]}")
            return False

        # Step 3: sudo make install
        print("  [3/3] sudo make install")
        rc, stdout, stderr = _run_cmd(
            ["make", "install"],
            cwd=str(self.driver_src),
            use_sudo=True,
        )
        if rc != 0:
            comp.mark_failed(f"install失敗: {stderr[:200]}")
            state.set_component(comp)
            state.add_build_record(kernel, "failed", f"install: {stderr[:100]}")
            print(f"  ❌ install失敗: {stderr[:200]}")
            return False

        comp.mark_installed(version="2.0.0", kernel=kernel)
        state.set_component(comp)
        state.add_build_record(kernel, "success", "driver build ok")
        print(f"  ✅ ドライバビルド＆インストール完了 (kernel: {kernel})")
        return True

    def build_main(self, state: SetupState) -> bool:
        """FeitCSI メインプログラムをビルド＆インストール"""
        comp = state.get_component("feitcsi")

        print(f"[BUILD] FeitCSI メインプログラム ビルド開始")
        print(f"        ソース: {self.main_src}")

        if not self.main_src.exists():
            comp.mark_failed("メインソースが見つかりません")
            state.set_component(comp)
            print(f"  ❌ {self.main_src} が存在しません")
            return False

        # 既にインストール済みかチェック
        if shutil.which("feitcsi") and comp.status == ComponentStatus.INSTALLED:
            print("  ⏭️  FeitCSI 既にインストール済み。スキップ。")
            return True

        # Step 1: make
        print("  [1/2] make (コンパイル中...)")
        cpu_count = os.cpu_count() or 2
        rc, stdout, stderr = _run_cmd(
            ["make", f"-j{cpu_count}"],
            cwd=str(self.main_src),
            timeout=300,
        )
        if rc != 0:
            comp.mark_failed(f"make失敗: {stderr[:200]}")
            state.set_component(comp)
            print(f"  ❌ make失敗: {stderr[:200]}")
            return False

        # Step 2: sudo make install
        print("  [2/2] sudo make install")
        rc, stdout, stderr = _run_cmd(
            ["make", "install"],
            cwd=str(self.main_src),
            use_sudo=True,
        )
        if rc != 0:
            comp.mark_failed(f"install失敗: {stderr[:200]}")
            state.set_component(comp)
            print(f"  ❌ install失敗: {stderr[:200]}")
            return False

        comp.mark_installed(version="2.0.0")
        state.set_component(comp)
        print("  ✅ FeitCSI メインプログラム ビルド＆インストール完了")
        return True

    def build_from_deb(self, state: SetupState) -> bool:
        """deb パッケージからインストール（ソースビルドの代替）"""
        deb_dir = self.setup_dir / "deb"

        # feitcsi-iwlwifi deb
        driver_debs = list(deb_dir.glob("feitcsi-iwlwifi*.deb"))
        if driver_debs:
            print(f"[BUILD] feitcsi-iwlwifi を deb からインストール")
            deb_path = driver_debs[0]
            rc, _, stderr = _run_cmd(
                ["apt", "install", str(deb_path), "-y"],
                use_sudo=True,
                timeout=300,
            )
            if rc == 0:
                kernel = SetupStateManager.get_current_kernel()
                comp = state.get_component("feitcsi_iwlwifi")
                comp.mark_installed(version="2.0.0-deb", kernel=kernel)
                state.set_component(comp)
                print(f"  ✅ ドライバ deb インストール完了")
            else:
                print(f"  ❌ ドライバ deb インストール失敗: {stderr[:200]}")
                return False

        # feitcsi メイン deb
        main_debs = list(deb_dir.glob("feitcsi_*.deb"))
        if main_debs:
            print(f"[BUILD] feitcsi を deb からインストール")
            deb_path = main_debs[0]
            rc, _, stderr = _run_cmd(
                ["apt", "install", str(deb_path), "-y"],
                use_sudo=True,
                timeout=300,
            )
            if rc == 0:
                comp = state.get_component("feitcsi")
                comp.mark_installed(version="2.0.0-deb")
                state.set_component(comp)
                print(f"  ✅ FeitCSI deb インストール完了")
            else:
                print(f"  ❌ FeitCSI deb インストール失敗: {stderr[:200]}")
                return False

        return True

    def build_all(self, state: SetupState) -> bool:
        """FeitCSI 全体をビルド。deb → ソースの優先順で試行"""
        kernel = SetupStateManager.get_current_kernel()

        print(f"\n{'='*50}")
        print(f"  FeitCSI ビルドパイプライン")
        print(f"  カーネル: {kernel}")
        print(f"{'='*50}")

        # 前提条件チェック
        prereq_ok, missing = self.check_build_prerequisites()
        if not prereq_ok:
            print(f"  ⚠️  前提条件未充足: {', '.join(missing)}")
            print(f"  オフラインパッケージで解決を試行...")

        # ソース存在チェック
        sources = self.check_sources_exist()

        # 戦略1: deb パッケージがあればそれを優先
        deb_dir = self.setup_dir / "deb"
        has_driver_deb = deb_dir.exists() and any(
            deb_dir.glob("feitcsi-iwlwifi*.deb")
        )
        has_main_deb = deb_dir.exists() and any(
            deb_dir.glob("feitcsi_*.deb")
        )

        if has_driver_deb and has_main_deb:
            print("\n[戦略1] deb パッケージからインストール")
            if self.build_from_deb(state):
                return True
            print("  deb インストール失敗。ソースビルドにフォールバック。")

        # 戦略2: ソースからビルド
        if sources["driver_src"] and sources["main_src"]:
            print("\n[戦略2] ソースコードからビルド")

            if not prereq_ok:
                print(f"  ❌ ビルド前提条件が不足: {', '.join(missing)}")
                print(f"  先に offline_installer でパッケージをインストールしてください")
                return False

            driver_ok = self.build_driver(state)
            if not driver_ok:
                print("  ❌ ドライバビルド失敗。続行不可。")
                return False

            main_ok = self.build_main(state)
            if not main_ok:
                print("  ❌ メインプログラムビルド失敗。")
                return False

            return True

        # どちらもない
        print("\n  ❌ FeitCSI のソースもdebも見つかりません。")
        print("  setup/feitcsi/ にソースを配置するか、")
        print("  setup/deb/ に .deb パッケージを配置してください。")
        print("  ダウンロード: https://github.com/KuskoSoft/FeitCSI/releases")
        return False

    def reload_driver(self) -> bool:
        """ドライバを再ロード"""
        print("[DRIVER] iwlwifi ドライバを再ロード中...")

        # アンロード
        rc, _, _ = _run_cmd(["modprobe", "-r", "iwlmvm"], use_sudo=True)
        rc, _, _ = _run_cmd(["modprobe", "-r", "iwlwifi"], use_sudo=True)

        # ロード
        rc, _, stderr = _run_cmd(["modprobe", "iwlwifi"], use_sudo=True)
        if rc != 0:
            print(f"  ❌ ドライバロード失敗: {stderr[:200]}")
            return False

        print("  ✅ ドライバ再ロード完了")
        return True


if __name__ == "__main__":
    manager = SetupStateManager()
    state_obj = manager.load()
    builder = FeitCSIBuilder()

    print("ソース存在確認:")
    for k, v in builder.check_sources_exist().items():
        print(f"  {k}: {'✅' if v else '❌'}")

    prereq_ok, missing = builder.check_build_prerequisites()
    print(f"\n前提条件: {'✅ OK' if prereq_ok else '❌ 不足'}")
    if missing:
        print(f"  不足: {', '.join(missing)}")

    manager.save(state_obj)
