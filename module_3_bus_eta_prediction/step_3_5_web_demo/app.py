"""
Module 3 - Step 3.5: FastAPI Web Application Entrypoint.
Provides Swagger UI (/docs), Contract-First REST API (/api/v1), and serves the Frontend SPA.
"""

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, BASE_DIR)

from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.eta_serving_service import (
    EtaServingService,
)
from module_3_bus_eta_prediction.step_3_5_web_demo.api_routes import router as api_router

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup & shutdown lifespan manager.
    Preloads EtaServingService into RAM during startup to eliminate cold-start latency.
    """
    print("[*] Lifespan Startup: Đang nạp CSDL Ground Truth và Model XGBoost vào RAM...")
    service = EtaServingService.get_instance()
    print(
        f"[+] Lifespan Ready: Đã nạp {len(service.extractor.route_meta)} tuyến vào bộ nhớ phục vụ!"
    )
    yield
    print("[*] Lifespan Shutdown: Dọn dẹp tài nguyên máy chủ.")


app = FastAPI(
    title="Hanoi Bus Live ETA Prediction Service",
    description=(
        "Hệ thống dự báo thời gian xe buýt đến trạm thời gian thực (Live ETA) "
        "kết hợp mô hình học máy XGBoost, bộ lọc hành lang Frenet và cửa sổ an toàn "
        "phòng ngừa rủi ro lỡ chuyến cho hành khách."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for local testing and decoupled frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Router
app.include_router(api_router)

# Mount static files
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def serve_index():
    """Serves the main single-page web app."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "service": "Hanoi Bus Live ETA Prediction Service",
        "status": "running",
        "docs": "/docs",
        "frontend": "index.html not found in static/",
    }
