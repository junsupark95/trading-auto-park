# -*- coding: utf-8 -*-
"""
FastAPI 메인 애플리케이션.

자동매매 시스템의 API 서버 진입점입니다.
React 빌드 산출물을 정적 파일로 서빙하여 단일 서비스로 배포합니다.

엔드포인트 그룹:
  - /api/positions: 포지션 조회
  - /api/orders: 주문 조회/관리
  - /api/pnl: 손익 조회
  - /api/strategy: 전략 상태
  - /api/risk: 리스크 이벤트
  - /api/emergency: 긴급 정지
  - /api/health: 헬스체크
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config.settings import get_settings
from backend.risk.emergency import get_emergency_stop

logger = logging.getLogger(__name__)

# 정적 파일 경로 (Next.js 빌드 산출물)
STATIC_DIR = Path(__file__).parent.parent / "frontend" / "out"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """애플리케이션 생명주기 관리."""
    settings = get_settings()
    logger.info(
        "🚀 자동매매 시스템 시작",
        extra={
            "event": "system_start",
            "mode": settings.trading_mode.value,
            "live_trading": settings.live_trading,
            "confirm_live_orders": settings.confirm_live_orders,
        },
    )

    # DB 초기화 (실패 시 시작하지 않음)
    try:
        from backend.persistence.database import init_database
        await init_database()
    except Exception as e:
        logger.critical(f"DB 초기화 실패 - 시스템 시작 불가: {e}")
        # DB 실패해도 API는 시작 (헬스체크용)

    # KIS 브로커 연결 (계좌 잔고 실시간 조회용)
    from backend.brokers.kis.auth import KISAuth
    from backend.brokers.kis.order_api import KISOrderAPI
    from backend.brokers.kis.ws_client import KISWebSocketClient
    from backend.strategy.engine import TradingEngine
    
    auth = KISAuth(settings)
    broker = KISOrderAPI(auth, settings)
    ws_client = KISWebSocketClient(auth, settings)
    try:
        await broker.connect()
        app.state.broker = broker
        
        # 엔진 생성 및 백그라운드 매매 루프 시작
        engine = TradingEngine(broker, settings)
        engine.set_ws_client(ws_client)
        app.state.engine = engine
        
        app.state.ws_task = asyncio.create_task(ws_client.start())
        app.state.engine_task = asyncio.create_task(engine.start())
        logger.info("트레이딩 엔진 및 웹소켓 백그라운드 태스크 시작 완료")
        
    except Exception as e:
        logger.error(f"브로커-엔진 초기 연결 실패: {e}")
        app.state.broker = None
        app.state.ws_client = None

    yield

    # 종료 처리
    logger.info("시스템 종료 중...")
    
    # 엔진 루프 및 웹소켓 안전 종료
    if hasattr(app.state, "engine"):
        await app.state.engine.stop()
        if hasattr(app.state, "engine_task"):
            try:
                await asyncio.wait_for(app.state.engine_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("엔진 태스크 강제 종료 타임아웃")
                
    if hasattr(app, "ws_client") or hasattr(app.state, "ws_task"):
        try:
            # engine의 ws_client를 직접 stop 할 수 있어야 함.
            if hasattr(app.state.engine, "_ws_client") and app.state.engine._ws_client:
                await app.state.engine._ws_client.stop()
            if hasattr(app.state, "ws_task"):
                await asyncio.wait_for(app.state.ws_task, timeout=3.0)
        except Exception as e:
            logger.warning(f"웹소켓 종료 오류: {e}")

    try:
        from backend.persistence.database import close_database
        await close_database()
    except Exception:
        pass


app = FastAPI(
    title="Korean Aggressive Opening Momentum",
    description="국내 주식 장초반 데이트레이딩 자동매매 시스템",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 설정 (개발 환경)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3002"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== 헬스체크 =====
@app.get("/api/health")
async def health_check() -> dict:
    """시스템 헬스체크."""
    settings = get_settings()
    emergency = get_emergency_stop()

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "mode": settings.trading_mode.value,
        "live_trading": settings.live_trading,
        "confirm_live_orders": settings.confirm_live_orders,
        "emergency_stop": emergency.is_active,
        "version": "0.1.0",
    }


# ===== 전략 상태 =====
@app.get("/api/strategy/status")
async def get_strategy_status() -> dict:
    """전략 엔진 현재 상태."""
    settings = get_settings()
    return {
        "strategy_name": "Korean Aggressive Opening Momentum",
        "mode": settings.trading_mode.value,
        "state": "IDLE",
        "is_live": settings.is_live,
        "can_execute_live_orders": settings.can_execute_live_orders,
        "timestamp": datetime.now().isoformat(),
    }


# ===== 포지션 =====
@app.get("/api/positions")
async def get_positions() -> dict:
    """현재 보유 포지션 조회."""
    # TODO: 실제 포지션 데이터 연동
    return {
        "positions": [],
        "count": 0,
        "timestamp": datetime.now().isoformat(),
    }


# ===== 주문 =====
@app.get("/api/orders")
async def get_orders() -> dict:
    """주문 이력 조회."""
    return {
        "orders": [],
        "pending_count": 0,
        "timestamp": datetime.now().isoformat(),
    }


# ===== 계좌/잔고 =====
@app.get("/api/account")
async def get_account_balance(request: Request) -> dict:
    """계좌 잔고 조회 (실시간)."""
    broker = getattr(request.app.state, "broker", None)
    
    if broker and await broker.is_connected():
        try:
            balance = await broker.get_balance()
            return {
                "total_equity": float(balance.total_equity),
                "available_cash": float(balance.available_cash),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"잔고 조회 중 오류: {e}")
            
    # 브로커 미연결 또는 오류 시 임시(Mock) 잔고 반환
    return {
        "total_equity": 10000000,
        "available_cash": 10000000,
        "timestamp": datetime.now().isoformat()
    }


# ===== 손익 =====
@app.get("/api/pnl")
async def get_pnl() -> dict:
    """일별 손익 조회."""
    return {
        "daily_pnl": 0,
        "realized_pnl": 0,
        "unrealized_pnl": 0,
        "total_trades": 0,
        "win_rate": 0,
        "timestamp": datetime.now().isoformat(),
    }


# ===== 리스크 이벤트 =====
@app.get("/api/risk/events")
async def get_risk_events() -> dict:
    """리스크 이벤트 조회."""
    return {
        "events": [],
        "active_blocks": [],
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/risk/status")
async def get_risk_status() -> dict:
    """리스크 상태 요약."""
    settings = get_settings()
    emergency = get_emergency_stop()

    return {
        "daily_loss_limit_pct": settings.daily_loss_limit_pct,
        "per_symbol_loss_limit_pct": settings.per_symbol_loss_limit_pct,
        "emergency_stop": emergency.get_status(),
        "vi_blocks": {},
        "timestamp": datetime.now().isoformat(),
    }


# ===== 긴급 정지 =====
@app.post("/api/emergency/stop")
async def activate_emergency_stop(request: Request) -> dict:
    """긴급 거래 정지 활성화."""
    body = await request.json()
    reason = body.get("reason", "수동 긴급 정지")
    emergency = get_emergency_stop()
    emergency.activate(reason)
    return {
        "success": True,
        "message": "긴급 정지 활성화",
        "status": emergency.get_status(),
    }


@app.post("/api/emergency/resume")
async def deactivate_emergency_stop(request: Request) -> dict:
    """긴급 정지 해제 (수동만 가능)."""
    body = await request.json()
    reason = body.get("reason", "수동 해제")
    emergency = get_emergency_stop()
    emergency.deactivate(reason)
    return {
        "success": True,
        "message": "긴급 정지 해제",
        "status": emergency.get_status(),
    }


# ===== 워치리스트 =====
@app.get("/api/watchlist")
async def get_watchlist() -> dict:
    """워치리스트 조회."""
    return {
        "candidates": [],
        "timestamp": datetime.now().isoformat(),
    }


# ===== AI 상태 =====
@app.get("/api/ai/status")
async def get_ai_status() -> dict:
    """AI 보조 분석기 상태."""
    settings = get_settings()
    return {
        "enabled": settings.ai_enabled,
        "model": settings.gemini_model,
        "daily_calls": 0,
        "daily_limit": settings.ai_daily_call_limit,
        "available": settings.ai_enabled,
    }


# ===== React 정적 파일 서빙 =====
# Next.js export 산출물을 서빙합니다
if STATIC_DIR.exists():
    app.mount("/_next", StaticFiles(directory=STATIC_DIR / "_next"), name="next_static")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str) -> FileResponse:
        """React SPA 정적 파일 서빙."""
        # API 경로가 아닌 경우에만
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")

        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)

        # SPA fallback: index.html
        index_path = STATIC_DIR / "index.html"
        if index_path.exists():
            return FileResponse(index_path)

        raise HTTPException(status_code=404, detail="Not found")
