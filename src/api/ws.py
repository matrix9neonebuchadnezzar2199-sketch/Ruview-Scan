"""
RuView Scan - WebSocket スキャン進捗ストリーム
"""

import asyncio
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.server import state

logger = logging.getLogger(__name__)
ws_router = APIRouter()

# 接続中のWebSocketクライアント
_clients: Set[WebSocket] = set()


@ws_router.websocket("/ws/scan")
async def websocket_scan(websocket: WebSocket):
    """スキャン進捗のリアルタイムストリーム"""
    await websocket.accept()
    _clients.add(websocket)
    client_id = id(websocket)
    logger.info(f"WebSocket接続: client={client_id}")

    try:
        # 初期状態を送信
        if state.scan_manager:
            status = state.scan_manager.get_status()
            await websocket.send_json({
                "type": "status",
                **status,
            })

        # クライアントからの切断を待つ
        while True:
            try:
                data = await websocket.receive_text()
                # 必要に応じてコマンドを処理
                try:
                    cmd = json.loads(data)
                    await _handle_command(websocket, cmd)
                except json.JSONDecodeError:
                    pass
            except WebSocketDisconnect:
                break

    except Exception as e:
        logger.error(f"WebSocket例外: {type(e).__name__}: {e}")
    finally:
        _clients.discard(websocket)
        logger.info(f"WebSocket切断: client={client_id}")


async def _handle_command(websocket: WebSocket, cmd: dict):
    """WebSocket経由のコマンドを処理"""
    action = cmd.get("action")

    if action == "status":
        if state.scan_manager:
            status = state.scan_manager.get_status()
            await websocket.send_json({"type": "status", **status})

    elif action == "start_scan":
        point_id = cmd.get("point_id")
        if point_id and state.scan_manager:
            try:
                asyncio.create_task(_run_scan_ws(point_id))
                await websocket.send_json({
                    "type": "scan_started",
                    "point_id": point_id,
                })
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                })


async def _run_scan_ws(point_id: str):
    """WebSocket経由でスキャンを実行"""
    try:
        await state.scan_manager.start_point_scan(
            point_id=point_id,
            progress_callback=broadcast_progress,
        )
        await broadcast_json({
            "type": "scan_complete",
            "point_id": point_id,
        })
    except Exception as e:
        await broadcast_error(point_id, str(e))


async def broadcast_progress(
    point_id: str, phase: str, progress: int,
    frame_count: int, elapsed: float
):
    """全クライアントに進捗を送信"""
    await broadcast_json({
        "type": "progress",
        "point_id": point_id,
        "phase": phase,
        "progress": progress,
        "frame_count": frame_count,
        "elapsed_sec": round(elapsed, 1),
    })


async def broadcast_error(point_id: str, message: str):
    """全クライアントにエラーを送信"""
    await broadcast_json({
        "type": "error",
        "point_id": point_id,
        "message": message,
    })


async def broadcast_json(data: dict):
    """全接続クライアントにJSONを送信"""
    disconnected = set()
    for ws in _clients:
        try:
            await ws.send_json(data)
        except Exception:
            disconnected.add(ws)

    _clients.difference_update(disconnected)
