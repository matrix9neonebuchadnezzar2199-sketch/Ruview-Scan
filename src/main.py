"""
RuView Scan - CLI エントリポイント
"""

import logging
import os
import sys
import click
import uvicorn


@click.command()
@click.option('--host', default='127.0.0.1', help='ホストアドレス')
@click.option('--port', default=8080, type=int, help='ポート番号')
@click.option('--simulate', is_flag=True, default=False, help='シミュレーションモード')
@click.option('--log-level', default='INFO', help='ログレベル')
def main(host, port, simulate, log_level):
    """RuView Scan - Wi-Fi CSI 6面部屋スキャナー"""

    # ログ設定
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S',
    )
    logger = logging.getLogger("ruview")

    # シミュレーションモードの場合は環境変数で設定
    if simulate:
        os.environ['RUVIEW_CSI_SOURCE'] = 'simulate'
        logger.info("シミュレーションモードで起動します")

    logger.info(f"RuView Scan starting on http://{host}:{port}")

    # src パッケージが見えるようにパスを設定
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from src.api.server import create_app
    app = create_app()

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level.lower(),
    )


if __name__ == '__main__':
    main()
