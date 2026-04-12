# -*- coding: utf-8 -*-
"""
전역 설정 관리 모듈.

환경변수 기반으로 모든 설정을 관리합니다.
민감정보는 반드시 환경변수로만 주입하며, 하드코딩하지 않습니다.
Pydantic Settings를 사용하여 타입 검증과 기본값을 보장합니다.

설정 우선순위: 환경변수 > .env 파일 > 기본값

공식 문서 확인 포인트:
  - KIS Open API 도메인: https://apiportal.koreainvestment.com/
  - 실전: https://openapi.koreainvestment.com:9443
  - 모의: https://openapivts.koreainvestment.com:29443
  - WS 실전: ws://ops.koreainvestment.com:21000
  - WS 모의: ws://ops.koreainvestment.com:31000
"""

from enum import Enum
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    """운용 모드: paper(모의투자) 또는 live(실전투자)."""
    PAPER = "paper"
    LIVE = "live"


class LogLevel(str, Enum):
    """로깅 레벨."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Settings(BaseSettings):
    """
    시스템 전역 설정.

    환경변수 또는 .env 파일에서 자동으로 값을 읽습니다.
    실전에서 위험한 설정은 기본값을 안전한 값으로 지정합니다.

    Attributes:
        trading_mode: 운용 모드 (paper/live). 기본값: paper.
        live_trading: 실전 주문 활성화 여부. 기본값: False.
        confirm_live_orders: 실전 주문 이중 확인. 기본값: False.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 운용 모드 ----
    trading_mode: TradingMode = Field(
        default=TradingMode.PAPER,
        description="운용 모드: paper(모의투자) 또는 live(실전투자)",
    )
    live_trading: bool = Field(
        default=False,
        description="실전 주문 활성화. False이면 모든 주문이 차단됨",
    )
    confirm_live_orders: bool = Field(
        default=False,
        description="실전 주문 이중 확인 플래그. live_trading과 함께 True여야 실전 주문 가능",
    )

    # ---- KIS Open API (실전) ----
    kis_app_key: str = Field(default="", description="실전투자 앱키")
    kis_app_secret: str = Field(default="", description="실전투자 앱시크릿")
    kis_account_no: str = Field(default="", description="실전 계좌번호 앞 8자리")
    kis_account_prod: str = Field(default="01", description="계좌상품코드 뒤 2자리")
    kis_hts_id: str = Field(default="", description="HTS ID")

    # ---- KIS Open API (모의) ----
    kis_paper_app_key: str = Field(default="", description="모의투자 앱키")
    kis_paper_app_secret: str = Field(default="", description="모의투자 앱시크릿")
    kis_paper_account_no: str = Field(default="", description="모의 계좌번호 앞 8자리")

    # ---- KIS 도메인 (공식 문서 기준, 변경 시 공식 문서 확인 필요) ----
    kis_prod_url: str = Field(
        default="https://openapi.koreainvestment.com:9443",
        description="실전투자 REST API 도메인",
    )
    kis_paper_url: str = Field(
        default="https://openapivts.koreainvestment.com:29443",
        description="모의투자 REST API 도메인",
    )
    kis_prod_ws_url: str = Field(
        default="ws://ops.koreainvestment.com:21000",
        description="실전투자 웹소켓 도메인",
    )
    kis_paper_ws_url: str = Field(
        default="ws://ops.koreainvestment.com:31000",
        description="모의투자 웹소켓 도메인",
    )

    # ---- 데이터베이스 ----
    database_url: str = Field(
        default="postgresql+asyncpg://localhost:5432/autotrader",
        description="PostgreSQL 연결 문자열 (asyncpg)",
    )
    db_fail_halts_system: bool = Field(
        default=True,
        description="DB 연결 실패 시 시스템 HALTED 전환 여부",
    )

    # ---- AI (Gemini) ----
    gemini_api_key: str = Field(default="", description="Gemini API 키")
    gemini_model: str = Field(
        default="gemini-2.5-flash-lite",
        description="사용할 Gemini 모델명",
    )
    ai_enabled: bool = Field(default=True, description="AI 보조 분석 활성화")
    ai_daily_call_limit: int = Field(
        default=500,
        description="AI 일일 호출 상한",
        ge=1,
        le=5000,
    )
    ai_cooldown_seconds: int = Field(
        default=30,
        description="동일 종목 AI 호출 쿨다운 (초)",
        ge=5,
    )

    # ---- 리스크 한도 (시스템 불변 보호 규칙) ----
    daily_loss_limit_pct: float = Field(
        default=3.0,
        description="일일 최대 손실 한도 (%)",
        gt=0,
        le=10.0,
    )
    per_symbol_loss_limit_pct: float = Field(
        default=1.5,
        description="종목당 최대 손실 한도 (%)",
        gt=0,
        le=5.0,
    )
    max_api_error_count: int = Field(
        default=5,
        description="API 오류 누적 시 HALTED 전환 임계값",
        ge=1,
    )
    unfilled_timeout_seconds: int = Field(
        default=60,
        description="미체결 주문 타임아웃 (초)",
        ge=10,
    )
    starting_capital: int = Field(
        default=10000000,
        description="시작 자본금 (원). 일일 손실 한도 계산 기준",
        ge=1000000,
    )

    # ---- 서버 ----
    host: str = Field(default="0.0.0.0", description="서버 바인드 주소")
    port: int = Field(default=8000, description="서버 포트")
    log_level: LogLevel = Field(default=LogLevel.INFO, description="로깅 레벨")

    @property
    def is_paper(self) -> bool:
        """모의투자 모드인지 확인."""
        return self.trading_mode == TradingMode.PAPER

    @property
    def is_live(self) -> bool:
        """실전투자 모드인지 확인."""
        return self.trading_mode == TradingMode.LIVE

    @property
    def can_execute_live_orders(self) -> bool:
        """
        실전 주문 실행 가능 여부.

        live_trading과 confirm_live_orders 모두 True이고
        trading_mode가 LIVE일 때만 실전 주문 가능.
        """
        return (
            self.is_live
            and self.live_trading
            and self.confirm_live_orders
        )

    @property
    def active_app_key(self) -> str:
        """현재 모드에 맞는 앱키 반환."""
        return self.kis_paper_app_key if self.is_paper else self.kis_app_key

    @property
    def active_app_secret(self) -> str:
        """현재 모드에 맞는 앱시크릿 반환."""
        return self.kis_paper_app_secret if self.is_paper else self.kis_app_secret

    @property
    def active_account_no(self) -> str:
        """현재 모드에 맞는 계좌번호 반환."""
        return self.kis_paper_account_no if self.is_paper else self.kis_account_no

    @property
    def active_rest_url(self) -> str:
        """현재 모드에 맞는 REST API URL 반환."""
        return self.kis_paper_url if self.is_paper else self.kis_prod_url

    @property
    def active_ws_url(self) -> str:
        """현재 모드에 맞는 WebSocket URL 반환."""
        return self.kis_paper_ws_url if self.is_paper else self.kis_prod_ws_url

    @field_validator("daily_loss_limit_pct")
    @classmethod
    def validate_daily_loss_limit(cls, v: float) -> float:
        """일일 손실 한도가 과도하게 크지 않도록 검증."""
        if v > 10.0:
            raise ValueError("일일 손실 한도는 10%를 초과할 수 없습니다 (안전 레일)")
        return v

    @field_validator("per_symbol_loss_limit_pct")
    @classmethod
    def validate_per_symbol_loss_limit(cls, v: float) -> float:
        """종목당 손실 한도 검증."""
        if v > 5.0:
            raise ValueError("종목당 손실 한도는 5%를 초과할 수 없습니다 (안전 레일)")
        return v


# 싱글톤 설정 인스턴스
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    전역 설정 인스턴스를 반환합니다.

    Returns:
        Settings: 전역 설정 객체.

    Example:
        >>> settings = get_settings()
        >>> print(settings.trading_mode)
        TradingMode.PAPER
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """설정을 재로드합니다 (테스트용)."""
    global _settings
    _settings = None
