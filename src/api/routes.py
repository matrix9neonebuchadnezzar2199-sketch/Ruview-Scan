"""
RuView Scan - REST API エンドポイント
"""

import asyncio
import logging
import time
from typing import List, Optional, Set

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.api.server import state
from src.errors import RuViewError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_start_time = time.time()

# H3修正: バックグラウンドタスクの参照を保持してGC防止
_background_tasks: Set[asyncio.Task] = set()


# ===== DTOs =====

class HealthResponse(BaseModel):
    status: str
    version: str
    nic: Optional[str] = None
    csi_source: str
    uptime: float


class SessionResponse(BaseModel):
    session_id: str
    room_name: str


class ScanStatusResponse(BaseModel):
    session: Optional[str] = None
    scanning: bool
    scanning_point: Optional[str] = None
    completed: List[str]
    remaining: List[str]
    progress: float = 0.0


class RoomResponse(BaseModel):
    width: float
    depth: float
    height: float
    area: float


class MapResponse(BaseModel):
    face: str
    band: str
    width_m: float
    height_m: float
    resolution: float
    grid: List[List[float]]


class StructureResponse(BaseModel):
    face: str
    x1: float
    y1: float
    x2: float
    y2: float
    material: str
    confidence: float
    intensity: float
    label: str


class ForeignResponse(BaseModel):
    face: str
    x: float
    y: float
    radius: float
    confidence: float
    label: str
    detail: str
    detection_method: str


# ===== Endpoints =====

@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok" if state.running else "starting",
        version="1.0.0",
        nic=state.nic_info.chipset if state.nic_info else "simulation",
        csi_source=state.config.get("csi", {}).get("source", "simulate"),
        uptime=time.time() - _start_time,
    )


@router.get("/config")
async def get_config():
    """現在の設定を返す"""
    cfg = state.config.copy()
    return cfg


@router.post("/session/create", response_model=SessionResponse)
async def create_session(room_name: str = "untitled"):
    """新規スキャンセッション作成"""
    if not state.scan_manager:
        raise HTTPException(500, detail="System not initialized")

    session = state.scan_manager.create_session(room_name)
    return SessionResponse(
        session_id=session.session_id,
        room_name=session.room_name,
    )


@router.post("/scan/{point_id}/start")
async def start_scan(point_id: str):
    """計測点のスキャン開始 (非同期で実行、進捗はWebSocketで通知)"""
    if not state.scan_manager:
        raise HTTPException(500, detail="System not initialized")

    if state.scan_manager.current_session is None:
        state.scan_manager.create_session()

    try:
        # 非同期でスキャン実行 (結果はWebSocketで通知)
        task = asyncio.create_task(_run_scan(point_id))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return {"status": "started", "point_id": point_id}
    except RuViewError as e:
        raise HTTPException(400, detail=e.format())


async def _run_scan(point_id: str):
    """バックグラウンドでスキャンを実行"""
    try:
        from src.api.ws import broadcast_progress, broadcast_json
        await state.scan_manager.start_point_scan(
            point_id=point_id,
            progress_callback=broadcast_progress,
        )
        # 完了通知をWebSocketにブロードキャスト
        await broadcast_json({
            "type": "scan_complete",
            "point_id": point_id,
        })
    except RuViewError as e:
        logger.error(f"Scan error: {e.format()}")
        from src.api.ws import broadcast_error
        await broadcast_error(point_id, str(e))
    except Exception as e:
        logger.error(f"Scan exception: {e}", exc_info=True)
        from src.api.ws import broadcast_error
        await broadcast_error(point_id, str(e))


@router.get("/scan/{point_id}/status")
async def scan_status(point_id: str):
    """計測点のスキャン状態"""
    if not state.scan_manager:
        raise HTTPException(500, detail="System not initialized")

    status = state.scan_manager.get_status()
    is_done = point_id in status.get('completed', [])
    is_scanning = status.get('scanning_point') == point_id

    return {
        "point_id": point_id,
        "status": "scanning" if is_scanning else ("done" if is_done else "ready"),
    }


@router.get("/scan/status", response_model=ScanStatusResponse)
async def get_scan_status():
    """全体のスキャン状態"""
    if not state.scan_manager:
        return ScanStatusResponse(
            scanning=False, completed=[], remaining=[
                'north', 'east', 'south', 'west', 'center'
            ]
        )

    s = state.scan_manager.get_status()
    return ScanStatusResponse(**s)


@router.post("/build")
async def build_result(
    manual_width: Optional[float] = Query(None),
    manual_depth: Optional[float] = Query(None),
    manual_height: Optional[float] = Query(None),
):
    """スキャン結果を3D化 (部屋推定 + 反射マップ + 構造物検出)"""
    if not state.scan_manager or not state.scan_manager.current_session:
        raise HTTPException(400, detail="No scan session")

    session = state.scan_manager.current_session
    if not session.is_complete:
        raise HTTPException(
            400,
            detail=f"All 5 points required. Completed: {session.completed_points}"
        )

    try:
        # 1. ToF による部屋寸法推定
        tof_dims = state.room_estimator.estimate(session)
        logger.info(f"ToF推定寸法: {tof_dims.width}×{tof_dims.depth}×{tof_dims.height}")

        # 2. 手動入力値との融合 (手動 80%, ToF 20%)
        if manual_width and manual_depth and manual_height:
            MANUAL_WEIGHT = 0.8
            TOF_WEIGHT = 0.2
            fused_w = round(manual_width * MANUAL_WEIGHT + tof_dims.width * TOF_WEIGHT, 1)
            fused_d = round(manual_depth * MANUAL_WEIGHT + tof_dims.depth * TOF_WEIGHT, 1)
            fused_h = round(manual_height * MANUAL_WEIGHT + tof_dims.height * TOF_WEIGHT, 1)
            from src.utils.geo_utils import RoomDimensions
            state.room_dims = RoomDimensions(width=fused_w, depth=fused_d, height=fused_h)
            logger.info(f"融合寸法: {fused_w}×{fused_d}×{fused_h} "
                        f"(手動: {manual_width}×{manual_depth}×{manual_height})")
        else:
            state.room_dims = tof_dims
            logger.info("手動入力なし — ToF推定値をそのまま使用")

        result = {
            "room": {
                "width": state.room_dims.width,
                "depth": state.room_dims.depth,
                "height": state.room_dims.height,
                "area": state.room_dims.area,
            },
            "structures": [],
            "foreign": [],
        }

        # 2. 反射マップ生成 (Phase B で実装)
        try:
            from src.scan.reflection_map import ReflectionMapGenerator
            from src.fusion.band_merger import BandMerger
            from src.fusion.spatial_integrator import SpatialIntegrator
            from src.fusion.view_generator import ViewGenerator

            rmap_gen = ReflectionMapGenerator(state.room_dims)
            maps = rmap_gen.generate(session)
            state.reflection_maps = maps

            # 3. 構造物検出 (Phase B)
            from src.scan.structure_detector import StructureDetector
            detector = StructureDetector()
            all_structures = []
            for face, rmap in maps.items():
                structures = detector.detect(rmap)
                all_structures.extend(structures)
            state.structures = all_structures

            result["structures"] = [
                {
                    "face": s.face, "x1": s.x1, "y1": s.y1,
                    "x2": s.x2, "y2": s.y2,
                    "material": s.material, "confidence": s.confidence,
                    "intensity": s.intensity, "label": s.label,
                }
                for s in all_structures
            ]

            # 4. 異物検出 (Phase C)
            try:
                from src.scan.foreign_detector import ForeignDetector
                from src.rf.scanner import RFScanner
                nic_cfg = state.config.get("nic", {})
                rf_iface = nic_cfg.get("interface", "wlan0")
                if state.nic_info:
                    rf_iface = state.nic_info.interface
                rf_scanner = RFScanner(interface=rf_iface)
                fd = ForeignDetector(rf_scanner)
                import asyncio
                foreign = await fd.detect(session, maps, all_structures)
                state.foreign_objects = foreign
                result["foreign"] = [
                    {
                        "face": f.face, "x": f.x, "y": f.y,
                        "radius": f.radius, "confidence": f.confidence,
                        "label": f.label, "detail": f.detail,
                        "detection_method": f.detection_method,
                    }
                    for f in foreign
                ]
            except ImportError:
                logger.info("Foreign detector not yet available (Phase C)")

        except ImportError:
            logger.info("Reflection map / structure detector not yet available (Phase B)")

        return result

    except RuViewError as e:
        raise HTTPException(500, detail=e.format())
    except Exception as e:
        logger.error(f"Build error: {e}", exc_info=True)
        raise HTTPException(500, detail=str(e))


@router.get("/result/room")
async def get_room():
    """部屋寸法を返す"""
    if state.room_dims is None:
        raise HTTPException(404, detail="Room not estimated yet. Run /api/build first.")
    return {
        "width": state.room_dims.width,
        "depth": state.room_dims.depth,
        "height": state.room_dims.height,
        "area": state.room_dims.area,
    }


@router.get("/result/map/{face}/{band}")
async def get_reflection_map(face: str, band: str):
    """反射マップを返す"""
    if state.reflection_maps is None:
        raise HTTPException(404, detail="Reflection maps not generated yet")

    key = f"{face}_{band}"
    if key not in state.reflection_maps:
        # フォールバック: face名だけで検索
        rmap = state.reflection_maps.get(face)
        if rmap is None:
            raise HTTPException(404, detail=f"Map not found: {face}/{band}")
    else:
        rmap = state.reflection_maps[key]

    return {
        "face": rmap.face,
        "band": rmap.band,
        "width_m": rmap.width_m,
        "height_m": rmap.height_m,
        "resolution": rmap.resolution,
        "grid": rmap.grid.tolist(),
    }


@router.get("/result/structures")
async def get_structures():
    """検出構造物リスト"""
    if state.structures is None:
        return {"structures": []}
    return {
        "structures": [
            {
                "face": s.face, "x1": s.x1, "y1": s.y1,
                "x2": s.x2, "y2": s.y2,
                "material": s.material, "confidence": s.confidence,
                "intensity": s.intensity, "label": s.label,
            }
            for s in state.structures
        ]
    }


@router.get("/result/foreign")
async def get_foreign():
    """検出異物リスト"""
    if state.foreign_objects is None:
        return {"foreign": []}
    return {
        "foreign": [
            {
                "face": f.face, "x": f.x, "y": f.y,
                "radius": f.radius, "confidence": f.confidence,
                "label": f.label, "detail": f.detail,
                "detection_method": f.detection_method,
            }
            for f in state.foreign_objects
        ]
    }


@router.post("/reset")
async def reset():
    """セッションリセット"""
    if state.scan_manager:
        state.scan_manager.reset()
    state.room_dims = None
    state.reflection_maps = None
    state.structures = None
    state.foreign_objects = None
    return {"status": "reset"}
