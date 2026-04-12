# -*- coding: utf-8 -*-
"""
상태 기계 (State Machine) 모듈.

전략 엔진의 모든 상태 전이를 관리합니다.
모든 상태 전이마다 구조화된 JSON 로그를 남깁니다.

상태 목록: IDLE, SCANNING, WATCHING, READY_TO_BUY, BUY_ORDER_SENT,
           POSITION_OPEN, SELL_ORDER_SENT, CLOSED, HALTED, ERROR

설계 원칙:
  - 허용되지 않은 전이는 예외를 발생시킴
  - HALTED 상태는 어디서든 진입 가능하지만 복구만으로 탈출
  - 모든 전이에 타임스탬프와 사유를 기록
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class TradingState(str, Enum):
    """전략 엔진 상태."""
    IDLE = "IDLE"
    SCANNING = "SCANNING"
    WATCHING = "WATCHING"
    READY_TO_BUY = "READY_TO_BUY"
    BUY_ORDER_SENT = "BUY_ORDER_SENT"
    POSITION_OPEN = "POSITION_OPEN"
    SELL_ORDER_SENT = "SELL_ORDER_SENT"
    CLOSED = "CLOSED"
    HALTED = "HALTED"
    ERROR = "ERROR"


class TradingEvent(str, Enum):
    """상태 전이를 유발하는 이벤트."""
    MARKET_OPEN = "market_open"
    TICK_RECEIVED = "tick_received"
    CANDLE_CLOSED = "candle_closed"
    BREAKOUT_DETECTED = "breakout_detected"
    BUY_ORDER_SENT = "buy_order_sent"
    BUY_ORDER_FILLED = "buy_order_filled"
    SELL_ORDER_SENT = "sell_order_sent"
    SELL_ORDER_FILLED = "sell_order_filled"
    STOP_LOSS_HIT = "stop_loss_hit"
    TAKE_PROFIT_HIT = "take_profit_hit"
    TRAILING_STOP_HIT = "trailing_stop_hit"
    TIME_EXIT_TRIGGERED = "time_exit_triggered"
    VI_TRIGGERED = "vi_triggered"
    API_ERROR = "api_error"
    RECONNECT_SUCCESS = "reconnect_success"
    DAY_LOSS_LIMIT_HIT = "day_loss_limit_hit"
    EMERGENCY_STOP_TRIGGERED = "emergency_stop_triggered"
    RESTART_RECOVERY_COMPLETE = "restart_recovery_complete"
    MARKET_CLOSE = "market_close"
    RESET = "reset"


@dataclass
class StateTransition:
    """상태 전이 기록."""
    from_state: TradingState
    to_state: TradingState
    event: TradingEvent
    timestamp: datetime
    symbol: Optional[str] = None
    reason: str = ""
    metadata: dict = field(default_factory=dict)


# 허용된 상태 전이 테이블
# (현재 상태, 이벤트) -> 다음 상태
TRANSITION_TABLE: dict[tuple[TradingState, TradingEvent], TradingState] = {
    # IDLE 전이
    (TradingState.IDLE, TradingEvent.MARKET_OPEN): TradingState.SCANNING,
    (TradingState.IDLE, TradingEvent.RESTART_RECOVERY_COMPLETE): TradingState.SCANNING,

    # SCANNING 전이
    (TradingState.SCANNING, TradingEvent.TICK_RECEIVED): TradingState.SCANNING,
    (TradingState.SCANNING, TradingEvent.BREAKOUT_DETECTED): TradingState.WATCHING,
    (TradingState.SCANNING, TradingEvent.MARKET_CLOSE): TradingState.IDLE,

    # WATCHING 전이
    (TradingState.WATCHING, TradingEvent.CANDLE_CLOSED): TradingState.READY_TO_BUY,
    (TradingState.WATCHING, TradingEvent.TICK_RECEIVED): TradingState.WATCHING,
    (TradingState.WATCHING, TradingEvent.VI_TRIGGERED): TradingState.SCANNING,
    (TradingState.WATCHING, TradingEvent.MARKET_CLOSE): TradingState.IDLE,
    (TradingState.WATCHING, TradingEvent.RESET): TradingState.SCANNING,

    # READY_TO_BUY 전이
    (TradingState.READY_TO_BUY, TradingEvent.BUY_ORDER_SENT): TradingState.BUY_ORDER_SENT,
    (TradingState.READY_TO_BUY, TradingEvent.VI_TRIGGERED): TradingState.SCANNING,
    (TradingState.READY_TO_BUY, TradingEvent.RESET): TradingState.SCANNING,
    (TradingState.READY_TO_BUY, TradingEvent.MARKET_CLOSE): TradingState.IDLE,

    # BUY_ORDER_SENT 전이
    (TradingState.BUY_ORDER_SENT, TradingEvent.BUY_ORDER_FILLED): TradingState.POSITION_OPEN,
    (TradingState.BUY_ORDER_SENT, TradingEvent.API_ERROR): TradingState.ERROR,
    (TradingState.BUY_ORDER_SENT, TradingEvent.RESET): TradingState.SCANNING,

    # POSITION_OPEN 전이
    (TradingState.POSITION_OPEN, TradingEvent.STOP_LOSS_HIT): TradingState.SELL_ORDER_SENT,
    (TradingState.POSITION_OPEN, TradingEvent.TAKE_PROFIT_HIT): TradingState.SELL_ORDER_SENT,
    (TradingState.POSITION_OPEN, TradingEvent.TRAILING_STOP_HIT): TradingState.SELL_ORDER_SENT,
    (TradingState.POSITION_OPEN, TradingEvent.TIME_EXIT_TRIGGERED): TradingState.SELL_ORDER_SENT,
    (TradingState.POSITION_OPEN, TradingEvent.SELL_ORDER_SENT): TradingState.SELL_ORDER_SENT,
    (TradingState.POSITION_OPEN, TradingEvent.TICK_RECEIVED): TradingState.POSITION_OPEN,
    (TradingState.POSITION_OPEN, TradingEvent.MARKET_CLOSE): TradingState.SELL_ORDER_SENT,

    # SELL_ORDER_SENT 전이
    (TradingState.SELL_ORDER_SENT, TradingEvent.SELL_ORDER_FILLED): TradingState.CLOSED,
    (TradingState.SELL_ORDER_SENT, TradingEvent.API_ERROR): TradingState.ERROR,

    # CLOSED 전이
    (TradingState.CLOSED, TradingEvent.RESET): TradingState.SCANNING,
    (TradingState.CLOSED, TradingEvent.MARKET_CLOSE): TradingState.IDLE,

    # HALTED 전이 (오직 복구를 통해서만 탈출)
    (TradingState.HALTED, TradingEvent.RESTART_RECOVERY_COMPLETE): TradingState.IDLE,

    # ERROR 전이
    (TradingState.ERROR, TradingEvent.RECONNECT_SUCCESS): TradingState.SCANNING,
    (TradingState.ERROR, TradingEvent.RESET): TradingState.SCANNING,
}

# HALTED로의 전이는 어떤 상태에서든 가능 (글로벌 이벤트)
GLOBAL_HALT_EVENTS = {
    TradingEvent.DAY_LOSS_LIMIT_HIT,
    TradingEvent.EMERGENCY_STOP_TRIGGERED,
}


class StateMachine:
    """
    전략 엔진 상태 기계.

    허용된 전이만 수행하며, 모든 전이를 로그로 기록합니다.
    HALTED 상태는 글로벌 이벤트에 의해 언제든 진입 가능합니다.

    Attributes:
        current_state: 현재 상태.
        history: 전이 이력.
        symbol: 현재 처리 중인 종목 (있는 경우).

    Example:
        >>> sm = StateMachine()
        >>> sm.transition(TradingEvent.MARKET_OPEN)
        >>> print(sm.current_state)
        TradingState.SCANNING
    """

    def __init__(self, initial_state: TradingState = TradingState.IDLE) -> None:
        self._state: TradingState = initial_state
        self._history: list[StateTransition] = []
        self._symbol: Optional[str] = None
        self._previous_state: Optional[TradingState] = None

    @property
    def current_state(self) -> TradingState:
        """현재 상태를 반환합니다."""
        return self._state

    @property
    def history(self) -> list[StateTransition]:
        """전이 이력을 반환합니다."""
        return self._history.copy()

    @property
    def symbol(self) -> Optional[str]:
        """현재 처리 중인 종목을 반환합니다."""
        return self._symbol

    @symbol.setter
    def symbol(self, value: Optional[str]) -> None:
        self._symbol = value

    @property
    def is_halted(self) -> bool:
        """HALTED 상태 여부."""
        return self._state == TradingState.HALTED

    @property
    def is_error(self) -> bool:
        """ERROR 상태 여부."""
        return self._state == TradingState.ERROR

    @property
    def has_position(self) -> bool:
        """포지션 보유 중 여부."""
        return self._state in (
            TradingState.POSITION_OPEN,
            TradingState.SELL_ORDER_SENT,
        )

    def can_transition(self, event: TradingEvent) -> bool:
        """
        주어진 이벤트로 전이 가능한지 확인합니다.

        Args:
            event: 확인할 이벤트.

        Returns:
            전이 가능 여부.
        """
        if event in GLOBAL_HALT_EVENTS:
            return True
        return (self._state, event) in TRANSITION_TABLE

    def transition(
        self,
        event: TradingEvent,
        reason: str = "",
        symbol: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> TradingState:
        """
        이벤트에 따라 상태를 전이합니다.

        모든 전이는 구조화 JSON 로그로 기록됩니다.
        허용되지 않은 전이는 InvalidTransitionError를 발생시킵니다.

        Args:
            event: 전이를 유발하는 이벤트.
            reason: 전이 사유 (로그용).
            symbol: 관련 종목코드.
            metadata: 추가 메타데이터.

        Returns:
            전이 후의 새 상태.

        Raises:
            InvalidTransitionError: 허용되지 않은 전이.
        """
        old_state = self._state

        # 글로벌 HALT 이벤트 처리
        if event in GLOBAL_HALT_EVENTS:
            self._previous_state = old_state
            new_state = TradingState.HALTED
        else:
            key = (self._state, event)
            if key not in TRANSITION_TABLE:
                raise InvalidTransitionError(
                    f"허용되지 않은 전이: {self._state.value} --[{event.value}]--> ?"
                )
            new_state = TRANSITION_TABLE[key]

        # API 오류 누적 시 HALTED 전이 (별도 로직 필요)
        if event == TradingEvent.API_ERROR and metadata:
            error_count = metadata.get("cumulative_api_errors", 0)
            max_errors = metadata.get("max_api_errors", 5)
            if error_count >= max_errors:
                self._previous_state = old_state
                new_state = TradingState.HALTED
                reason = f"API 오류 누적 ({error_count}/{max_errors})"

        # 상태 전이 실행
        self._state = new_state

        if symbol:
            self._symbol = symbol

        # 전이 기록
        transition_record = StateTransition(
            from_state=old_state,
            to_state=new_state,
            event=event,
            timestamp=datetime.now(),
            symbol=symbol or self._symbol,
            reason=reason,
            metadata=metadata or {},
        )
        self._history.append(transition_record)

        # 구조화 로그 기록
        logger.info(
            "상태 전이",
            extra={
                "event": "state_transition",
                "from_state": old_state.value,
                "to_state": new_state.value,
                "trigger_event": event.value,
                "symbol": symbol or self._symbol,
                "reason": reason,
                "metadata": metadata or {},
                "timestamp": transition_record.timestamp.isoformat(),
            },
        )

        return new_state

    def force_halt(self, reason: str) -> None:
        """
        강제로 HALTED 상태로 전환합니다 (긴급 정지).

        Args:
            reason: 정지 사유.
        """
        self.transition(
            TradingEvent.EMERGENCY_STOP_TRIGGERED,
            reason=reason,
        )

    def recover(self) -> TradingState:
        """
        HALTED/ERROR 상태에서 복구합니다.

        Returns:
            복구 후 상태 (IDLE).

        Raises:
            InvalidTransitionError: HALTED/ERROR 상태가 아닌 경우.
        """
        if self._state not in (TradingState.HALTED, TradingState.ERROR):
            raise InvalidTransitionError(
                f"복구는 HALTED 또는 ERROR 상태에서만 가능합니다 (현재: {self._state.value})"
            )
        return self.transition(
            TradingEvent.RESTART_RECOVERY_COMPLETE,
            reason="관리자에 의한 수동 복구",
        )

    def reset_to_scanning(self, reason: str = "리셋") -> TradingState:
        """
        SCANNING 상태로 리셋합니다 (종목 전환 시).

        Args:
            reason: 리셋 사유.

        Returns:
            리셋 후 상태.
        """
        return self.transition(TradingEvent.RESET, reason=reason)

    def get_state_summary(self) -> dict:
        """
        현재 상태 요약을 반환합니다.

        Returns:
            상태 요약 딕셔너리.
        """
        return {
            "current_state": self._state.value,
            "symbol": self._symbol,
            "is_halted": self.is_halted,
            "has_position": self.has_position,
            "transition_count": len(self._history),
            "last_transition": (
                {
                    "from": self._history[-1].from_state.value,
                    "to": self._history[-1].to_state.value,
                    "event": self._history[-1].event.value,
                    "time": self._history[-1].timestamp.isoformat(),
                }
                if self._history
                else None
            ),
        }


class InvalidTransitionError(Exception):
    """허용되지 않은 상태 전이 시 발생하는 예외."""
    pass
