# -*- coding: utf-8 -*-
"""
구조화 로깅 모듈.

structlog 기반으로 JSON 형식의 구조화 로깅을 설정합니다.
모든 거래 관련 이벤트는 구조화 필드로 기록됩니다.
"""

import logging
import sys

import structlog


def setup_logging(log_level: str = "INFO") -> None:
    """
    구조화 로깅을 설정합니다.

    개발 환경에서는 포맷된 출력, 프로덕션에서는 JSON 출력을 사용합니다.

    Args:
        log_level: 로깅 레벨 (DEBUG, INFO, WARNING, ERROR).
    """
    # 표준 라이브러리 로깅 설정
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    # structlog 설정
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),  # 개발용
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
