# -*- coding: utf-8 -*-
"""
체결 추적 모듈.

미체결 주문의 상태를 추적하고, 장기 미체결을 자동 취소합니다.
체결 통보(WebSocket)를 처리하여 포지션 상태를 갱신합니다.

설계 원칙:
  - 미체결 주문 60초 타임아웃 (기본)
  - 체결 통보 수신 시 즉시 포지션 갱신
  - 타임아웃 시 자동 취소 + 로그
"""

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from backend.brokers.base import BaseBroker, OrderStatus

logger = logging.getLogger(__name__)


class FillTracker:
    """
    체결 추적기.

    미체결 주문을 추적하고, 타임아웃 시 자동 취소합니다.

    Attributes:
        pending_orders: 추적 중인 미체결 주문.
        filled_orders: 체결 완료 주문.

    Example:
        >>> tracker = FillTracker(broker, timeout_seconds=60)
        >>> tracker.track_order("005930", "KIS123", "BUY", 10, datetime.now())
        >>> # 주기적으로 호출
        >>> auto_cancelled = await tracker.check_timeouts()
    """

    def __init__(
        self,
        broker: BaseBroker,
        timeout_seconds: int = 60,
    ) -> None:
        self._broker = broker
        self._timeout = timeout_seconds
        # broker_order_id -> order_info
        self._pending: dict[str, dict] = {}
        self._filled: list[dict] = []
        self._cancelled: list[dict] = []

    @property
    def pending_count(self) -> int:
        """미체결 주문 수."""
        return len(self._pending)

    @property
    def pending_symbols(self) -> set[str]:
        """미체결 주문이 있는 종목 세트."""
        return {o["symbol"] for o in self._pending.values()}

    def track_order(
        self,
        symbol: str,
        broker_order_id: str,
        side: str,
        quantity: int,
        submitted_at: datetime,
        price: Optional[Decimal] = None,
    ) -> None:
        """
        주문을 추적 대상에 추가합니다.

        Args:
            symbol: 종목코드.
            broker_order_id: 브로커 주문 ID.
            side: 주문 방향 (BUY/SELL).
            quantity: 주문 수량.
            submitted_at: 주문 제출 시각.
            price: 주문 가격.
        """
        self._pending[broker_order_id] = {
            "symbol": symbol,
            "broker_order_id": broker_order_id,
            "side": side,
            "quantity": quantity,
            "submitted_at": submitted_at,
            "price": price,
            "filled_quantity": 0,
        }

        logger.info(
            "주문 추적 시작",
            extra={
                "event": "order_tracked",
                "symbol": symbol,
                "broker_order_id": broker_order_id,
                "side": side,
                "quantity": quantity,
            },
        )

    def on_fill(
        self,
        broker_order_id: str,
        filled_quantity: int,
        filled_price: Decimal,
    ) -> Optional[dict]:
        """
        체결 통보 처리.

        Args:
            broker_order_id: 브로커 주문 ID.
            filled_quantity: 체결 수량.
            filled_price: 체결 가격.

        Returns:
            체결 완료 시 주문 정보, 아니면 None (부분 체결).
        """
        if broker_order_id not in self._pending:
            logger.warning(f"추적되지 않는 체결 통보: {broker_order_id}")
            return None

        order = self._pending[broker_order_id]
        order["filled_quantity"] += filled_quantity
        order["filled_price"] = filled_price
        order["filled_at"] = datetime.now()

        if order["filled_quantity"] >= order["quantity"]:
            # 전량 체결
            completed = self._pending.pop(broker_order_id)
            self._filled.append(completed)

            logger.info(
                "전량 체결 확인",
                extra={
                    "event": "order_fully_filled",
                    "symbol": order["symbol"],
                    "broker_order_id": broker_order_id,
                    "filled_quantity": order["filled_quantity"],
                    "filled_price": str(filled_price),
                },
            )
            return completed
        else:
            logger.info(
                "부분 체결",
                extra={
                    "event": "order_partially_filled",
                    "symbol": order["symbol"],
                    "filled": order["filled_quantity"],
                    "total": order["quantity"],
                },
            )
            return None

    async def check_timeouts(self) -> list[dict]:
        """
        미체결 주문 타임아웃을 확인하고 자동 취소합니다.

        Returns:
            자동 취소된 주문 리스트.
        """
        now = datetime.now()
        timed_out = []

        for oid, order in list(self._pending.items()):
            elapsed = (now - order["submitted_at"]).total_seconds()
            if elapsed >= self._timeout:
                # 자동 취소 시도
                logger.warning(
                    "미체결 타임아웃 - 자동 취소",
                    extra={
                        "event": "order_timeout_cancel",
                        "symbol": order["symbol"],
                        "broker_order_id": oid,
                        "elapsed_seconds": elapsed,
                    },
                )

                try:
                    result = await self._broker.cancel_order(oid)
                    if result.success:
                        cancelled = self._pending.pop(oid)
                        cancelled["cancel_reason"] = "TIMEOUT"
                        cancelled["cancelled_at"] = now.isoformat()
                        self._cancelled.append(cancelled)
                        timed_out.append(cancelled)
                except Exception as e:
                    logger.error(
                        f"타임아웃 취소 실패: {oid} - {e}",
                        extra={
                            "event": "timeout_cancel_failed",
                            "broker_order_id": oid,
                            "error": str(e),
                        },
                    )

        return timed_out

    async def poll_order_status(self) -> list[dict]:
        """
        미체결 주문 상태를 폴링합니다 (WebSocket 체결통보 백업).

        Returns:
            새로 체결 확인된 주문 리스트.
        """
        newly_filled = []

        for oid in list(self._pending.keys()):
            try:
                result = await self._broker.get_order_status(oid)
                if result.status == OrderStatus.FILLED and result.filled_price:
                    filled = self.on_fill(
                        oid, result.filled_quantity, result.filled_price
                    )
                    if filled:
                        newly_filled.append(filled)
                elif result.status == OrderStatus.CANCELLED:
                    cancelled = self._pending.pop(oid, None)
                    if cancelled:
                        cancelled["cancel_reason"] = "BROKER_CANCELLED"
                        self._cancelled.append(cancelled)
            except Exception:
                pass

        return newly_filled

    def get_summary(self) -> dict:
        """추적 상태 요약."""
        return {
            "pending_count": self.pending_count,
            "filled_count": len(self._filled),
            "cancelled_count": len(self._cancelled),
            "pending_symbols": list(self.pending_symbols),
            "timeout_seconds": self._timeout,
        }
