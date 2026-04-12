# -*- coding: utf-8 -*-
"""
전략 청산 규칙 모듈.

청산 우선순위:
  1. 손절 (초기 스탑로스)
  2. 부분 익절 (목표 수익 도달)
  3. 트레일링 스탑 (수익 보호)
  4. 시간 청산 (진입 후 N분)
  5. 장마감 청산 (15:20 이전)
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from backend.config.strategy_config import AggressiveProfileConfig, MARKET_HOURS

logger = logging.getLogger(__name__)


@dataclass
class ExitSignal:
    """청산 시그널."""
    symbol: str
    exit_type: str  # STOP_LOSS, PARTIAL_TAKE_PROFIT, TRAILING_STOP, TIME_EXIT, FORCE_CLOSE
    quantity_ratio: float  # 청산 비율 (1.0 = 전량)
    target_price: Optional[Decimal] = None
    reason: str = ""


class ExitRules:
    """
    청산 규칙 엔진.

    포지션 보유 중 청산 조건을 지속적으로 평가합니다.

    Example:
        >>> rules = ExitRules(config)
        >>> signal = rules.check_stop_loss(symbol, entry_price, current_price)
    """

    def __init__(self, config: Optional[AggressiveProfileConfig] = None) -> None:
        self._config = config or AggressiveProfileConfig()

    def check_stop_loss(
        self,
        symbol: str,
        entry_price: Decimal,
        current_price: Decimal,
    ) -> Optional[ExitSignal]:
        """
        손절 조건을 확인합니다.

        Args:
            symbol: 종목코드.
            entry_price: 진입가.
            current_price: 현재가.

        Returns:
            손절 시그널 또는 None.
        """
        if entry_price <= 0:
            return None

        loss_pct = float((current_price - entry_price) / entry_price * 100)

        if loss_pct <= -self._config.initial_stop_loss_pct:
            logger.warning(
                "손절 트리거",
                extra={
                    "event": "stop_loss_triggered",
                    "symbol": symbol,
                    "entry_price": str(entry_price),
                    "current_price": str(current_price),
                    "loss_pct": loss_pct,
                },
            )
            return ExitSignal(
                symbol=symbol,
                exit_type="STOP_LOSS",
                quantity_ratio=1.0,
                target_price=current_price,
                reason=f"손절: {loss_pct:.2f}% (한도: -{self._config.initial_stop_loss_pct}%)",
            )
        return None

    def check_partial_take_profit(
        self,
        symbol: str,
        entry_price: Decimal,
        current_price: Decimal,
        partial_exits_done: int,
    ) -> Optional[ExitSignal]:
        """
        부분 익절 조건을 확인합니다.

        Args:
            symbol: 종목코드.
            entry_price: 진입가.
            current_price: 현재가.
            partial_exits_done: 이미 수행한 부분 익절 횟수.

        Returns:
            부분 익절 시그널 또는 None.
        """
        if partial_exits_done > 0:
            return None  # 부분 익절은 1회만

        if entry_price <= 0:
            return None

        profit_pct = float((current_price - entry_price) / entry_price * 100)

        if profit_pct >= self._config.partial_take_profit_pct:
            logger.info(
                "부분 익절 트리거",
                extra={
                    "event": "partial_take_profit",
                    "symbol": symbol,
                    "profit_pct": profit_pct,
                    "ratio": self._config.partial_take_profit_ratio,
                },
            )
            return ExitSignal(
                symbol=symbol,
                exit_type="PARTIAL_TAKE_PROFIT",
                quantity_ratio=self._config.partial_take_profit_ratio,
                target_price=current_price,
                reason=f"부분 익절: {profit_pct:.2f}% (목표: {self._config.partial_take_profit_pct}%)",
            )
        return None

    def check_trailing_stop(
        self,
        symbol: str,
        entry_price: Decimal,
        highest_price: Decimal,
        current_price: Decimal,
    ) -> Optional[ExitSignal]:
        """
        트레일링 스탑을 확인합니다.

        trailing_activation_pct 이상 수익 달성 후,
        고점 대비 trailing_stop_pct 이상 하락 시 청산합니다.

        Args:
            symbol: 종목코드.
            entry_price: 진입가.
            highest_price: 보유 중 최고가.
            current_price: 현재가.

        Returns:
            트레일링 스탑 시그널 또는 None.
        """
        if entry_price <= 0 or highest_price <= 0:
            return None

        # 활성화 조건: 진입가 대비 일정 수익률 이상
        profit_from_entry = float(
            (highest_price - entry_price) / entry_price * 100
        )
        if profit_from_entry < self._config.trailing_activation_pct:
            return None

        # 트레일링 체크: 고점 대비 하락
        drop_from_high = float(
            (highest_price - current_price) / highest_price * 100
        )

        if drop_from_high >= self._config.trailing_stop_pct:
            logger.info(
                "트레일링 스탑 트리거",
                extra={
                    "event": "trailing_stop_triggered",
                    "symbol": symbol,
                    "highest": str(highest_price),
                    "current": str(current_price),
                    "drop_pct": drop_from_high,
                },
            )
            return ExitSignal(
                symbol=symbol,
                exit_type="TRAILING_STOP",
                quantity_ratio=1.0,
                target_price=current_price,
                reason=f"트레일링 스탑: 고점 대비 -{drop_from_high:.2f}%",
            )
        return None

    def check_time_exit(
        self,
        symbol: str,
        entry_time: datetime,
        current_time: Optional[datetime] = None,
    ) -> Optional[ExitSignal]:
        """
        시간 청산을 확인합니다.

        진입 후 설정된 시간이 경과하면 청산합니다.

        Args:
            symbol: 종목코드.
            entry_time: 진입 시각.
            current_time: 현재 시각.

        Returns:
            시간 청산 시그널 또는 None.
        """
        now = current_time or datetime.now()
        elapsed = (now - entry_time).total_seconds() / 60

        if elapsed >= self._config.time_exit_minutes:
            return ExitSignal(
                symbol=symbol,
                exit_type="TIME_EXIT",
                quantity_ratio=1.0,
                reason=f"시간 청산: {elapsed:.0f}분 경과 (한도: {self._config.time_exit_minutes}분)",
            )
        return None

    def check_force_close(
        self,
        symbol: str,
        current_time: Optional[datetime] = None,
    ) -> Optional[ExitSignal]:
        """
        장마감 전 강제 청산을 확인합니다.

        15:20 이전에 전량 청산해야 합니다.

        Args:
            symbol: 종목코드.
            current_time: 현재 시각.

        Returns:
            강제 청산 시그널 또는 None.
        """
        now = current_time or datetime.now()
        current_time_str = now.strftime("%H:%M")

        if current_time_str >= MARKET_HOURS.force_close_start:
            return ExitSignal(
                symbol=symbol,
                exit_type="FORCE_CLOSE",
                quantity_ratio=1.0,
                reason=f"장마감 강제 청산: {current_time_str} >= {MARKET_HOURS.force_close_start}",
            )
        return None

    def evaluate_all(
        self,
        symbol: str,
        entry_price: Decimal,
        highest_price: Decimal,
        current_price: Decimal,
        entry_time: datetime,
        partial_exits_done: int = 0,
        current_time: Optional[datetime] = None,
    ) -> Optional[ExitSignal]:
        """
        모든 청산 조건을 우선순위에 따라 평가합니다.

        우선순위: 강제청산 > 손절 > 부분익절 > 트레일링 > 시간청산

        Returns:
            가장 우선순위가 높은 청산 시그널 또는 None.
        """
        # 1. 장마감 강제 청산 (최우선)
        signal = self.check_force_close(symbol, current_time)
        if signal:
            return signal

        # 2. 손절
        signal = self.check_stop_loss(symbol, entry_price, current_price)
        if signal:
            return signal

        # 3. 부분 익절
        signal = self.check_partial_take_profit(
            symbol, entry_price, current_price, partial_exits_done
        )
        if signal:
            return signal

        # 4. 트레일링 스탑
        signal = self.check_trailing_stop(
            symbol, entry_price, highest_price, current_price
        )
        if signal:
            return signal

        # 5. 시간 청산
        signal = self.check_time_exit(symbol, entry_time, current_time)
        if signal:
            return signal

        return None
