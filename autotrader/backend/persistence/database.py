# -*- coding: utf-8 -*-
"""
데이터베이스 연결 관리 모듈.

PostgreSQL(asyncpg) 기반 비동기 DB 연결을 관리합니다.
Supabase Free를 초기 개발에 사용할 수 있으며,
실전 전환 시 일반 PostgreSQL로 교체 가능하도록 추상화합니다.

DB 연결 실패 시 거래를 허용하지 않고 HALTED 상태로 전환합니다.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config.settings import get_settings

logger = logging.getLogger(__name__)

# 전역 엔진/세션 팩토리
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


async def init_database() -> AsyncEngine:
    """
    DB 엔진을 초기화합니다.

    Supabase Free 사용 시 주의사항:
      - 무료 플랜은 connection pooling 제한이 있음 (보통 15 connections)
      - pool_size를 5 이하로 유지 권장
      - 실전 전환 시 별도 매니지드 DB로 교체 필요

    Returns:
        AsyncEngine: SQLAlchemy 비동기 엔진.

    Raises:
        ConnectionError: DB 연결 실패 시. 이 경우 시스템은 HALTED 전환 필요.
    """
    global _engine, _session_factory

    settings = get_settings()

    try:
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.log_level.value == "DEBUG",
            pool_size=5,
            max_overflow=2,
            pool_timeout=10,
            pool_recycle=300,
            pool_pre_ping=True,
        )

        _session_factory = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # 연결 테스트
        async with _engine.begin() as conn:
            await conn.execute(
                # SQLAlchemy text() import needed at runtime
                __import__("sqlalchemy").text("SELECT 1")
            )

        logger.info("DB 연결 성공", extra={"url": settings.database_url[:30] + "..."})
        return _engine

    except Exception as e:
        logger.critical(
            "DB 연결 실패 - 시스템 HALTED 전환 필요",
            extra={"error": str(e)},
        )
        raise ConnectionError(f"DB 연결 실패: {e}") from e


async def close_database() -> None:
    """DB 연결을 종료합니다."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("DB 연결 종료")


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    DB 세션을 제공하는 컨텍스트 매니저.

    세션은 자동으로 커밋/롤백됩니다.
    DB 연결 실패 시 예외를 발생시키며, 호출자가 HALTED 전환을 처리해야 합니다.

    Yields:
        AsyncSession: DB 세션.

    Raises:
        RuntimeError: DB 엔진이 초기화되지 않은 경우.
        Exception: DB 작업 중 오류 발생 시.

    Example:
        >>> async with get_session() as session:
        ...     result = await session.execute(select(Order))
    """
    if _session_factory is None:
        raise RuntimeError(
            "DB 엔진이 초기화되지 않았습니다. init_database()를 먼저 호출하세요."
        )

    session = _session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def get_engine() -> Optional[AsyncEngine]:
    """현재 DB 엔진 반환 (없으면 None)."""
    return _engine
