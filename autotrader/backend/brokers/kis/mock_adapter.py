# -*- coding: utf-8 -*-
"""
Mock 브로커 어댑터.

Paper trading 모드에서 사용하는 모의 브로커입니다.
실제 API 호출 없이 주문/체결/잔고를 시뮬레이션합니다.
테스트와 개발 단계에서 사용됩니다.
"""

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from backend.brokers.base import (
    AccountBalance,
    BaseBroker,
    MarketPrice,
    OrderBook,
    OrderBookEntry,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    StockPosition,
)

logger = logging.getLogger(__name__)


class MockBroker(BaseBroker):
    """
    모의 브로커 어댑터.

    paper trading과 테스트에 사용됩니다.
    실제 API 호출 없이 가상의 주문/체결을 처리합니다.

    Example:
        >>> broker = MockBroker(initial_cash=Decimal("10000000"))
        >>> await broker.connect()
        >>> order = OrderRequest(symbol="005930", side=OrderSide.BUY,
        ...     order_type=OrderType.MARKET, quantity=10)
        >>> result = await broker.submit_order(order)
    """

    def __init__(self, initial_cash: Decimal = Decimal("10000000")) -> None:
        self._connected: bool = False
        self._cash: Decimal = initial_cash
        self._initial_cash: Decimal = initial_cash
        self._positions: dict[str, StockPosition] = {}
        self._orders: dict[str, dict] = {}
        self._mock_prices: dict[str, Decimal] = {
            "005930": Decimal("65000"),   # 삼성전자
            "000660": Decimal("180000"),  # SK하이닉스
            "035720": Decimal("55000"),   # 카카오
        }

    async def connect(self) -> bool:
        """모의 연결."""
        self._connected = True
        logger.info("[MockBroker] 연결 완료")
        return True

    async def disconnect(self) -> None:
        """모의 연결 해제."""
        self._connected = False
        logger.info("[MockBroker] 연결 해제")

    async def is_connected(self) -> bool:
        """연결 상태."""
        return self._connected

    async def get_balance(self) -> AccountBalance:
        """모의 잔고 조회."""
        total_equity = self._cash
        for pos in self._positions.values():
            total_equity += pos.current_price * pos.quantity

        return AccountBalance(
            total_equity=total_equity,
            available_cash=self._cash,
            total_profit_loss=total_equity - self._initial_cash,
            total_profit_loss_pct=(
                ((total_equity - self._initial_cash) / self._initial_cash * 100)
                if self._initial_cash > 0
                else Decimal("0")
            ),
        )

    async def get_positions(self) -> list[StockPosition]:
        """모의 보유 종목."""
        return list(self._positions.values())

    async def get_price(self, symbol: str) -> MarketPrice:
        """모의 시세."""
        price = self._mock_prices.get(symbol, Decimal("50000"))
        return MarketPrice(
            symbol=symbol,
            current_price=price,
            open_price=price * Decimal("0.98"),
            high_price=price * Decimal("1.03"),
            low_price=price * Decimal("0.97"),
            prev_close=price * Decimal("0.97"),
            volume=1000000,
            trade_amount=int(price * 1000000),
            change_pct=Decimal("3.09"),
            timestamp=datetime.now(),
        )

    async def get_orderbook(self, symbol: str) -> OrderBook:
        """모의 호가."""
        price = self._mock_prices.get(symbol, Decimal("50000"))
        step = max(Decimal("1"), price * Decimal("0.001"))

        return OrderBook(
            symbol=symbol,
            asks=[
                OrderBookEntry(price=price + step * i, quantity=100 * (6 - i))
                for i in range(1, 6)
            ],
            bids=[
                OrderBookEntry(price=price - step * i, quantity=100 * (6 - i))
                for i in range(1, 6)
            ],
            timestamp=datetime.now(),
        )

    async def submit_order(self, request: OrderRequest) -> OrderResponse:
        """
        모의 주문 제출 및 즉시 체결.

        Paper 모드에서는 주문 즉시 체결로 처리합니다.
        """
        order_id = str(uuid.uuid4())[:8]
        price = self._mock_prices.get(request.symbol, Decimal("50000"))

        # 슬리피지 적용 (보수적)
        if request.side == OrderSide.BUY:
            fill_price = price * Decimal("1.001")  # 0.1% 불리하게
        else:
            fill_price = price * Decimal("0.999")

        # 잔고 체크
        if request.side == OrderSide.BUY:
            cost = fill_price * request.quantity
            if cost > self._cash:
                return OrderResponse(
                    success=False,
                    broker_order_id=order_id,
                    status=OrderStatus.REJECTED,
                    message=f"잔고 부족: 필요 {cost}, 가용 {self._cash}",
                )

            # 매수 체결
            self._cash -= cost
            if request.symbol in self._positions:
                pos = self._positions[request.symbol]
                total_qty = pos.quantity + request.quantity
                pos.avg_price = (
                    (pos.avg_price * pos.quantity + fill_price * request.quantity)
                    / total_qty
                )
                pos.quantity = total_qty
            else:
                self._positions[request.symbol] = StockPosition(
                    symbol=request.symbol,
                    name=f"MOCK_{request.symbol}",
                    quantity=request.quantity,
                    avg_price=fill_price,
                    current_price=price,
                )

        elif request.side == OrderSide.SELL:
            if request.symbol not in self._positions:
                return OrderResponse(
                    success=False,
                    broker_order_id=order_id,
                    status=OrderStatus.REJECTED,
                    message=f"보유 종목 없음: {request.symbol}",
                )

            pos = self._positions[request.symbol]
            if request.quantity > pos.quantity:
                return OrderResponse(
                    success=False,
                    broker_order_id=order_id,
                    status=OrderStatus.REJECTED,
                    message=f"보유 수량 부족: {pos.quantity} < {request.quantity}",
                )

            # 매도 체결
            proceeds = fill_price * request.quantity
            commission = proceeds * Decimal("0.00015")  # 수수료 0.015%
            tax = proceeds * Decimal("0.0018")  # 세금 0.18% (가정)
            self._cash += proceeds - commission - tax
            pos.quantity -= request.quantity

            if pos.quantity == 0:
                del self._positions[request.symbol]

        logger.info(
            f"[MockBroker] 주문 체결: {request.side.value} {request.symbol} "
            f"x{request.quantity} @ {fill_price}",
            extra={
                "event": "mock_order_filled",
                "symbol": request.symbol,
                "side": request.side.value,
                "quantity": request.quantity,
                "price": str(fill_price),
            },
        )

        return OrderResponse(
            success=True,
            broker_order_id=order_id,
            status=OrderStatus.FILLED,
            filled_quantity=request.quantity,
            filled_price=fill_price,
            message="모의 체결 완료",
        )

    async def cancel_order(self, broker_order_id: str) -> OrderResponse:
        """모의 주문 취소."""
        return OrderResponse(
            success=True,
            broker_order_id=broker_order_id,
            status=OrderStatus.CANCELLED,
            message="모의 취소 완료",
        )

    async def get_order_status(self, broker_order_id: str) -> OrderResponse:
        """모의 주문 상태."""
        return OrderResponse(
            success=True,
            broker_order_id=broker_order_id,
            status=OrderStatus.FILLED,
            message="모의 체결 완료",
        )

    def set_mock_price(self, symbol: str, price: Decimal) -> None:
        """테스트용 모의 가격 설정."""
        self._mock_prices[symbol] = price
        if symbol in self._positions:
            self._positions[symbol].current_price = price
