# -*- coding: utf-8 -*-
"""
pytest 공통 fixture 정의.

모든 테스트에서 사용하는 설정, 모의 브로커, 전략 설정 등을 제공합니다.
"""

import os
import sys
from decimal import Decimal
from datetime import datetime

import pytest

# 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.config.settings import Settings, TradingMode, reset_settings
from backend.config.strategy_config import AggressiveProfileConfig, SAFETY_RAILS
from backend.brokers.kis.mock_adapter import MockBroker
from backend.risk.engine import RiskEngine, RiskContext
from backend.risk.emergency import EmergencyStopManager
from backend.strategy.state_machine import StateMachine, TradingState
from backend.execution.order_manager import OrderManager


@pytest.fixture
def paper_settings() -> Settings:
    """Paper 모드 설정."""
    reset_settings()
    return Settings(
        trading_mode=TradingMode.PAPER,
        live_trading=False,
        confirm_live_orders=False,
        database_url="postgresql+asyncpg://localhost:5432/test_autotrader",
        ai_enabled=False,
    )


@pytest.fixture
def live_settings() -> Settings:
    """Live 모드 설정 (테스트용, 실제 API 호출 없음)."""
    reset_settings()
    return Settings(
        trading_mode=TradingMode.LIVE,
        live_trading=True,
        confirm_live_orders=True,
        database_url="postgresql+asyncpg://localhost:5432/test_autotrader",
        ai_enabled=False,
    )


@pytest.fixture
def strategy_config() -> AggressiveProfileConfig:
    """기본 전략 설정."""
    return AggressiveProfileConfig()


@pytest.fixture
def mock_broker() -> MockBroker:
    """모의 브로커."""
    return MockBroker(initial_cash=Decimal("10000000"))


@pytest.fixture
def risk_engine(paper_settings, strategy_config) -> RiskEngine:
    """리스크 엔진."""
    return RiskEngine(paper_settings, strategy_config)


@pytest.fixture
def state_machine() -> StateMachine:
    """상태 기계."""
    return StateMachine()


@pytest.fixture
def emergency_stop() -> EmergencyStopManager:
    """긴급 정지 관리자."""
    return EmergencyStopManager()


@pytest.fixture
def order_manager(mock_broker) -> OrderManager:
    """주문 관리자."""
    return OrderManager(mock_broker)


@pytest.fixture
def normal_context() -> RiskContext:
    """정상 리스크 컨텍스트."""
    return RiskContext(
        system_state="SCANNING",
        emergency_stop=False,
        api_health="HEALTHY",
        current_position_count=0,
        daily_entry_count=0,
        daily_realized_pnl=Decimal("0"),
        starting_capital=Decimal("10000000"),
        symbol="005930",
        symbol_entry_count_today=0,
        symbol_realized_pnl=Decimal("0"),
        current_time=datetime(2026, 4, 12, 9, 10, 0),
    )
