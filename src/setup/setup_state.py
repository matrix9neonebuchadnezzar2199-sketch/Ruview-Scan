"""
RuView Scan - Setup State Manager
構築状態の永続化・カーネル版追跡・ビルド状態管理

保存先: config/setup_state.json
"""
# ERR-F001: setup_state.py - 構築状態管理モジュール

import json
import os
import platform
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, List


class SetupStatus(str, Enum):
    """セットアップステータス"""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REBUILD = "needs_rebuild"


class ComponentStatus(str, Enum):
    """個別コンポーネントのステータス"""
    NOT_INSTALLED = "not_installed"
    INSTALLED = "installed"
    BUILD_FAILED = "build_failed"
    VERSION_MISMATCH = "version_mismatch"
    SKIPPED = "skipped"


@dataclass
class ComponentState:
    """個別コンポーネントの状態"""
    name: str
    status: str = ComponentStatus.NOT_INSTALLED
    version: str = ""
    installed_at: str = ""
    error_message: str = ""
    build_kernel: str = ""

    def mark_installed(self, version: str = "", kernel: str = ""):
        self.status = ComponentStatus.INSTALLED
        self.version = version
        self.installed_at = datetime.now(timezone.utc).isoformat()
        self.build_kernel = kernel
        self.error_message = ""

    def mark_failed(self, error: str):
        self.status = ComponentStatus.BUILD_FAILED
        self.error_message = error
        self.installed_at = datetime.now(timezone.utc).isoformat()

    def mark_skipped(self, reason: str = ""):
        self.status = ComponentStatus.SKIPPED
        self.error_message = reason

    def needs_rebuild(self, current_kernel: str) -> bool:
        if self.status != ComponentStatus.INSTALLED:
            return True
        if self.build_kernel and self.build_kernel != current_kernel:
            return True
        return False


@dataclass
class EnvironmentInfo:
    """検出された環境情報"""
    os_name: str = ""
    os_version: str = ""
    os_id: str = ""
    os_id_like: str = ""
    kernel_version: str = ""
    arch: str = ""
    cpu_model: str = ""
    cpu_cores: int = 0
    has_sse42: bool = False
    has_avx2: bool = False
    nic_detected: bool = False
    nic_model: str = ""
    nic_pci_id: str = ""
    firmware_present: bool = False
    firmware_path: str = ""


@dataclass
class SetupState:
    """構築状態の全体管理"""
    schema_version: int = 1
    first_setup_at: str = ""
    last_updated_at: str = ""
    setup_status: str = SetupStatus.NOT_STARTED
    environment: dict = field(default_factory=dict)
    components: dict = field(default_factory=dict)
    build_history: list = field(default_factory=list)

    def _ensure_defaults(self):
        default_components = [
            "system_deps",
            "firmware",
            "linux_headers",
            "feitcsi_iwlwifi",
            "feitcsi",
            "python_deps",
            "monitor_mode",
        ]
        for comp_name in default_components:
            if comp_name not in self.components:
                self.components[comp_name] = asdict(ComponentState(name=comp_name))

    def get_component(self, name: str) -> ComponentState:
        self._ensure_defaults()
        data = self.components.get(name, {"name": name})
        return ComponentState(**data)

    def set_component(self, comp: ComponentState):
        self.components[comp.name] = asdict(comp)
        self.last_updated_at = datetime.now(timezone.utc).isoformat()

    def add_build_record(self, kernel: str, status: str, message: str = ""):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kernel": kernel,
            "status": status,
            "message": message,
        }
        self.build_history.append(record)
        if len(self.build_history) > 5:
            self.build_history = self.build_history[-5:]

    def is_first_run(self) -> bool:
        return self.setup_status == SetupStatus.NOT_STARTED

    def is_completed(self) -> bool:
        return self.setup_status == SetupStatus.COMPLETED

    def needs_rebuild_for_kernel(self, current_kernel: str) -> bool:
        driver = self.get_component("feitcsi_iwlwifi")
        return driver.needs_rebuild(current_kernel)

    def get_summary(self) -> Dict[str, str]:
        self._ensure_defaults()
        summary = {}
        for name, data in self.components.items():
            comp = ComponentState(**data)
            summary[name] = comp.status
        return summary

    def all_components_ready(self) -> bool:
        self._ensure_defaults()
        for name, data in self.components.items():
            comp = ComponentState(**data)
            if comp.status not in (
                ComponentStatus.INSTALLED,
                ComponentStatus.SKIPPED,
            ):
                return False
        return True


class SetupStateManager:
    """setup_state.json の読み書きを管理"""

    def __init__(self, project_root: Optional[str] = None):
        if project_root is None:
            project_root = str(
                Path(__file__).resolve().parent.parent.parent
            )
        self.project_root = Path(project_root)
        self.config_dir = self.project_root / "config"
        self.state_file = self.config_dir / "setup_state.json"

    def load(self) -> SetupState:
        if not self.state_file.exists():
            state = SetupState()
            state._ensure_defaults()
            return state
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            state = SetupState(**data)
            state._ensure_defaults()
            return state
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            # ERR-F001: 状態ファイル破損時はバックアップして再生成
            backup_path = self.state_file.with_suffix(".json.bak")
            if self.state_file.exists():
                self.state_file.rename(backup_path)
            print(f"[WARN] setup_state.json corrupted. Backup: {backup_path}")
            print(f"[WARN] Detail: {e}")
            state = SetupState()
            state._ensure_defaults()
            return state

    def save(self, state: SetupState):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        state.last_updated_at = datetime.now(timezone.utc).isoformat()
        data = asdict(state)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def reset(self):
        if self.state_file.exists():
            backup_path = self.state_file.with_suffix(
                f".json.{int(time.time())}.bak"
            )
            self.state_file.rename(backup_path)
            print(f"[INFO] State reset. Backup: {backup_path}")

    @staticmethod
    def get_current_kernel() -> str:
        try:
            result = subprocess.run(
                ["uname", "-r"],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            return platform.release()

    @staticmethod
    def get_current_arch() -> str:
        return platform.machine()

    @staticmethod
    def detect_os_info() -> Dict[str, str]:
        info = {
            "os_name": "",
            "os_version": "",
            "os_id": "",
            "os_id_like": "",
        }
        os_release = Path("/etc/os-release")
        if not os_release.exists():
            info["os_name"] = platform.system()
            info["os_version"] = platform.version()
            return info
        try:
            with open(os_release, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("PRETTY_NAME="):
                        info["os_name"] = line.split("=", 1)[1].strip('"')
                    elif line.startswith("VERSION_ID="):
                        info["os_version"] = line.split("=", 1)[1].strip('"')
                    elif line.startswith("ID="):
                        info["os_id"] = line.split("=", 1)[1].strip('"')
                    elif line.startswith("ID_LIKE="):
                        info["os_id_like"] = line.split("=", 1)[1].strip('"')
        except OSError:
            info["os_name"] = platform.system()
            info["os_version"] = platform.version()
        return info


if __name__ == "__main__":
    manager = SetupStateManager()
    state = manager.load()
    print(f"First run: {state.is_first_run()}")
    print(f"Kernel: {manager.get_current_kernel()}")
    print(f"Arch: {manager.get_current_arch()}")
    print(f"OS: {manager.detect_os_info()}")
    print(f"Components:")
    for name, status in state.get_summary().items():
        print(f"  {name}: {status}")
    if state.is_first_run():
        state.first_setup_at = datetime.now(timezone.utc).isoformat()
        state.setup_status = SetupStatus.IN_PROGRESS
        manager.save(state)
        print(f"\nState saved: {manager.state_file}")
