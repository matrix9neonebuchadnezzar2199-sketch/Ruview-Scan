#!/bin/bash
# =============================================================================
# RuView Scan - 起動スクリプト
# =============================================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# デフォルト設定
HOST="127.0.0.1"
PORT=8080
SIMULATE=false
LOG_LEVEL="INFO"

# 引数パース
while [[ $# -gt 0 ]]; do
    case "$1" in
        --simulate) SIMULATE=true; shift ;;
        --host)     HOST="$2"; shift 2 ;;
        --port)     PORT="$2"; shift 2 ;;
        --debug)    LOG_LEVEL="DEBUG"; shift ;;
        --help)
            echo "Usage: $0 [options]"
            echo "  --simulate    シミュレーションモードで起動"
            echo "  --host HOST   リッスンアドレス (default: 127.0.0.1)"
            echo "  --port PORT   リッスンポート (default: 8080)"
            echo "  --debug       デバッグログを有効化"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Python仮想環境
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# PYTHONPATH設定
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# 起動
echo "=============================================="
echo " RuView Scan v1.0"
echo "=============================================="
echo " Host: $HOST:$PORT"
echo " Simulate: $SIMULATE"
echo " Log Level: $LOG_LEVEL"
echo "=============================================="

ARGS="--host $HOST --port $PORT --log-level $LOG_LEVEL"
if [ "$SIMULATE" = true ]; then
    ARGS="$ARGS --simulate"
fi

python -m src.main $ARGS
