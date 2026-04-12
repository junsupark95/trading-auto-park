# -*- coding: utf-8 -*-
"""
메트릭 수집 모듈.

거래 성과, 리스크 지표, 시스템 지표를 실시간으로 추적합니다.
API 응답으로 대시보드에 제공합니다.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DailyMetrics:
    """일별 거래 메트릭."""
    trade_date: date = field(default_factory=date.today)
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    max_drawdown_pct: float = 0.0
    largest_win: Decimal = Decimal("0")
    largest_loss: Decimal = Decimal("0")
    avg_win: Decimal = Decimal("0")
    avg_loss: Decimal = Decimal("0")
    avg_holding_time_min: float = 0.0
    entry_count: int = 0
    exit_count: int = 0
    emergency_stops: int = 0
    vi_blocks: int = 0
    risk_violations: int = 0
    ai_calls: int = 0
    api_errors: int = 0

    @property
    def win_rate(self) -> float:
        """승률 (%)."""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100

    @property
    def profit_factor(self) -> float:
        """수익 팩터 (총 수익 / 총 손실)."""
        if self.avg_loss == 0 or self.losing_trades == 0:
            return float("inf") if self.winning_trades > 0 else 0.0
        total_wins = self.avg_win * self.winning_trades
        total_losses = abs(self.avg_loss) * self.losing_trades
        if total_losses == 0:
            return float("inf")
        return float(total_wins / total_losses)

    @property
    def risk_reward_ratio(self) -> float:
        """리스크 리워드 비율."""
        if self.avg_loss == 0:
            return 0.0
        return float(abs(self.avg_win / self.avg_loss))

    @property
    def daily_pnl(self) -> Decimal:
        """당일 총 손익 (실현 + 미실현)."""
        return self.realized_pnl + self.unrealized_pnl


class MetricsCollector:
    """
    메트릭 수집기.

    장중 실시간으로 메트릭을 갱신합니다.

    Example:
        >>> collector = MetricsCollector()
        >>> collector.record_trade(pnl=Decimal("15000"), holding_min=12.5)
        >>> print(collector.today.win_rate)
    """

    def __init__(self) -> None:
        self._today = DailyMetrics()
        self._history: list[DailyMetrics] = []

    @property
    def today(self) -> DailyMetrics:
        """금일 메트릭."""
        # 날짜 변경 시 자동 리셋
        if self._today.trade_date != date.today():
            self._history.append(self._today)
            self._today = DailyMetrics()
        return self._today

    def record_trade(
        self,
        pnl: Decimal,
        holding_min: float = 0,
    ) -> None:
        """
        거래를 기록합니다.

        Args:
            pnl: 실현 손익.
            holding_min: 보유 시간 (분).
        """
        m = self.today
        m.total_trades += 1

        if pnl > 0:
            m.winning_trades += 1
            if pnl > m.largest_win:
                m.largest_win = pnl
        elif pnl < 0:
            m.losing_trades += 1
            if pnl < m.largest_loss:
                m.largest_loss = pnl
        else:
            m.breakeven_trades += 1

        m.realized_pnl += pnl

        # 평균 업데이트
        if m.winning_trades > 0:
            total_wins = m.avg_win * (m.winning_trades - 1) + max(pnl, Decimal("0"))
            m.avg_win = total_wins / m.winning_trades
        if m.losing_trades > 0:
            total_losses = m.avg_loss * (m.losing_trades - 1) + min(pnl, Decimal("0"))
            m.avg_loss = total_losses / m.losing_trades

        # 평균 보유 시간 업데이트
        if holding_min > 0:
            prev_total = m.avg_holding_time_min * (m.total_trades - 1)
            m.avg_holding_time_min = (prev_total + holding_min) / m.total_trades

    def record_entry(self) -> None:
        """진입 기록."""
        self.today.entry_count += 1

    def record_exit(self) -> None:
        """청산 기록."""
        self.today.exit_count += 1

    def record_emergency_stop(self) -> None:
        """긴급 정지 기록."""
        self.today.emergency_stops += 1

    def record_vi_block(self) -> None:
        """VI 차단 기록."""
        self.today.vi_blocks += 1

    def record_risk_violation(self) -> None:
        """리스크 위반 기록."""
        self.today.risk_violations += 1

    def record_ai_call(self) -> None:
        """AI 호출 기록."""
        self.today.ai_calls += 1

    def record_api_error(self) -> None:
        """API 오류 기록."""
        self.today.api_errors += 1

    def update_unrealized_pnl(self, pnl: Decimal) -> None:
        """미실현 손익 갱신."""
        self.today.unrealized_pnl = pnl

    def get_summary(self) -> dict:
        """금일 메트릭 요약."""
        m = self.today
        return {
            "date": m.trade_date.isoformat(),
            "total_trades": m.total_trades,
            "win_rate": round(m.win_rate, 1),
            "profit_factor": round(m.profit_factor, 2),
            "realized_pnl": str(m.realized_pnl),
            "unrealized_pnl": str(m.unrealized_pnl),
            "daily_pnl": str(m.daily_pnl),
            "winning_trades": m.winning_trades,
            "losing_trades": m.losing_trades,
            "largest_win": str(m.largest_win),
            "largest_loss": str(m.largest_loss),
            "avg_holding_time_min": round(m.avg_holding_time_min, 1),
            "risk_violations": m.risk_violations,
            "vi_blocks": m.vi_blocks,
            "api_errors": m.api_errors,
            "ai_calls": m.ai_calls,
        }
