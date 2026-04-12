# -*- coding: utf-8 -*-
"""
주문 관리자 모듈.

주문 생성, 제출, 추적, 중복 방지를 담당합니다.
멱등성 키를 사용하여 동일 주문의 중복 제출을 방지합니다.
미체결 주문의 타임아웃을 관리합니다.

설계 원칙:
  - 주문 전 반드시 RiskEngine 통과 필요
  - 실전 주문 함수에는 @require_live_trading 보호장치
  - 주문 직전/직후 중복 제출 방지
  - 장애 발생 시 조용한 실패 금지, 명확한 상태 전이와 로그
"""

import hashlib
import logging
import time
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from backend.brokers.base import (
    BaseBroker,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
)
from backend.config.settings import get_settings
from backend.risk.safety_rails import require_live_trading

logger = logging.getLogger(__name__)


class OrderManager:
    """
    주문 관리자.

    주문의 전체 생명주기를 관리합니다:
    생성 → 중복 검사 → 제출 → 체결 추적 → 완료/취소

    Attributes:
        pending_orders: 미체결 주문 목록.
        filled_orders: 체결 완료 주문 목록.

    Example:
        >>> manager = OrderManager(broker)
        >>> response = await manager.submit_buy("005930", 10, Decimal("65000"))
    """

    def __init__(self, broker: BaseBroker) -> None:
        self._broker = broker
        self._pending_orders: dict[str, dict] = {}  # idempotency_key -> order info
        self._filled_orders: list[dict] = []
        self._recent_keys: dict[str, float] = {}  # 중복 방지용 최근 키
        self._order_history: list[dict] = []

    @property
    def pending_count(self) -> int:
        """미체결 주문 수."""
        return len(self._pending_orders)

    @property
    def has_pending_for(self) -> set[str]:
        """미체결 주문이 있는 종목 목록."""
        return {info["symbol"] for info in self._pending_orders.values()}

    def _generate_idempotency_key(
        self,
        symbol: str,
        side: str,
        quantity: int,
    ) -> str:
        """
        멱등성 키를 생성합니다.

        동일 종목+방향+수량+시간(5초 윈도우) 조합으로 생성하여
        단기간 내 동일 주문의 중복 제출을 방지합니다.
        """
        time_window = int(time.time() / 5)  # 5초 윈도우
        raw = f"{symbol}:{side}:{quantity}:{time_window}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _check_duplicate(self, key: str) -> bool:
        """
        중복 주문 여부를 확인합니다.

        Returns:
            True이면 중복 (차단해야 함).
        """
        now = time.time()
        # 오래된 키 정리
        self._recent_keys = {
            k: t for k, t in self._recent_keys.items()
            if now - t < 10  # 10초 이내 키만 유지
        }

        if key in self._recent_keys:
            logger.warning(
                "중복 주문 감지 - 차단",
                extra={
                    "event": "duplicate_order_blocked",
                    "idempotency_key": key,
                },
            )
            return True

        if key in self._pending_orders:
            logger.warning(
                "이미 미체결 중인 동일 주문 - 차단",
                extra={
                    "event": "pending_duplicate_blocked",
                    "idempotency_key": key,
                },
            )
            return True

        return False

    @require_live_trading
    async def submit_buy(
        self,
        symbol: str,
        quantity: int,
        price: Optional[Decimal] = None,
        order_type: OrderType = OrderType.LIMIT,
    ) -> OrderResponse:
        """
        매수 주문을 제출합니다.

        @require_live_trading 보호장치:
          - paper 모드: mock adapter를 통해 정상 실행
          - live 모드: live_trading=true, confirm_live_orders=true 필수

        Args:
            symbol: 종목코드.
            quantity: 수량.
            price: 주문가격 (지정가). None이면 시장가.
            order_type: 주문 유형.

        Returns:
            OrderResponse: 주문 결과.
        """
        key = self._generate_idempotency_key(symbol, "BUY", quantity)

        if self._check_duplicate(key):
            return OrderResponse(
                success=False,
                status=OrderStatus.REJECTED,
                message="중복 주문 차단",
            )

        request = OrderRequest(
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=order_type,
            quantity=quantity,
            price=price,
            idempotency_key=key,
        )

        # 키 등록
        self._recent_keys[key] = time.time()

        logger.info(
            "매수 주문 제출",
            extra={
                "event": "buy_order_submit",
                "symbol": symbol,
                "quantity": quantity,
                "price": str(price) if price else "MARKET",
                "idempotency_key": key,
            },
        )

        try:
            response = await self._broker.submit_order(request)

            order_record = {
                "id": str(uuid.uuid4()),
                "idempotency_key": key,
                "symbol": symbol,
                "side": "BUY",
                "quantity": quantity,
                "price": str(price) if price else "MARKET",
                "status": response.status.value,
                "broker_order_id": response.broker_order_id,
                "submitted_at": datetime.now().isoformat(),
            }

            if response.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED):
                self._pending_orders[key] = order_record
            elif response.status == OrderStatus.FILLED:
                order_record["filled_at"] = datetime.now().isoformat()
                order_record["filled_price"] = str(response.filled_price)
                self._filled_orders.append(order_record)

            self._order_history.append(order_record)
            return response

        except Exception as e:
            logger.error(
                "매수 주문 실패",
                extra={
                    "event": "buy_order_error",
                    "symbol": symbol,
                    "error": str(e),
                },
            )
            return OrderResponse(
                success=False,
                status=OrderStatus.ERROR,
                message=str(e),
            )

    @require_live_trading
    async def submit_sell(
        self,
        symbol: str,
        quantity: int,
        price: Optional[Decimal] = None,
        order_type: OrderType = OrderType.LIMIT,
        reason: str = "",
    ) -> OrderResponse:
        """
        매도 주문을 제출합니다.

        손절/익절/시간청산 등 청산 사유를 reason으로 기록합니다.

        Args:
            symbol: 종목코드.
            quantity: 수량.
            price: 주문가격.
            order_type: 주문 유형.
            reason: 청산 사유 (예: "stop_loss", "take_profit").

        Returns:
            OrderResponse: 주문 결과.
        """
        key = self._generate_idempotency_key(symbol, "SELL", quantity)

        if self._check_duplicate(key):
            return OrderResponse(
                success=False,
                status=OrderStatus.REJECTED,
                message="중복 매도 주문 차단",
            )

        request = OrderRequest(
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=order_type,
            quantity=quantity,
            price=price,
            idempotency_key=key,
        )

        self._recent_keys[key] = time.time()

        logger.info(
            "매도 주문 제출",
            extra={
                "event": "sell_order_submit",
                "symbol": symbol,
                "quantity": quantity,
                "price": str(price) if price else "MARKET",
                "reason": reason,
                "idempotency_key": key,
            },
        )

        try:
            response = await self._broker.submit_order(request)

            order_record = {
                "id": str(uuid.uuid4()),
                "idempotency_key": key,
                "symbol": symbol,
                "side": "SELL",
                "quantity": quantity,
                "price": str(price) if price else "MARKET",
                "status": response.status.value,
                "broker_order_id": response.broker_order_id,
                "reason": reason,
                "submitted_at": datetime.now().isoformat(),
            }

            if response.status == OrderStatus.FILLED:
                order_record["filled_at"] = datetime.now().isoformat()
                self._filled_orders.append(order_record)
            else:
                self._pending_orders[key] = order_record

            self._order_history.append(order_record)
            return response

        except Exception as e:
            logger.error(
                "매도 주문 실패",
                extra={
                    "event": "sell_order_error",
                    "symbol": symbol,
                    "error": str(e),
                    "reason": reason,
                },
            )
            return OrderResponse(
                success=False,
                status=OrderStatus.ERROR,
                message=str(e),
            )

    def get_pending_orders(self) -> list[dict]:
        """미체결 주문 목록."""
        return list(self._pending_orders.values())

    def get_order_history(self) -> list[dict]:
        """전체 주문 이력."""
        return self._order_history.copy()

    def clear_filled(self, key: str) -> None:
        """체결 완료된 주문을 미체결에서 제거."""
        self._pending_orders.pop(key, None)
