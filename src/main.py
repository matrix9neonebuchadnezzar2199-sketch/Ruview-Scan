"""
RuView Scan - CLI エントリポイント
(Phase F-0 改修: FeitCSI ベース環境自動構築・ブートシーケンス統合)
"""

import logging
import os
import sys
import json
import click
import uvicorn


def run_boot_sequence(simulate: bool, skip_setup: bool, logger) -> dict:
    """
    起動時ブートシーケンスを実行する
    - 環境チェック
    - オフラインインストール
    - FeitCSI ビルド
    - モニターモード起動
    Returns: BootResult の辞書表現
    """
    if simulate:
        logger.info("シミュレーションモード: ブートシーケンスをスキップ")
        return {
            "success": True,
            "simulation_mode": True,
            "feitcsi_available": False,
            "monitor_active": False,
            "message": "シミュレーションモードで起動",
        }

    if skip_setup:
        logger.info("--skip-setup: ブートシーケンスをスキップ")
        return {
            "success": True,
            "simulation_mode": False,
            "feitcsi_available": None,
            "monitor_active": None,
            "message": "セットアップスキップ",
        }

    try:
        from src.setup.boot_sequence import BootSequenceController
        controller = BootSequenceController()
        result = controller.run()

        # 結果をログ出力
        if result.success:
            logger.info(f"ブートシーケンス完了: FeitCSI={result.feitcsi_available}, "
                        f"Monitor={result.monitor_active}")
        else:
            logger.warning(f"ブートシーケンス警告: {result.message}")
            for err in result.errors:
                logger.warning(f"  - {err}")

        return {
            "success": result.success,
            "simulation_mode": result.simulation_mode,
            "feitcsi_available": result.feitcsi_available,
            "monitor_active": result.monitor_active,
            "message": result.message,
            "errors": result.errors,
            "env_summary": result.env_summary,
        }

    except ImportError as e:
        logger.warning(f"ブートシーケンスモジュール読み込み失敗: {e}")
        logger.info("セットアップモジュールなしで続行します")
        return {
            "success": True,
            "simulation_mode": False,
            "feitcsi_available": None,
            "monitor_active": None,
            "message": f"セットアップモジュール未検出: {e}",
        }
    except Exception as e:
        logger.error(f"ブートシーケンスエラー: {e}")
        return {
            "success": False,
            "simulation_mode": False,
            "feitcsi_available": False,
            "monitor_active": False,
            "message": f"ブートシーケンス失敗: {e}",
        }


@click.command()
@click.option('--host', default='127.0.0.1', help='ホストアドレス')
@click.option('--port', default=8080, type=int, help='ポート番号')
@click.option('--simulate', is_flag=True, default=False, help='シミュレーションモード')
@click.option('--feitcsi', is_flag=True, default=False, help='FeitCSI モードを強制')
@click.option('--skip-setup', is_flag=True, default=False, help='ブートシーケンスをスキップ')
@click.option('--log-level', default='INFO', help='ログレベル')
def main(host, port, simulate, feitcsi, skip_setup, log_level):
    """RuView Scan - Wi-Fi CSI 6面部屋スキャナー (FeitCSI 統合版)"""

    # ログ設定
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S',
    )
    logger = logging.getLogger("ruview")

    logger.info("=" * 60)
    logger.info("RuView Scan v2.0 - FeitCSI 統合版")
    logger.info("=" * 60)

    # src パッケージが見えるようにパスを設定
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # ---- ブートシーケンス実行 ----
    boot_result = run_boot_sequence(simulate, skip_setup, logger)

    # ---- CSI ソース決定 ----
    if simulate:
        os.environ['RUVIEW_CSI_SOURCE'] = 'simulate'
        logger.info("CSI ソース: simulate")
    elif feitcsi or (boot_result.get("feitcsi_available") is True):
        os.environ['RUVIEW_CSI_SOURCE'] = 'feitcsi'
        logger.info("CSI ソース: feitcsi")
    elif boot_result.get("feitcsi_available") is False:
        os.environ['RUVIEW_CSI_SOURCE'] = 'simulate'
        logger.warning("FeitCSI 利用不可 → シミュレーションモードにフォールバック")
    else:
        # skip-setup 等で不明な場合はデフォルト feitcsi を試行
        os.environ.setdefault('RUVIEW_CSI_SOURCE', 'feitcsi')
        logger.info(f"CSI ソース: {os.environ['RUVIEW_CSI_SOURCE']}")

    # ブート結果を環境変数で WebUI に渡す
    os.environ['RUVIEW_BOOT_RESULT'] = json.dumps(boot_result, ensure_ascii=False)

    logger.info(f"RuView Scan starting on http://{host}:{port}")

    # ---- アプリ起動 ----
    from src.api.server import create_app
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level=log_level.lower())


if __name__ == "__main__":
    main()