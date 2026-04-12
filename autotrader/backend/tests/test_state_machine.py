# -*- coding: utf-8 -*-
"""상태 기계 테스트."""

import pytest
from backend.strategy.state_machine import (
    InvalidTransitionError,
    StateMachine,
    TradingEvent,
    TradingState,
)


class TestStateMachine:
    """상태 기계 전이 테스트."""

    def test_initial_state_is_idle(self, state_machine):
        """초기 상태는 IDLE."""
        assert state_machine.current_state == TradingState.IDLE

    def test_idle_to_scanning(self, state_machine):
        """IDLE → SCANNING (market_open)."""
        state_machine.transition(TradingEvent.MARKET_OPEN)
        assert state_machine.current_state == TradingState.SCANNING

    def test_scanning_to_watching(self, state_machine):
        """SCANNING → WATCHING (breakout_detected)."""
        state_machine.transition(TradingEvent.MARKET_OPEN)
        state_machine.transition(TradingEvent.BREAKOUT_DETECTED, symbol="005930")
        assert state_machine.current_state == TradingState.WATCHING

    def test_full_buy_flow(self, state_machine):
        """완전한 매수 흐름: IDLE → SCANNING → WATCHING → READY → SENT → OPEN."""
        state_machine.transition(TradingEvent.MARKET_OPEN)
        state_machine.transition(TradingEvent.BREAKOUT_DETECTED)
        state_machine.transition(TradingEvent.CANDLE_CLOSED)
        assert state_machine.current_state == TradingState.READY_TO_BUY

        state_machine.transition(TradingEvent.BUY_ORDER_SENT)
        assert state_machine.current_state == TradingState.BUY_ORDER_SENT

        state_machine.transition(TradingEvent.BUY_ORDER_FILLED)
        assert state_machine.current_state == TradingState.POSITION_OPEN

    def test_stop_loss_flow(self, state_machine):
        """손절 흐름: POSITION_OPEN → SELL_SENT → CLOSED."""
        state_machine.transition(TradingEvent.MARKET_OPEN)
        state_machine.transition(TradingEvent.BREAKOUT_DETECTED)
        state_machine.transition(TradingEvent.CANDLE_CLOSED)
        state_machine.transition(TradingEvent.BUY_ORDER_SENT)
        state_machine.transition(TradingEvent.BUY_ORDER_FILLED)
        state_machine.transition(TradingEvent.STOP_LOSS_HIT)
        assert state_machine.current_state == TradingState.SELL_ORDER_SENT

        state_machine.transition(TradingEvent.SELL_ORDER_FILLED)
        assert state_machine.current_state == TradingState.CLOSED

    def test_global_halt_from_any_state(self, state_machine):
        """어떤 상태에서든 HALTED로 전이 가능."""
        state_machine.transition(TradingEvent.MARKET_OPEN)
        state_machine.transition(TradingEvent.BREAKOUT_DETECTED)
        state_machine.transition(TradingEvent.DAY_LOSS_LIMIT_HIT)
        assert state_machine.current_state == TradingState.HALTED

    def test_emergency_stop_halts(self, state_machine):
        """긴급 정지로 HALTED 전이."""
        state_machine.transition(TradingEvent.EMERGENCY_STOP_TRIGGERED)
        assert state_machine.is_halted

    def test_invalid_transition_raises(self, state_machine):
        """허용되지 않은 전이는 예외 발생."""
        with pytest.raises(InvalidTransitionError):
            state_machine.transition(TradingEvent.BUY_ORDER_FILLED)

    def test_recovery_from_halted(self, state_machine):
        """HALTED에서 복구."""
        state_machine.transition(TradingEvent.EMERGENCY_STOP_TRIGGERED)
        state_machine.recover()
        assert state_machine.current_state == TradingState.IDLE

    def test_history_tracking(self, state_machine):
        """전이 이력 추적."""
        state_machine.transition(TradingEvent.MARKET_OPEN)
        state_machine.transition(TradingEvent.BREAKOUT_DETECTED)
        assert len(state_machine.history) == 2


class TestStateMachineProperties:
    """상태 기계 속성 테스트."""

    def test_has_position(self, state_machine):
        """포지션 보유 상태 확인."""
        assert not state_machine.has_position
        state_machine.transition(TradingEvent.MARKET_OPEN)
        state_machine.transition(TradingEvent.BREAKOUT_DETECTED)
        state_machine.transition(TradingEvent.CANDLE_CLOSED)
        state_machine.transition(TradingEvent.BUY_ORDER_SENT)
        state_machine.transition(TradingEvent.BUY_ORDER_FILLED)
        assert state_machine.has_position

    def test_state_summary(self, state_machine):
        """상태 요약 반환."""
        summary = state_machine.get_state_summary()
        assert summary["current_state"] == "IDLE"
        assert summary["is_halted"] is False
