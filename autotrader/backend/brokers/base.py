# -*- coding: utf-8 -*-
"""
브로커 인터페이스 정의.

모든 증권사 어댑터가 구현해야 하는 추상 인터페이스입니다.
mock adapter와 실제 KIS adapter 모두 이 인터페이스를 따릅니다.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    """주문 방향."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """주문 유형."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    """주문 상태."""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


@dataclass
class OrderRequest:
    """주문 요청."""
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: Optional[Decimal] = None
    idempotency_key: str = ""


@dataclass
class OrderResponse:
    """주문 응답."""
    success: bool
    broker_order_id: str = ""
    status: OrderStatus = OrderStatus.PENDING
    message: str = ""
    filled_quantity: int = 0
    filled_price: Optional[Decimal] = None
    raw_response: dict = field(default_factory=dict)


@dataclass
class AccountBalance:
    """계좌 잔고."""
    total_equity: Decimal = Decimal("0")
    available_cash: Decimal = Decimal("0")
    total_profit_loss: Decimal = Decimal("0")
    total_profit_loss_pct: Decimal = Decimal("0")


@dataclass
class StockPosition:
    """보유 종목."""
    symbol: str
    name: str = ""
    quantity: int = 0
    avg_price: Decimal = Decimal("0")
    current_price: Decimal = Decimal("0")
    profit_loss: Decimal = Decimal("0")
    profit_loss_pct: Decimal = Decimal("0")


@dataclass
class MarketPrice:
    """시세 데이터."""
    symbol: str
    current_price: Decimal = Decimal("0")
    open_price: Decimal = Decimal("0")
    high_price: Decimal = Decimal("0")
    low_price: Decimal = Decimal("0")
    prev_close: Decimal = Decimal("0")
    volume: int = 0
    trade_amount: int = 0  # 거래대금 (원)
    change_pct: Decimal = Decimal("0")
    timestamp: Optional[datetime] = None


@dataclass
class OrderBookEntry:
    """호가 단일 항목."""
    price: Decimal
    quantity: int


@dataclass
class OrderBook:
    """호가 데이터."""
    symbol: str
    asks: list[OrderBookEntry] = field(default_factory=list)  # 매도 호가 (가격 오름차순)
    bids: list[OrderBookEntry] = field(default_factory=list)  # 매수 호가 (가격 내림차순)
    timestamp: Optional[datetime] = None

    @property
    def spread(self) -> Decimal:
        """호가 스프레드. 매도1호가 - 매수1호가."""
        if self.asks and self.bids:
            return self.asks[0].price - self.bids[0].price
        return Decimal("0")

    @property
    def spread_pct(self) -> Decimal:
        """호가 스프레드 비율 (%)."""
        if self.bids and self.bids[0].price > 0:
            return (self.spread / self.bids[0].price) * 100
        return Decimal("0")


class BaseBroker(ABC):
    """
    증권사 브로커 추상 인터페이스.

    모든 증권사 어댑터는 이 클래스를 상속받아 구현합니다.
    """

    @abstractmethod
    async def connect(self) -> bool:
        """브로커에 연결합니다."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """브로커 연결을 종료합니다."""
        ...

    @abstractmethod
    async def is_connected(self) -> bool:
        """연결 상태를 확인합니다."""
        ...

    @abstractmethod
    async def get_balance(self) -> AccountBalance:
        """계좌 잔고를 조회합니다."""
        ...

    @abstractmethod
    async def get_positions(self) -> list[StockPosition]:
        """보유 종목을 조회합니다."""
        ...

    @abstractmethod
    async def get_price(self, symbol: str) -> MarketPrice:
        """종목 현재가를 조회합니다."""
        ...

    @abstractmethod
    async def get_orderbook(self, symbol: str) -> OrderBook:
        """호가를 조회합니다."""
        ...

    @abstractmethod
    async def submit_order(self, request: OrderRequest) -> OrderResponse:
        """주문을 제출합니다."""
        ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> OrderResponse:
        """주문을 취소합니다."""
        ...

    @abstractmethod
    async def get_order_status(self, broker_order_id: str) -> OrderResponse:
        """주문 상태를 조회합니다."""
        ...
