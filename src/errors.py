"""
RuView Scan - カスタム例外定義
=================================
エラーコード体系:
  E-NIC-xxx  : NIC関連エラー
  E-CSI-xxx  : CSIデータ取得・解析エラー
  E-CAL-xxx  : キャリブレーション関連エラー
  E-SCAN-xxx : スキャンセッション関連エラー
  E-ROOM-xxx : 部屋推定関連エラー
  E-MAP-xxx  : 反射マップ関連エラー
  E-DET-xxx  : 検出エンジンエラー
  E-RF-xxx   : RFスキャンエラー
  E-API-xxx  : APIサーバーエラー
  E-CFG-xxx  : 設定関連エラー
"""

from typing import Optional


class RuViewError(Exception):
    """RuView Scan 基底例外クラス"""

    def __init__(self, code: str, message: str, detail: Optional[str] = None,
                 remedy: Optional[str] = None):
        self.code = code
        self.message = message
        self.detail = detail
        self.remedy = remedy
        super().__init__(self.format())

    def format(self) -> str:
        parts = [f"[{self.code}] {self.message}"]
        if self.detail:
            parts.append(f"  詳細: {self.detail}")
        if self.remedy:
            parts.append(f"  対処: {self.remedy}")
        return "\n".join(parts)


# ===== NIC関連 =====

class NICNotFoundError(RuViewError):
    """E-NIC-001: Wi-Fi NICが見つからない"""
    def __init__(self, detail: str = ""):
        super().__init__(
            code="E-NIC-001",
            message="Wi-Fi NICが検出できません",
            detail=detail or "lspci / lsusb でNICが見つかりませんでした",
            remedy="Intel AX210/AX211/AX200/AX201 搭載のNICを接続してください"
        )


class NICNotCSICapableError(RuViewError):
    """E-NIC-002: NICがCSI非対応"""
    def __init__(self, nic_name: str):
        super().__init__(
            code="E-NIC-002",
            message=f"NIC '{nic_name}' はCSI取得に対応していません",
            detail="CSI対応NIC: Intel AX210, AX211, AX200, AX201, IWL5300, QCA9300",
            remedy="Intel AX210搭載のUSBアダプタ ($30-50) を追加してください"
        )


class MonitorModeError(RuViewError):
    """E-NIC-003: モニターモード移行失敗"""
    def __init__(self, interface: str, detail: str = ""):
        super().__init__(
            code="E-NIC-003",
            message=f"インターフェース '{interface}' をモニターモードに設定できません",
            detail=detail or "ドライバまたは権限の問題の可能性があります",
            remedy="sudo での実行を確認し、airmon-ng check kill を試してください"
        )


class NICBusyError(RuViewError):
    """E-NIC-004: NICが他プロセスで使用中"""
    def __init__(self, interface: str, processes: str = ""):
        super().__init__(
            code="E-NIC-004",
            message=f"インターフェース '{interface}' が他のプロセスで使用中です",
            detail=f"競合プロセス: {processes}" if processes else None,
            remedy="airmon-ng check kill を実行してからやり直してください"
        )


# ===== CSI関連 =====

class CSISourceError(RuViewError):
    """E-CSI-001: CSIソース接続失敗"""
    def __init__(self, source: str, detail: str = ""):
        super().__init__(
            code="E-CSI-001",
            message=f"CSIソース '{source}' に接続できません",
            detail=detail,
            remedy="PicoScenes/IAXが起動しているか、UDPポートを確認してください"
        )


class CSIParseError(RuViewError):
    """E-CSI-002: CSIデータのパース失敗"""
    def __init__(self, detail: str = ""):
        super().__init__(
            code="E-CSI-002",
            message="CSIデータの解析に失敗しました",
            detail=detail,
            remedy="CSIソースのフォーマットと設定を確認してください"
        )


class CSINoDataError(RuViewError):
    """E-CSI-003: CSIデータが受信できない"""
    def __init__(self, timeout_sec: float = 0):
        super().__init__(
            code="E-CSI-003",
            message="CSIデータが受信できません",
            detail=f"{timeout_sec}秒間データを受信できませんでした" if timeout_sec else None,
            remedy="Wi-Fi APが電波を送信しているか、NICの周波数/チャネル設定を確認してください"
        )


class CSISubcarrierError(RuViewError):
    """E-CSI-004: サブキャリア数の不整合"""
    def __init__(self, expected: int, actual: int):
        super().__init__(
            code="E-CSI-004",
            message=f"サブキャリア数が想定と異なります (期待: {expected}, 実際: {actual})",
            detail="帯域幅設定またはCSIソースの構成が不一致の可能性があります",
            remedy="config.yaml の bandwidth 設定とCSIソースの帯域幅を揃えてください"
        )


# ===== キャリブレーション関連 =====

class CalibrationError(RuViewError):
    """E-CAL-001: キャリブレーション失敗"""
    def __init__(self, detail: str = ""):
        super().__init__(
            code="E-CAL-001",
            message="キャリブレーションに失敗しました",
            detail=detail,
            remedy="安定したCSIデータが取得できる環境で再実行してください"
        )


class CalibrationUnstableError(RuViewError):
    """E-CAL-002: キャリブレーション中のCSIが不安定"""
    def __init__(self, variance: float, threshold: float):
        super().__init__(
            code="E-CAL-002",
            message="キャリブレーション中のCSIが不安定です",
            detail=f"分散: {variance:.4f} (閾値: {threshold:.4f})",
            remedy="人の移動を止め、部屋を静止状態にしてから再キャリブレーションしてください"
        )


# ===== スキャンセッション関連 =====

class ScanSessionError(RuViewError):
    """E-SCAN-001: スキャンセッション関連エラー"""
    def __init__(self, detail: str = ""):
        super().__init__(
            code="E-SCAN-001",
            message="スキャンセッションエラーが発生しました",
            detail=detail,
            remedy="スキャンをリセットしてやり直してください"
        )


class ScanPointError(RuViewError):
    """E-SCAN-002: 計測点エラー"""
    def __init__(self, point_id: str, detail: str = ""):
        super().__init__(
            code="E-SCAN-002",
            message=f"計測点 '{point_id}' でエラーが発生しました",
            detail=detail,
            remedy="該当計測点のスキャンをやり直してください"
        )


class ScanAlreadyRunningError(RuViewError):
    """E-SCAN-003: スキャンが既に実行中"""
    def __init__(self):
        super().__init__(
            code="E-SCAN-003",
            message="スキャンが既に実行中です",
            detail="別の計測点のスキャンが進行中です",
            remedy="現在のスキャン完了を待つか、リセットしてください"
        )


# ===== 部屋推定関連 =====

class RoomEstimationError(RuViewError):
    """E-ROOM-001: 部屋寸法推定エラー"""
    def __init__(self, detail: str = ""):
        super().__init__(
            code="E-ROOM-001",
            message="部屋寸法の推定に失敗しました",
            detail=detail,
            remedy="全5箇所のスキャンが完了しているか確認してください"
        )


class InsufficientDataError(RuViewError):
    """E-ROOM-002: データ不足"""
    def __init__(self, required: int, actual: int):
        super().__init__(
            code="E-ROOM-002",
            message="推定に必要なデータが不足しています",
            detail=f"必要計測点: {required}, 完了: {actual}",
            remedy="残りの計測点のスキャンを完了してください"
        )


# ===== 反射マップ関連 =====

class ReflectionMapError(RuViewError):
    """E-MAP-001: 反射マップ生成エラー"""
    def __init__(self, detail: str = ""):
        super().__init__(
            code="E-MAP-001",
            message="反射マップの生成に失敗しました",
            detail=detail,
            remedy="CSIデータとスキャン結果を確認してください"
        )


# ===== 検出エンジン関連 =====

class DetectionEngineError(RuViewError):
    """E-DET-001: 検出エンジンの初期化失敗"""
    def __init__(self, detail: str = ""):
        super().__init__(
            code="E-DET-001",
            message="検出エンジンの初期化に失敗しました",
            detail=detail,
            remedy="反射マップが正常に生成されているか確認してください"
        )


# ===== RFスキャン関連 =====

class RFScanError(RuViewError):
    """E-RF-001: RFスキャン実行失敗"""
    def __init__(self, detail: str = ""):
        super().__init__(
            code="E-RF-001",
            message="RFスキャンの実行に失敗しました",
            detail=detail,
            remedy="sudo権限とインターフェース状態を確認してください"
        )


class RFScanPermissionError(RuViewError):
    """E-RF-002: RFスキャンの権限不足"""
    def __init__(self):
        super().__init__(
            code="E-RF-002",
            message="RFスキャンにroot権限が必要です",
            detail="iw dev scan にはCAP_NET_ADMINが必要です",
            remedy="sudo ruview.sh で起動してください"
        )


# ===== API関連 =====

class APIStartError(RuViewError):
    """E-API-001: APIサーバー起動失敗"""
    def __init__(self, port: int, detail: str = ""):
        super().__init__(
            code="E-API-001",
            message=f"APIサーバーをポート {port} で起動できません",
            detail=detail,
            remedy=f"ポート {port} が使用中でないか確認してください"
        )


# ===== 設定関連 =====

class ConfigError(RuViewError):
    """E-CFG-001: 設定ファイル読み込みエラー"""
    def __init__(self, path: str, detail: str = ""):
        super().__init__(
            code="E-CFG-001",
            message="設定ファイルの読み込みに失敗しました",
            detail=f"パス: {path} / {detail}",
            remedy="config/default.yaml が正しいYAML形式であることを確認してください"
        )
