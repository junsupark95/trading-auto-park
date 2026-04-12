# -*- coding: utf-8 -*-
"""
AI 입출력 스키마 정의.

AI 응답은 반드시 이 스키마를 따라야 합니다.
스키마를 벗어나거나 필수 필드가 누락되면 해당 응답은 무효 처리됩니다.
AI 응답 파싱 실패 시 경고 로그만 남기고, 규칙 기반 엔진만 계속 운용합니다.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ActionBias(str, Enum):
    """AI 판단 방향."""
    ALLOW = "allow"
    WATCH = "watch"
    AVOID = "avoid"


class AIAnalysisRequest(BaseModel):
    """
    AI 분석 요청 입력.

    브로커 원시 API가 아닌 정규화된 데이터를 전달합니다.
    """
    symbol: str = Field(description="종목코드 (6자리)")
    symbol_name: str = Field(default="", description="종목명")
    current_price: float = Field(description="현재가")
    open_price: float = Field(description="시가")
    high_price: float = Field(description="고가")
    low_price: float = Field(description="저가")
    prev_close: float = Field(description="전일 종가")
    volume: int = Field(description="거래량")
    trade_amount: int = Field(description="거래대금 (원)")
    gap_pct: float = Field(description="시가 갭 상승률 (%)")
    volume_ratio: float = Field(description="20일 평균 대비 거래량 비율")
    orb_high: float = Field(default=0, description="ORB 고가")
    orb_low: float = Field(default=0, description="ORB 저가")
    spread_pct: float = Field(default=0, description="호가 스프레드 (%)")
    news_summary: str = Field(default="", description="관련 뉴스/공시 요약")
    sector: str = Field(default="", description="업종")
    market_sentiment: str = Field(
        default="neutral",
        description="시장 전반 센티먼트 (bullish/neutral/bearish)",
    )


class AIAnalysisResponse(BaseModel):
    """
    AI 분석 응답.

    이 스키마를 벗어나는 응답은 무효 처리됩니다.
    AI 장애 시에도 규칙 기반 엔진은 계속 운용됩니다.
    """
    symbol: str = Field(description="종목코드")
    action_bias: ActionBias = Field(description="판단 방향: allow/watch/avoid")
    entry_score: float = Field(
        description="진입 점수 (0.0 ~ 1.0)",
        ge=0.0,
        le=1.0,
    )
    exit_urgency: float = Field(
        default=0.0,
        description="청산 긴급도 (0.0 ~ 1.0)",
        ge=0.0,
        le=1.0,
    )
    confidence: float = Field(
        description="판단 신뢰도 (0.0 ~ 1.0)",
        ge=0.0,
        le=1.0,
    )
    risk_flags: list[str] = Field(
        default_factory=list,
        description="리스크 플래그 목록",
    )
    reason_codes: list[str] = Field(
        default_factory=list,
        description="판단 근거 코드 목록",
    )
    commentary: str = Field(
        default="",
        description="간단한 해석 (한글)",
    )

    @field_validator("risk_flags")
    @classmethod
    def validate_risk_flags(cls, v: list[str]) -> list[str]:
        """알려진 리스크 플래그만 허용."""
        known_flags = {
            "SPREAD_WIDE", "NEAR_VI", "WEAK_NEWS", "OVERHEATED",
            "LOW_VOLUME", "UPPER_LIMIT_NEAR", "MARKET_WEAK",
            "CHASE_RISK", "THEME_FADING", "HIGH_VOLATILITY",
        }
        return [f for f in v if f in known_flags]


class AIExitAdvice(BaseModel):
    """AI 청산 보조 의견. 부분 익절/잔량 유지에 대한 의견만 제공."""
    symbol: str
    hold_recommendation: str = Field(
        description="HOLD_PARTIAL / CLOSE_ALL / HOLD_ALL"
    )
    suggested_exit_ratio: float = Field(
        default=0.5,
        description="제안 청산 비율 (0.0 ~ 1.0)",
        ge=0.0,
        le=1.0,
    )
    reason: str = Field(default="", description="판단 근거")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
