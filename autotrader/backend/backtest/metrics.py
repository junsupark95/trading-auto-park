# -*- coding: utf-8 -*-
"""
백테스트 성과 분석 도구.

샤프 비율, 최대 낙폭(MDD), 수익 곡선 분석 등을 수행합니다.
"""

from dataclasses import dataclass
from decimal import Decimal
import numpy as np


@dataclass
class BacktestResult:
    """백테스트 결과 요약."""
    initial_capital: Decimal
    final_capital: Decimal
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int


def calculate_metrics(
    initial_capital: Decimal,
    equity_curve: list[Decimal],
    trades: list[Decimal],
    risk_free_rate: float = 0.02,
) -> BacktestResult:
    """
    에퀴티 커브와 거래 결과 배열을 받아서 백테스트 결과를 계산합니다.

    Args:
        initial_capital: 시작 자금
        equity_curve: 일별/분별 자본 커브
        trades: 거래별 청산 손익 배열
        risk_free_rate: 무위험 수익률 (기본 2%)
    """
    if not equity_curve:
        return BacktestResult(initial_capital, initial_capital, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    final_capital = equity_curve[-1]
    total_return_pct = float((final_capital - initial_capital) / initial_capital * 100)

    # 드로다운 계산
    eq_array = np.array([float(x) for x in equity_curve])
    peak = np.maximum.accumulate(eq_array)
    drawdowns = (peak - eq_array) / peak * 100
    max_drawdown_pct = np.max(drawdowns) if len(drawdowns) > 0 else 0.0

    # 샤프 비율 (일 단위 기준이라 가정 시 단순화)
    returns = np.diff(eq_array) / eq_array[:-1]
    sharpe_ratio = 0.0
    if len(returns) > 1 and np.std(returns) != 0:
        sharpe_ratio = np.sqrt(252) * np.mean(returns - (risk_free_rate / 252)) / np.std(returns)

    # 트레이드 분석
    wins = [float(t) for t in trades if t > 0]
    losses = [float(t) for t in trades if t <= 0]
    total_trades = len(trades)
    winning_trades = len(wins)
    losing_trades = len(losses)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')

    return BacktestResult(
        initial_capital=initial_capital,
        final_capital=final_capital,
        total_return_pct=total_return_pct,
        annualized_return_pct=total_return_pct,  # 간소화
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=0.0,  # 향후 구현
        win_rate=win_rate,
        profit_factor=profit_factor,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
    )
