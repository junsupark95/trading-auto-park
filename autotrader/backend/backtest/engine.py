# -*- coding: utf-8 -*-
"""
과거 데이터 기반 백테스트 엔젠.

백테스트 시뮬레이터를 활용하여 특정 기간의 거래 결과를 도출합니다.
"""

import asyncio
from datetime import datetime
from decimal import Decimal
import logging

from backend.backtest.simulator import BacktestSimulator
from backend.backtest.metrics import calculate_metrics, BacktestResult
from backend.strategy.engine import TradingEngine
from backend.brokers.base import MarketPrice

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    히스토리컬 데이터 기반 백테스터.

    Trading Engine 코어 로직을 훼손하지 않고 과거 데이터를 주입하여
    전략의 성능을 테스트합니다.
    """

    def __init__(self, starting_capital: int = 10000000):
        self.simulator = BacktestSimulator(starting_capital=starting_capital)
        self.trading_engine = TradingEngine(broker=self.simulator)
        self.equity_curve: list[Decimal] = []
        self.trades: list[Decimal] = []  # 완료된 트레이드의 손익 기록

    async def run(self, historical_data: list[MarketPrice]) -> BacktestResult:
        """
        주어진 과거 데이터스트림을 통해 백테스트를 실행합니다.
        
        주의: 실제 TradingEngine은 asyncio sleep 등 실시간 로직이 포함되어 있으므로,
        진정한 의미의 빠른 백테스트를 위해서는 Engine의 시간 흐름을 모킹하거나 별도 Event Loop 필요.
        본 구현은 개념적인 인터페이스를 제공합니다.
        """
        logger.info(f"백테스트 시작: {len(historical_data)} 틱 데이터")
        
        await self.trading_engine._broker.connect()
        initial_capital = (await self.simulator.get_balance()).total_equity

        # 데이터 주입 루프
        for data_point in historical_data:
            # 1. 시세 주입 (Simulator)
            self.simulator.inject_market_data(data_point)
            
            # 2. 엔진 상태 업데이트 (가상 시간)
            # await self.trading_engine._main_loop_tick() # 실시간 sleep이 걸려있어 수정 필요

            # 3. 에퀴티 커브 기록
            bal = await self.simulator.get_balance()
            self.equity_curve.append(bal.total_equity)

        await self.trading_engine._broker.disconnect()
        
        # 임시 트레이드 기록 추출
        for pos in await self.simulator.get_positions():
            self.trades.append(pos.profit_loss)

        return calculate_metrics(
            initial_capital=initial_capital,
            equity_curve=self.equity_curve,
            trades=self.trades
        )
