# -*- coding: utf-8 -*-
"""리스크 엔진 테스트."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from backend.risk.engine import RiskContext, RiskEngine


class TestRiskEngineEntry:
    """진입 리스크 체크 테스트."""

    def test_normal_entry_allowed(self, risk_engine, normal_context):
        """정상 조건에서 진입 허용."""
        result = risk_engine.check_entry_allowed(normal_context)
        assert result.passed

    def test_emergency_stop_blocks(self, risk_engine, normal_context):
        """긴급 정지 시 진입 차단."""
        normal_context.emergency_stop = True
        result = risk_engine.check_entry_allowed(normal_context)
        assert not result.passed
        assert any("EMERGENCY_STOP" in v for v in result.violations)

    def test_halted_state_blocks(self, risk_engine, normal_context):
        """HALTED 상태에서 진입 차단."""
        normal_context.system_state = "HALTED"
        result = risk_engine.check_entry_allowed(normal_context)
        assert not result.passed

    def test_daily_loss_limit_blocks(self, risk_engine, normal_context):
        """일일 손실 한도 초과 시 진입 차단."""
        normal_context.daily_realized_pnl = Decimal("-400000")  # -4%
        result = risk_engine.check_entry_allowed(normal_context)
        assert not result.passed
        assert any("DAILY_LOSS_LIMIT" in v for v in result.violations)

    def test_max_positions_blocks(self, risk_engine, normal_context):
        """최대 보유 종목 수 초과 시 진입 차단."""
        normal_context.current_position_count = 2  # max=2
        result = risk_engine.check_entry_allowed(normal_context)
        assert not result.passed
        assert any("MAX_POSITIONS" in v for v in result.violations)

    def test_reentry_cooldown_blocks(self, risk_engine, normal_context):
        """재진입 쿨다운 중 진입 차단."""
        normal_context.last_exit_time = datetime(2026, 4, 12, 9, 8, 0)  # 2분 전
        result = risk_engine.check_entry_allowed(normal_context)
        assert not result.passed
        assert any("REENTRY_COOLDOWN" in v for v in result.violations)

    def test_market_close_cutoff_blocks(self, risk_engine, normal_context):
        """장 마감 후 진입 차단."""
        normal_context.current_time = datetime(2026, 4, 12, 15, 15, 0)
        result = risk_engine.check_entry_allowed(normal_context)
        assert not result.passed

    def test_duplicate_order_blocks(self, risk_engine, normal_context):
        """중복 주문 차단."""
        normal_context.has_pending_order_for_symbol = True
        result = risk_engine.check_entry_allowed(normal_context)
        assert not result.passed
        assert any("DUPLICATE_ORDER" in v for v in result.violations)

    def test_api_unhealthy_blocks(self, risk_engine, normal_context):
        """API 비정상 시 진입 차단."""
        normal_context.api_health = "DEGRADED"
        result = risk_engine.check_entry_allowed(normal_context)
        assert not result.passed

    def test_before_entry_time_blocks(self, risk_engine, normal_context):
        """진입 시작 시간 전 차단."""
        normal_context.current_time = datetime(2026, 4, 12, 9, 0, 0)
        result = risk_engine.check_entry_allowed(normal_context)
        assert not result.passed

    def test_symbol_reentry_limit_blocks(self, risk_engine, normal_context):
        """종목당 재진입 한도 초과 차단."""
        normal_context.symbol_entry_count_today = 2  # max=2
        result = risk_engine.check_entry_allowed(normal_context)
        assert not result.passed


class TestRiskEngineExit:
    """청산 리스크 체크 테스트."""

    def test_normal_exit_allowed(self, risk_engine, normal_context):
        """정상 청산 허용."""
        result = risk_engine.check_exit_allowed(normal_context)
        assert result.passed

    def test_duplicate_sell_blocks(self, risk_engine, normal_context):
        """중복 매도 주문 차단."""
        normal_context.has_pending_order_for_symbol = True
        result = risk_engine.check_exit_allowed(normal_context)
        assert not result.passed
