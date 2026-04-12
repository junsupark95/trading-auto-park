# -*- coding: utf-8 -*-
"""
백테스트 시뮬레이터 (Mock Broker 확장).

과거 가격 데이터를 주입받아 주문 체결을 시뮬레이션합니다.
슬리피지와 수수료, 세금을 반영합니다.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from backend.brokers.base import (
    BaseBroker,
    AccountBalance,
    MarketPrice,
    OrderBook,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
    StockPosition,
)


class BacktestSimulator(BaseBroker):
    """
    백테스트용 시뮬레이티드 브로커.

    미리 준비된 틱/분봉 데이터를 사용하여 체결을 처리합니다.
    """

    def __init__(self, starting_capital: int = 10000000) -> None:
        self._capital = Decimal(str(starting_capital))
        self._available_cash = self._capital
        self._positions: dict[str, StockPosition] = {}
        self._pending_orders: dict[str, OrderRequest] = {}
        self._order_status: dict[str, OrderStatus] = {}

        # 수수료율 (매수/매도 0.015%)
        self.fee_rate = Decimal("0.00015")
        # 거래세 (매도시 0.2%)
        self.tax_rate = Decimal("0.002")
        # 슬리피지 (틱당)
        self.slippage_ticks = 1

        self._current_prices: dict[str, MarketPrice] = {}
        self._order_counter = 0

    def inject_market_data(self, price_data: MarketPrice) -> None:
        """현재가 데이터를 주입하고 미체결 주문의 체결 여부를 평가합니다."""
        self._current_prices[price_data.symbol] = price_data
        self._evaluate_orders(price_data)

    def _evaluate_orders(self, price_data: MarketPrice) -> None:
        """조건 충족 시 주문을 체결 처리합니다."""
        # 심플한 백테스트 체결 로직: 시장가 주문은 다음 시가/현재가로 상정
        for oid, req in list(self._pending_orders.items()):
            if req.symbol != price_data.symbol:
                continue

            # 시장가 체결 처리
            if req.order_type == OrderType.MARKET:
                fill_price = price_data.current_price
                if req.side == OrderSide.BUY:
                    # 슬리피지: 더 비싸게 삼
                    fill_price *= Decimal("1.001")
                    total_cost = (fill_price * req.quantity) * (1 + self.fee_rate)
                    if self._available_cash >= total_cost:
                        self._available_cash -= total_cost
                        self._add_position(req.symbol, req.quantity, fill_price)
                        self._order_status[oid] = OrderStatus.FILLED
                        del self._pending_orders[oid]
                elif req.side == OrderSide.SELL:
                    # 슬리피지: 더 싸게 팖
                    fill_price *= Decimal("0.999")
                    gross = fill_price * req.quantity
                    net = gross * (1 - self.fee_rate - self.tax_rate)
                    self._available_cash += net
                    self._remove_position(req.symbol, req.quantity, fill_price)
                    self._order_status[oid] = OrderStatus.FILLED
                    del self._pending_orders[oid]

    def _add_position(self, symbol: str, qty: int, price: Decimal) -> None:
        if symbol in self._positions:
            pos = self._positions[symbol]
            new_qty = pos.quantity + qty
            new_avg = ((pos.avg_price * pos.quantity) + (price * qty)) / new_qty
            pos.quantity = new_qty
            pos.avg_price = new_avg
        else:
            self._positions[symbol] = StockPosition(
                symbol=symbol,
                name=symbol,
                quantity=qty,
                avg_price=price,
                current_price=price,
            )

    def _remove_position(self, symbol: str, qty: int, price: Decimal) -> None:
        if symbol in self._positions:
            pos = self._positions[symbol]
            pos.quantity = max(0, pos.quantity - qty)
            if pos.quantity == 0:
                del self._positions[symbol]

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        pass

    async def is_connected(self) -> bool:
        return True

    async def get_balance(self) -> AccountBalance:
        pos_value = sum(
            p.quantity * self._current_prices.get(p.symbol, p).current_price
            for p in self._positions.values()
        )
        return AccountBalance(
            total_equity=self._available_cash + pos_value,
            available_cash=self._available_cash,
        )

    async def get_positions(self) -> list[StockPosition]:
        return list(self._positions.values())

    async def get_price(self, symbol: str) -> MarketPrice:
        if symbol in self._current_prices:
            return self._current_prices[symbol]
        return MarketPrice(symbol=symbol, current_price=Decimal("0"))

    async def get_orderbook(self, symbol: str) -> OrderBook:
        return OrderBook(symbol=symbol, asks=[], bids=[])

    async def submit_order(self, request: OrderRequest) -> OrderResponse:
        self._order_counter += 1
        oid = f"TEST_ORD_{self._order_counter}"
        self._pending_orders[oid] = request
        self._order_status[oid] = OrderStatus.SUBMITTED
        return OrderResponse(
            success=True,
            broker_order_id=oid,
            status=OrderStatus.SUBMITTED,
        )

    async def cancel_order(self, broker_order_id: str) -> OrderResponse:
        if broker_order_id in self._pending_orders:
            del self._pending_orders[broker_order_id]
            self._order_status[broker_order_id] = OrderStatus.CANCELLED
            return OrderResponse(success=True, broker_order_id=broker_order_id, status=OrderStatus.CANCELLED)
        return OrderResponse(success=False, broker_order_id=broker_order_id, status=OrderStatus.ERROR)

    async def get_order_status(self, broker_order_id: str) -> OrderResponse:
        status = self._order_status.get(broker_order_id, OrderStatus.ERROR)
        return OrderResponse(
            success=True,
            broker_order_id=broker_order_id,
            status=status,
        )
