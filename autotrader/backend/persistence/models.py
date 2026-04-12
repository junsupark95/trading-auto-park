# -*- coding: utf-8 -*-
"""
SQLAlchemy ORM 모델 정의.

10개 핵심 엔티티를 정의합니다:
  - watchlist_snapshots: 워치리스트 스냅샷
  - signal_events: 시그널 이벤트
  - orders: 주문
  - fills: 체결
  - positions: 포지션
  - daily_pnl: 일별 손익
  - risk_events: 리스크 이벤트
  - strategy_runs: 전략 실행 기록
  - api_errors: API 오류 기록
  - system_health: 시스템 상태

설계 원칙:
  - Supabase Free와 일반 PostgreSQL 모두 호환
  - UUID 기반 PK로 분산 환경 대비
  - 모든 테이블에 created_at 인덱스 (조회 패턴 최적화)
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy 선언적 베이스 클래스."""
    pass


class StrategyRun(Base):
    """
    전략 실행 기록.

    매 거래일 전략 엔진이 시작될 때 새 레코드가 생성됩니다.

    조회 패턴:
      - 날짜별 실행 기록 조회
      - 최신 실행 상태 확인
    """
    __tablename__ = "strategy_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trading_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)  # paper/live
    strategy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    config_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="STARTED"
    )  # STARTED, RUNNING, COMPLETED, HALTED, ERROR
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    total_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    orders: Mapped[list["Order"]] = relationship(back_populates="strategy_run")
    signal_events: Mapped[list["SignalEvent"]] = relationship(back_populates="strategy_run")

    __table_args__ = (
        Index("ix_strategy_runs_date", "trading_date"),
        Index("ix_strategy_runs_status", "status"),
    )


class WatchlistSnapshot(Base):
    """
    워치리스트 스냅샷.

    장 시작 전 스캐너가 선별한 후보 종목 목록을 저장합니다.

    조회 패턴:
      - 날짜별 스냅샷 조회
      - 종목코드별 이력 조회
    """
    __tablename__ = "watchlist_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trading_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    symbol_name: Mapped[str] = mapped_column(String(100), nullable=False)
    gap_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    volume_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    avg_volume_20d: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    market_cap: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sector: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tags: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    rank_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_watchlist_date", "trading_date"),
        Index("ix_watchlist_symbol", "symbol"),
    )


class SignalEvent(Base):
    """
    시그널 이벤트.

    스캐너/전략 엔진이 생성한 매매 시그널을 기록합니다.
    AI 판단 결과도 함께 저장합니다.

    조회 패턴:
      - 날짜별 시그널 조회
      - 종목별 시그널 이력
      - 시그널 유형별 조회
    """
    __tablename__ = "signal_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_runs.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    signal_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # BREAKOUT, ORB_LONG, STOP_LOSS, TAKE_PROFIT, TRAILING_STOP, TIME_EXIT
    direction: Mapped[str] = mapped_column(String(4), nullable=False)  # BUY/SELL
    price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    strength: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 4), nullable=True
    )  # 0.0 ~ 1.0
    ai_action_bias: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True
    )  # allow/watch/avoid
    ai_entry_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 4), nullable=True
    )
    ai_confidence: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 4), nullable=True
    )
    ai_risk_flags: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ai_commentary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    passed_hard_rules: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    strategy_run: Mapped["StrategyRun"] = relationship(back_populates="signal_events")

    __table_args__ = (
        Index("ix_signal_date", "created_at"),
        Index("ix_signal_symbol", "symbol"),
        Index("ix_signal_type", "signal_type"),
    )


class Order(Base):
    """
    주문 기록.

    모든 주문(paper/live)을 추적합니다.
    멱등성 키(idempotency_key)로 중복 주문을 방지합니다.

    조회 패턴:
      - 주문 상태별 조회 (미체결, 체결, 취소)
      - 종목별 주문 이력
      - 멱등성 키로 중복 검사
    """
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_runs.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # BUY/SELL
    order_type: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # MARKET/LIMIT
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )  # PENDING, SUBMITTED, PARTIAL, FILLED, CANCELLED, REJECTED, ERROR
    idempotency_key: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    broker_order_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    broker_response: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    signal_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    mode: Mapped[str] = mapped_column(String(10), nullable=False)  # paper/live
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_fill_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    filled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    strategy_run: Mapped["StrategyRun"] = relationship(back_populates="orders")
    fills: Mapped[list["Fill"]] = relationship(back_populates="order")

    __table_args__ = (
        Index("ix_orders_status", "status"),
        Index("ix_orders_symbol", "symbol"),
        Index("ix_orders_created", "created_at"),
        UniqueConstraint("idempotency_key", name="uq_orders_idempotency"),
    )


class Fill(Base):
    """
    체결 기록.

    주문의 부분/전량 체결 내역을 기록합니다.

    조회 패턴:
      - 주문별 체결 내역
      - 날짜별 체결 기록
    """
    __tablename__ = "fills"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    commission: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    tax: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    broker_fill_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    filled_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    order: Mapped["Order"] = relationship(back_populates="fills")

    __table_args__ = (
        Index("ix_fills_order", "order_id"),
        Index("ix_fills_filled_at", "filled_at"),
    )


class Position(Base):
    """
    포지션 기록.

    현재 보유 중인 포지션과 청산된 포지션 모두를 관리합니다.
    서버 재시작 후 상태 복구에 사용됩니다.

    조회 패턴:
      - 활성 포지션 조회 (is_open=True)
      - 종목별 포지션 이력
      - 날짜별 포지션 현황
    """
    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    symbol_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    side: Mapped[str] = mapped_column(String(4), nullable=False, default="LONG")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_entry_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    current_price: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    highest_price: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    unrealized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="POSITION_OPEN"
    )
    stop_loss_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    take_profit_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    trailing_stop_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    partial_exits: Mapped[int] = mapped_column(Integer, default=0)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    entry_signal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    strategy_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_runs.id"), nullable=True
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_positions_open", "is_open"),
        Index("ix_positions_symbol", "symbol"),
        Index("ix_positions_opened", "opened_at"),
    )


class DailyPnL(Base):
    """
    일별 손익 기록.

    매 거래일 종료 후 합산된 일별 손익을 저장합니다.

    조회 패턴:
      - 날짜 범위별 손익 조회
      - 누적 손익 계산
    """
    __tablename__ = "daily_pnl"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trading_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, unique=True
    )
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    unrealized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    total_pnl: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    total_commission: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    total_tax: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    winning_trades: Mapped[int] = mapped_column(Integer, default=0)
    losing_trades: Mapped[int] = mapped_column(Integer, default=0)
    max_drawdown_pct: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(8, 4), nullable=True
    )
    starting_capital: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    ending_capital: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_daily_pnl_date", "trading_date"),
    )


class RiskEvent(Base):
    """
    리스크 이벤트 기록.

    안전 레일이 발동되거나 리스크 관련 이벤트가 발생할 때 기록합니다.

    조회 패턴:
      - 이벤트 유형별 조회
      - 날짜별 리스크 이벤트
      - 종목별 리스크 이력
    """
    __tablename__ = "risk_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # DAILY_LOSS_LIMIT, PER_SYMBOL_LOSS, VI_BLOCK, EMERGENCY_STOP, API_HALT, ...
    severity: Mapped[str] = mapped_column(
        String(10), nullable=False, default="WARNING"
    )  # INFO, WARNING, CRITICAL
    symbol: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    action_taken: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # BLOCK_ENTRY, FORCE_EXIT, HALT_SYSTEM, LOG_ONLY
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_risk_events_type", "event_type"),
        Index("ix_risk_events_created", "created_at"),
        Index("ix_risk_events_severity", "severity"),
    )


class ApiError(Base):
    """
    API 오류 기록.

    KIS Open API 호출 중 발생한 오류를 기록합니다.
    누적 오류가 임계값 초과 시 HALTED 전환에 사용됩니다.

    조회 패턴:
      - 최근 N분간 오류 카운트 (HALTED 판단용)
      - 오류 유형별 집계
    """
    __tablename__ = "api_errors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_body: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_api_errors_created", "created_at"),
        Index("ix_api_errors_endpoint", "endpoint"),
    )


class SystemHealth(Base):
    """
    시스템 상태 기록.

    시스템의 현재 상태를 주기적으로 저장합니다.
    서버 재시작 후 상태 복구에 사용됩니다.

    조회 패턴:
      - 최신 상태 조회
      - 상태 변경 이력
    """
    __tablename__ = "system_health"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    system_state: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # IDLE, SCANNING, RUNNING, HALTED, ERROR
    trading_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    emergency_stop: Mapped[bool] = mapped_column(Boolean, default=False)
    api_health: Mapped[str] = mapped_column(
        String(20), nullable=False, default="HEALTHY"
    )  # HEALTHY, DEGRADED, UNHEALTHY
    db_health: Mapped[str] = mapped_column(
        String(20), nullable=False, default="HEALTHY"
    )
    ws_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    active_positions_count: Mapped[int] = mapped_column(Integer, default=0)
    pending_orders_count: Mapped[int] = mapped_column(Integer, default=0)
    daily_pnl: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    daily_trades: Mapped[int] = mapped_column(Integer, default=0)
    uptime_seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_heartbeat: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_system_health_created", "created_at"),
    )
