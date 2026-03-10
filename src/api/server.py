"""
RuView Scan - FastAPI Server
(RF PROBE v2.0 構造を継承)
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.config import load_config
from src.errors import RuViewError
from src.utils.nic import find_best_nic, NICInfo
from src.csi.adapter import create_adapter, CSIAdapter, SimulatedAdapter
from src.csi.calibration import PhaseCalibrator
from src.csi.collector import DualBandCollector
from src.scan.scan_manager import ScanManager
from src.scan.tof_estimator import ToFEstimator
from src.scan.aoa_estimator import AoAEstimator
from src.scan.room_estimator import RoomEstimator

logger = logging.getLogger(__name__)


class AppState:
    """アプリケーション状態"""
    config: dict = {}
    nic_info: Optional[NICInfo] = None
    csi_adapter: Optional[CSIAdapter] = None
    calibrator: Optional[PhaseCalibrator] = None
    collector: Optional[DualBandCollector] = None
    scan_manager: Optional[ScanManager] = None
    tof_estimator: Optional[ToFEstimator] = None
    aoa_estimator: Optional[AoAEstimator] = None
    room_estimator: Optional[RoomEstimator] = None
    room_dims = None          # RoomDimensions (推定後)
    reflection_maps = None    # 反射マップ (Phase B)
    structures = None         # 検出構造物 (Phase B)
    foreign_objects = None    # 検出異物 (Phase C)
    running: bool = False


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("RuView Scan v1.0 starting...")

    try:
        state.config = load_config()
        cfg = state.config

        # NIC detection - skip gracefully on Windows
        try:
            state.nic_info = find_best_nic()
            logger.info(f"NIC: {state.nic_info.chipset}")
        except (RuViewError, FileNotFoundError, OSError) as e:
            logger.warning(f"NIC detection skipped: {e} -> simulation mode")
            state.nic_info = None

        # CSI adapter
        csi_cfg = cfg.get("csi", {})
        csi_source = csi_cfg.get("source", "simulate")
        if state.nic_info is None:
            csi_source = "simulate"
            logger.info("CSI source: simulation (no NIC detected)")

        state.csi_adapter = create_adapter(csi_source, csi_cfg)
        await state.csi_adapter.connect()

        # Phase calibrator
        state.calibrator = PhaseCalibrator()

        # Dual-band collector
        meas_cfg = cfg.get("measurement", {})
        state.collector = DualBandCollector(
            adapter=state.csi_adapter,
            calibrator=state.calibrator,
            duration_per_band=meas_cfg.get("duration_per_band", 30),
            sample_rate=meas_cfg.get("sample_rate", 100),
            simulate_speedup=10.0 if csi_source == "simulate" else 1.0,
        )

        # Scan manager
        state.scan_manager = ScanManager(collector=state.collector)

        # Estimators
        analysis_cfg = cfg.get("analysis", {})
        tof_cfg = analysis_cfg.get("tof", {})
        state.tof_estimator = ToFEstimator(
            method=tof_cfg.get("method", "music"),
            n_paths=tof_cfg.get("n_paths", 8),
        )
        state.aoa_estimator = AoAEstimator(
            method=analysis_cfg.get("aoa", {}).get("method", "music"),
        )
        state.room_estimator = RoomEstimator(
            tof_estimator=state.tof_estimator,
            aoa_estimator=state.aoa_estimator,
        )

        state.running = True
        logger.info("RuView Scan v1.0 started successfully")

    except RuViewError as e:
        logger.error(f"Startup error: {e.format()}")
        raise
    except Exception as e:
        logger.error(f"Unexpected startup error: {type(e).__name__}: {e}")
        raise

    yield

    logger.info("RuView Scan v1.0 shutting down...")
    state.running = False
    if state.csi_adapter:
        await state.csi_adapter.disconnect()
    logger.info("RuView Scan v1.0 shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="RuView Scan",
        version="1.0.0",
        description="Wi-Fi CSI 6-Face Room Scanner",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Static files (frontend)
    static_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static")
    static_dir = os.path.normpath(static_dir)
    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Routes
    from src.api.routes import router
    from src.api.ws import ws_router
    app.include_router(router)
    app.include_router(ws_router)

    @app.get("/")
    async def index():
        """index.html を返す"""
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "RuView Scan API", "version": "1.0.0"}

    return app
