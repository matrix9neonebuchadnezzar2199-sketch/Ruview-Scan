"""
RuView Scan - Boot Sequence Controller
起動シーケンス全体を制御するオーケストレーター

起動フロー:
  1. setup_state.json 読み込み → 初回/再ビルド/通常を判定
  2. 環境チェック（env_checker）
  3. 自動修復（offline_installer）
  4. FeitCSI ビルド（feitcsi_builder）
  5. モニターモード設定（monitor_setup）
  6. 結果レポート → WebUI or CLI 表示
"""
# ERR-F006: boot_sequence.py - 起動シーケンス制御モジュール

import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from .setup_state import (
    SetupStateManager, SetupState, SetupStatus,
)
from .env_checker import (
    EnvironmentChecker, EnvironmentCheckReport,
    CheckResult, print_report,
)
from .offline_installer import OfflineInstaller
from .feitcsi_builder import FeitCSIBuilder
from .monitor_setup import MonitorSetup


@dataclass
class BootResult:
    """起動シーケンスの結果"""
    success: bool = False
    simulation_mode: bool = False
    feitcsi_available: bool = False
    monitor_active: bool = False
    udp_port: int = 0
    interface: str = ""
    message: str = ""
    env_report: dict = None
    monitor_status: dict = None


class BootSequence:
    """起動シーケンスのオーケストレーター"""

    def __init__(self, project_root: Optional[str] = None):
        if project_root is None:
            project_root = str(
                Path(__file__).resolve().parent.parent.parent
            )
        self.project_root = Path(project_root)
        self.state_manager = SetupStateManager(str(self.project_root))
        self.env_checker = EnvironmentChecker(str(self.project_root))
        self.offline_installer = OfflineInstaller(str(self.project_root))
        self.feitcsi_builder = FeitCSIBuilder(str(self.project_root))
        self.monitor_setup = MonitorSetup()

    def run(self, force_setup: bool = False, verbose: bool = True) -> BootResult:
        """起動シーケンスを実行"""
        result = BootResult()
        state = self.state_manager.load()
        kernel = SetupStateManager.get_current_kernel()

        if verbose:
            print()
            print("=" * 60)
            print("  RuView Scan - Boot Sequence")
            print("=" * 60)
            print(f"  カーネル: {kernel}")
            print()

        # === Phase 1: 状態判定 ===
        need_setup = (
            force_setup
            or state.is_first_run()
            or state.needs_rebuild_for_kernel(kernel)
        )

        if need_setup:
            reason = "初回セットアップ"
            if force_setup:
                reason = "強制セットアップ"
            elif state.needs_rebuild_for_kernel(kernel):
                reason = f"カーネル変更検出 (ビルド済み: {state.get_component('feitcsi_iwlwifi').build_kernel} → 現在: {kernel})"

            if verbose:
                print(f"[PHASE 1] セットアップ必要: {reason}")

            result = self._run_full_setup(state, kernel, verbose)
        else:
            if verbose:
                print("[PHASE 1] 構築済み環境。クイックチェック実行。")

            result = self._run_quick_check(state, kernel, verbose)

        # 状態保存
        self.state_manager.save(state)

        if verbose:
            print()
            print("=" * 60)
            print("  起動シーケンス完了")
            print(f"  モード: {'シミュレーション' if result.simulation_mode else '実機スキャン'}")
            print(f"  FeitCSI: {'利用可能' if result.feitcsi_available else '未利用'}")
            print(f"  結果: {result.message}")
            print("=" * 60)
            print()

        return result

    def _run_full_setup(
        self, state: SetupState, kernel: str, verbose: bool
    ) -> BootResult:
        """フルセットアップを実行"""
        result = BootResult()
        state.setup_status = SetupStatus.IN_PROGRESS

        # === Phase 2: 環境チェック ===
        if verbose:
            print("\n[PHASE 2] 環境チェック")
        env_report = self.env_checker.run_all_checks()
        result.env_report = asdict(env_report)

        if verbose:
            print_report(env_report)

        # === Phase 3: オフラインインストール ===
        if verbose:
            print("\n[PHASE 3] オフラインパッケージ インストール")

        install_results = self.offline_installer.run_all(state)

        # === Phase 4: FeitCSI ビルド ===
        if verbose:
            print("\n[PHASE 4] FeitCSI ビルド")

        feitcsi_ok = self.feitcsi_builder.build_all(state)
        result.feitcsi_available = feitcsi_ok

        # === Phase 5: モニターモード設定 ===
        if verbose:
            print("\n[PHASE 5] モニターモード設定")

        monitor_status = self.monitor_setup.full_setup(state)
        result.monitor_status = self.monitor_setup.get_status_dict()
        result.interface = monitor_status.interface_name
        result.monitor_active = monitor_status.feitcsi_running
        result.udp_port = 8008 if monitor_status.udp_responsive else 0

        # === 結果判定 ===
        if monitor_status.feitcsi_running and monitor_status.udp_responsive:
            result.success = True
            result.simulation_mode = False
            result.message = "実機スキャンモードで起動準備完了"
            state.setup_status = SetupStatus.COMPLETED
        elif not monitor_status.interface_name:
            result.success = True
            result.simulation_mode = True
            result.message = "NIC未検出。シミュレーションモードで起動"
            state.setup_status = SetupStatus.COMPLETED
        else:
            result.success = True
            result.simulation_mode = True
            result.message = "セットアップ部分完了。シミュレーションモードで起動"
            state.setup_status = SetupStatus.COMPLETED

        state.add_build_record(
            kernel=kernel,
            status="success" if result.success else "partial",
            message=result.message,
        )

        return result

    def _run_quick_check(
        self, state: SetupState, kernel: str, verbose: bool
    ) -> BootResult:
        """クイックチェック（構築済み環境の起動時）"""
        result = BootResult()

        # 環境チェック（軽量）
        env_report = self.env_checker.run_all_checks()
        result.env_report = asdict(env_report)

        if verbose:
            print_report(env_report)

        # FeitCSI の存在確認
        import shutil
        result.feitcsi_available = shutil.which("feitcsi") is not None

        # モニターモード起動
        if result.feitcsi_available:
            if verbose:
                print("\n[QUICK] モニターモード設定")
            monitor_status = self.monitor_setup.full_setup(state)
            result.monitor_status = self.monitor_setup.get_status_dict()
            result.interface = monitor_status.interface_name
            result.monitor_active = monitor_status.feitcsi_running
            result.udp_port = 8008 if monitor_status.udp_responsive else 0

        # 結果判定
        nic_check = next(
            (c for c in env_report.checks if c["id"] == "nic"), None
        )
        nic_ok = nic_check and nic_check["result"] == CheckResult.OK

        if result.monitor_active:
            result.success = True
            result.simulation_mode = False
            result.message = "実機スキャンモードで起動"
        elif not nic_ok:
            result.success = True
            result.simulation_mode = True
            result.message = "NIC未検出。シミュレーションモードで起動"
        else:
            result.success = True
            result.simulation_mode = True
            result.message = "FeitCSI起動失敗。シミュレーションモードで起動"

        return result

    def shutdown(self):
        """終了処理"""
        self.monitor_setup.stop_feitcsi_service()

    def get_status(self) -> dict:
        """現在の状態をWebUI用に返す"""
        state = self.state_manager.load()
        return {
            "setup_status": state.setup_status,
            "components": state.get_summary(),
            "monitor": self.monitor_setup.get_status_dict(),
            "kernel": SetupStateManager.get_current_kernel(),
            "all_ready": state.all_components_ready(),
        }


# === CLI エントリポイント ===
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RuView Scan Boot Sequence")
    parser.add_argument(
        "--setup", action="store_true",
        help="強制的にフルセットアップを実行"
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="環境チェックのみ実行（インストールしない）"
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="構築状態をリセット"
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="出力を最小限に抑える"
    )
    args = parser.parse_args()

    boot = BootSequence()

    if args.reset:
        boot.state_manager.reset()
        print("構築状態をリセットしました。")
        sys.exit(0)

    if args.check_only:
        checker = EnvironmentChecker()
        report = checker.run_all_checks()
        print_report(report)
        sys.exit(0 if report.can_proceed else 1)

    try:
        boot_result = boot.run(
            force_setup=args.setup,
            verbose=not args.quiet,
        )
        if boot_result.success:
            print("起動準備完了。WebUI を開始できます。")
        else:
            print("起動準備に問題があります。上記のエラーを確認してください。")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n中断されました。")
        boot.shutdown()
        sys.exit(130)
