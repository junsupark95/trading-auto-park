# -*- coding: utf-8 -*-
"""
Repository 패턴 모듈.

DB CRUD 작업을 추상화합니다.
Supabase Free / 매니지드 PostgreSQL 모두 동일 인터페이스로 사용 가능합니다.
"""

import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.persistence.models import (
    OrderRecord,
    PositionRecord,
    FillRecord,
    DailyPnl,
    RiskEvent,
    SystemState,
    TradeLog,
    ScanCandidate as ScanCandidateModel,
    AIDecisionLog,
    StrategyConfig,
)

logger = logging.getLogger(__name__)


class OrderRepository:
    """주문 데이터 저장소."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> OrderRecord:
        """주문 기록을 생성합니다."""
        record = OrderRecord(**kwargs)
        self._session.add(record)
        await self._session.flush()
        return record

    async def update_status(
        self,
        order_id: UUID,
        status: str,
        filled_quantity: Optional[int] = None,
        filled_avg_price: Optional[Decimal] = None,
    ) -> None:
        """주문 상태를 갱신합니다."""
        stmt = (
            update(OrderRecord)
            .where(OrderRecord.id == order_id)
            .values(
                status=status,
                updated_at=datetime.utcnow(),
                **({"filled_quantity": filled_quantity} if filled_quantity is not None else {}),
                **({"filled_avg_price": filled_avg_price} if filled_avg_price is not None else {}),
            )
        )
        await self._session.execute(stmt)

    async def get_pending_orders(self) -> list[OrderRecord]:
        """미체결 주문을 조회합니다."""
        stmt = select(OrderRecord).where(
            OrderRecord.status.in_(["PENDING", "SUBMITTED", "PARTIAL"])
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_today_orders(self) -> list[OrderRecord]:
        """당일 주문을 조회합니다."""
        today = date.today()
        stmt = select(OrderRecord).where(
            func.date(OrderRecord.created_at) == today
        ).order_by(OrderRecord.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class PositionRepository:
    """포지션 데이터 저장소."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> PositionRecord:
        """포지션을 생성합니다."""
        record = PositionRecord(**kwargs)
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_open_positions(self) -> list[PositionRecord]:
        """열린 포지션을 조회합니다."""
        stmt = select(PositionRecord).where(
            PositionRecord.status == "OPEN"
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def close_position(
        self,
        position_id: UUID,
        exit_price: Decimal,
        exit_reason: str,
        realized_pnl: Decimal,
    ) -> None:
        """포지션을 청산 처리합니다."""
        stmt = (
            update(PositionRecord)
            .where(PositionRecord.id == position_id)
            .values(
                status="CLOSED",
                exit_price=exit_price,
                exit_reason=exit_reason,
                realized_pnl=realized_pnl,
                closed_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        await self._session.execute(stmt)

    async def get_today_symbol_count(self, symbol: str) -> int:
        """당일 특정 종목 진입 횟수."""
        today = date.today()
        stmt = select(func.count()).where(
            and_(
                PositionRecord.symbol == symbol,
                func.date(PositionRecord.created_at) == today,
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0


class DailyPnlRepository:
    """일별 손익 저장소."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_today(self) -> DailyPnl:
        """당일 손익 레코드를 가져오거나 생성합니다."""
        today = date.today()
        stmt = select(DailyPnl).where(DailyPnl.trade_date == today)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if record is None:
            record = DailyPnl(trade_date=today)
            self._session.add(record)
            await self._session.flush()

        return record

    async def update_pnl(
        self,
        trade_date: date,
        realized_pnl: Decimal,
        total_trades: int,
        winning_trades: int,
    ) -> None:
        """일별 손익을 갱신합니다."""
        stmt = (
            update(DailyPnl)
            .where(DailyPnl.trade_date == trade_date)
            .values(
                realized_pnl=realized_pnl,
                total_trades=total_trades,
                winning_trades=winning_trades,
            )
        )
        await self._session.execute(stmt)


class RiskEventRepository:
    """리스크 이벤트 저장소."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log_event(
        self,
        event_type: str,
        severity: str,
        symbol: Optional[str] = None,
        description: str = "",
        metadata: Optional[dict] = None,
    ) -> RiskEvent:
        """리스크 이벤트를 기록합니다."""
        record = RiskEvent(
            event_type=event_type,
            severity=severity,
            symbol=symbol,
            description=description,
            metadata_json=metadata or {},
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_today_events(self) -> list[RiskEvent]:
        """당일 리스크 이벤트를 조회합니다."""
        today = date.today()
        stmt = select(RiskEvent).where(
            func.date(RiskEvent.created_at) == today
        ).order_by(RiskEvent.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class SystemStateRepository:
    """시스템 상태 저장소 (서버 재시작 복구용)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_state(
        self,
        state_key: str,
        state_value: dict,
    ) -> None:
        """시스템 상태를 저장합니다."""
        stmt = select(SystemState).where(SystemState.key == state_key)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if record:
            record.value = state_value
            record.updated_at = datetime.utcnow()
        else:
            record = SystemState(key=state_key, value=state_value)
            self._session.add(record)

        await self._session.flush()

    async def load_state(self, state_key: str) -> Optional[dict]:
        """시스템 상태를 로드합니다."""
        stmt = select(SystemState).where(SystemState.key == state_key)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        return record.value if record else None


class TradeLogRepository:
    """거래 로그 저장소."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log_trade(self, **kwargs) -> TradeLog:
        """거래를 기록합니다."""
        record = TradeLog(**kwargs)
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_today_trades(self) -> list[TradeLog]:
        """당일 거래를 조회합니다."""
        today = date.today()
        stmt = select(TradeLog).where(
            func.date(TradeLog.created_at) == today
        ).order_by(TradeLog.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_daily_realized_pnl(self) -> Decimal:
        """당일 실현 손익 합계."""
        today = date.today()
        stmt = select(func.coalesce(func.sum(TradeLog.realized_pnl), 0)).where(
            func.date(TradeLog.created_at) == today
        )
        result = await self._session.execute(stmt)
        return Decimal(str(result.scalar() or 0))
