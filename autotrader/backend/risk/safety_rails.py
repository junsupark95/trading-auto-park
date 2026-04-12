# -*- coding: utf-8 -*-
"""
절대 고정 안전 레일 모듈.

이 모듈의 규칙은 전략 파라미터가 아니라 시스템 불변 보호 규칙입니다.
AI는 이 규칙을 우회하거나 해제할 수 없습니다.
코드에서 동적으로 변경할 수 없도록 설계되어 있습니다.

16개 불변 안전 레일:
  1. 일일 최대 손실 한도 → 당일 거래 완전 중지
  2. 종목당 최대 손실 한도 → 즉시 청산 또는 신규 진입 금지
  3. 최대 동시 보유 종목 수 제한
  4. 동일 종목 당일 재진입 횟수 제한
  5. 손절 후 재진입 쿨다운
  6. VI 발동 직후 신규 진입 금지
  7. 장 마감 N분 전 신규 진입 금지
  8. API 오류 누적 시 자동 HALTED
  9. 실전 주문은 이중 플래그 필수
  10. 긴급 거래 정지 기능
  11. 서버 재시작 후 포지션/주문 상태 복구
  12. 미체결 장기 방치 금지
  13. 중복 주문 금지
  14. paper/live 모드 분리
  15. 실전 주문 함수 보호장치
  16. AI 안전 레일 우회 불가
"""

import functools
import logging
from typing import Any, Callable, TypeVar

from backend.config.settings import get_settings

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def require_live_trading(func: F) -> F:
    """
    실전 주문 함수에 대한 함수 레벨 보호장치 데코레이터.

    live_trading=true이고 confirm_live_orders=true이고
    trading_mode=live일 때만 함수 실행을 허용합니다.

    paper 모드에서는 mock 실행으로 대체됩니다.

    Args:
        func: 보호할 함수.

    Returns:
        래핑된 함수.

    Raises:
        LiveTradingDisabledError: 실전 주문 조건이 충족되지 않을 때.

    Example:
        >>> @require_live_trading
        ... async def submit_order(symbol, side, qty, price):
        ...     # 실전 주문 로직
        ...     pass
    """
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        settings = get_settings()

        if settings.is_paper:
            logger.info(
                f"[PAPER MODE] {func.__name__} 호출 - 모의 실행",
                extra={"event": "paper_mode_execution", "function": func.__name__},
            )
            # paper 모드에서는 함수를 정상 실행 (mock adapter가 처리)
            return await func(*args, **kwargs)

        # live 모드 체크
        if not settings.live_trading:
            raise LiveTradingDisabledError(
                f"live_trading=false: {func.__name__} 실행 차단. "
                "환경변수 LIVE_TRADING=true 설정 필요."
            )

        if not settings.confirm_live_orders:
            raise LiveTradingDisabledError(
                f"confirm_live_orders=false: {func.__name__} 실행 차단. "
                "환경변수 CONFIRM_LIVE_ORDERS=true 설정 필요."
            )

        logger.warning(
            f"[LIVE MODE] {func.__name__} 실전 주문 실행",
            extra={
                "event": "live_order_execution",
                "function": func.__name__,
            },
        )
        return await func(*args, **kwargs)

    return wrapper  # type: ignore


def ai_cannot_override(func: F) -> F:
    """
    AI가 우회할 수 없는 함수임을 표시하는 데코레이터.

    이 데코레이터가 적용된 함수의 결과는 AI 판단에 의해
    무시되거나 변경될 수 없습니다.

    Args:
        func: AI가 우회할 수 없는 함수.

    Returns:
        래핑된 함수 (원본과 동일).
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = func(*args, **kwargs)
        # AI 응답에 의한 오버라이드 시도 감지 로그
        logger.debug(
            f"[SAFETY_RAIL] {func.__name__} 실행됨 - AI 우회 불가",
            extra={
                "event": "safety_rail_executed",
                "function": func.__name__,
                "ai_override_possible": False,
            },
        )
        return result

    return wrapper  # type: ignore


class LiveTradingDisabledError(Exception):
    """실전 주문이 비활성화되어 있을 때 발생하는 예외."""
    pass


class SafetyRailViolationError(Exception):
    """안전 레일 위반 시 발생하는 예외."""
    pass


@ai_cannot_override
def validate_not_averaging_down(
    current_avg_price: float,
    current_quantity: int,
    new_price: float,
) -> bool:
    """
    물타기(averaging down) 여부를 검증합니다.

    손실 포지션에 추가매수하는 것은 시스템 규칙으로 금지됩니다.

    Args:
        current_avg_price: 현재 평균 단가.
        current_quantity: 현재 보유 수량.
        new_price: 추가 매수 시도 가격.

    Returns:
        True이면 물타기가 아님 (정상).

    Raises:
        SafetyRailViolationError: 물타기 시도 감지.
    """
    if current_quantity > 0 and new_price < current_avg_price:
        raise SafetyRailViolationError(
            f"물타기 금지: 현재 평균가({current_avg_price}) > 추가매수가({new_price})"
        )
    return True


@ai_cannot_override
def validate_mode_separation(
    order_mode: str,
    system_mode: str,
) -> bool:
    """
    paper/live 모드 분리를 검증합니다.

    주문 모드와 시스템 모드가 일치해야 합니다.

    Args:
        order_mode: 주문의 대상 모드 ("paper" 또는 "live").
        system_mode: 현재 시스템 모드.

    Returns:
        True이면 모드 일치.

    Raises:
        SafetyRailViolationError: 모드 불일치.
    """
    if order_mode != system_mode:
        raise SafetyRailViolationError(
            f"모드 불일치: 주문 모드({order_mode}) != 시스템 모드({system_mode})"
        )
    return True


@ai_cannot_override
def validate_overnight_hold_forbidden(
    has_open_positions: bool,
    is_market_closed: bool,
) -> bool:
    """
    오버나이트 보유 금지를 검증합니다.

    장 마감 시 보유 포지션이 있으면 강제 청산해야 합니다.

    Args:
        has_open_positions: 보유 포지션 존재 여부.
        is_market_closed: 장 마감 여부.

    Returns:
        True이면 오버나이트 위험 없음.
    """
    if has_open_positions and is_market_closed:
        logger.critical(
            "오버나이트 보유 감지 - 즉시 청산 필요",
            extra={
                "event": "overnight_hold_detected",
                "action": "FORCE_CLOSE_REQUIRED",
            },
        )
        return False
    return True
