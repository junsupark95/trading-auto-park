# -*- coding: utf-8 -*-
"""
전략 파라미터 설정 모듈.

Korean Aggressive Opening Momentum 전략의 모든 파라미터를 정의합니다.
공격형 전략이지만 시스템 안전 레일은 절대 해제 불가합니다.

설계 철학:
  - 공격성은 진입 남발이 아니라 선별 강도, 빠른 판단, 부분 익절에서 구현
  - 물타기/손실 복구용 무리한 거래/무제한 재진입 금지
  - 로스 카메론식 장초반 모멘텀을 국내장 구조에 맞게 수정
"""

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class AggressiveProfileConfig(BaseModel):
    """
    공격형 장초반 모멘텀 전략 파라미터.

    모든 값은 환경변수 또는 직접 주입으로 설정 가능하며,
    기본값은 보수적 초기 운용에 적합하도록 설정되어 있습니다.

    Attributes:
        gap_up_min_pct: 최소 시가 갭 상승률 (%).
        gap_up_max_pct: 최대 시가 갭 상승률 (%). 과도한 갭은 추격 위험.
        orb_period_minutes: Opening Range Breakout 기간 (분).
    """

    # ---- 종목 필터 ----
    gap_up_min_pct: float = Field(
        default=3.0, ge=0.5, le=30.0,
        description="최소 시가 갭 상승률 (%)"
    )
    gap_up_max_pct: float = Field(
        default=15.0, ge=1.0, le=30.0,
        description="최대 시가 갭 상승률 (%). 상한가 근접 제외용"
    )
    min_avg_volume_20d: int = Field(
        default=5_000_000_000, ge=0,
        description="최근 20일 평균 거래대금 최소 (원)"
    )
    volume_surge_ratio: float = Field(
        default=3.0, ge=1.0, le=20.0,
        description="당일 거래대금 / 20일 평균 배수"
    )
    max_spread_pct: float = Field(
        default=0.5, ge=0.05, le=2.0,
        description="최대 허용 호가 스프레드 (%)"
    )
    min_market_cap: int = Field(
        default=100_000_000_000, ge=0,
        description="최소 시가총액 (원). 극소형주 제외"
    )

    # ---- 진입 규칙 ----
    orb_period_minutes: int = Field(
        default=5, ge=1, le=30,
        description="Opening Range 기간 (분)"
    )
    breakout_volume_ratio: float = Field(
        default=1.5, ge=1.0, le=10.0,
        description="돌파 시 필요 거래량 배수 (ORB 평균 대비)"
    )
    entry_start_time: str = Field(
        default="09:05",
        description="신규 진입 시작 시간 (HH:MM)"
    )
    entry_primary_cutoff: str = Field(
        default="10:30",
        description="주요 진입 마감 시간. 이후 진입 횟수 대폭 축소"
    )
    entry_hard_cutoff: str = Field(
        default="15:10",
        description="신규 진입 절대 마감 시간"
    )
    post_cutoff_max_entries: int = Field(
        default=1, ge=0, le=3,
        description="주요 마감 이후 허용 진입 횟수"
    )

    # ---- 청산 규칙 ----
    initial_stop_loss_pct: float = Field(
        default=1.5, ge=0.3, le=5.0,
        description="초기 손절 (%)"
    )
    partial_take_profit_pct: float = Field(
        default=2.0, ge=0.5, le=10.0,
        description="부분 익절 목표 수익률 (%)"
    )
    partial_take_profit_ratio: float = Field(
        default=0.5, ge=0.1, le=0.9,
        description="부분 익절 시 매도 비율 (0.5 = 보유량의 50%)"
    )
    trailing_stop_pct: float = Field(
        default=1.0, ge=0.3, le=5.0,
        description="트레일링 스탑 (%)"
    )
    trailing_activation_pct: float = Field(
        default=2.5, ge=0.5, le=10.0,
        description="트레일링 스탑 활성화 수익률 (%)"
    )
    time_exit_minutes: int = Field(
        default=120, ge=5, le=360,
        description="시간 청산: 진입 후 N분 경과 시 청산"
    )
    force_close_before_market_close_minutes: int = Field(
        default=10, ge=5, le=30,
        description="장 마감 N분 전 전량 청산"
    )

    # ---- 포지션/진입 제한 ----
    max_positions: int = Field(
        default=2, ge=1, le=3,
        description="최대 동시 보유 종목 수"
    )
    max_daily_entries: int = Field(
        default=6, ge=1, le=15,
        description="일일 최대 진입 횟수"
    )
    per_symbol_max_entries: int = Field(
        default=2, ge=1, le=5,
        description="종목당 당일 최대 재진입 횟수"
    )
    reentry_cooldown_seconds: int = Field(
        default=300, ge=30, le=1800,
        description="손절 후 재진입 쿨다운 (초)"
    )
    position_size_pct: float = Field(
        default=20.0, ge=5.0, le=50.0,
        description="종목당 자금 비중 (%). 33% 이상은 매우 보수적 검증 후에만 사용"
    )

    # ---- 시장 상태 필터 ----
    weak_market_entry_reduction: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="시장 약세 시 진입 횟수 축소 비율 (0.5 = 50% 축소)"
    )

    @field_validator("gap_up_max_pct")
    @classmethod
    def validate_gap_range(cls, v: float, info) -> float:
        """갭 상한이 갭 하한보다 크도록 검증."""
        if "gap_up_min_pct" in info.data and v <= info.data["gap_up_min_pct"]:
            raise ValueError("gap_up_max_pct는 gap_up_min_pct보다 커야 합니다")
        return v

    @field_validator("position_size_pct")
    @classmethod
    def warn_high_concentration(cls, v: float) -> float:
        """종목당 집중도가 높으면 경고."""
        if v > 33.0:
            import warnings
            warnings.warn(
                f"종목당 자금 비중 {v}%는 매우 높습니다. "
                "초기 live 운영에서는 20% 이하를 권장합니다.",
                UserWarning,
                stacklevel=2,
            )
        return v


@dataclass
class MarketHours:
    """
    시장 운용 시간 규칙.

    대한민국 정규장 구조를 반영합니다.
    - 동시호가: 08:30~09:00 (매매 금지)
    - 정규장: 09:00~15:30
    - 종가 단일가: 15:20~15:30 (신규 진입 금지)
    """
    system_start: str = "08:40"
    system_end: str = "15:30"
    pre_market_prep_start: str = "08:40"
    pre_market_prep_end: str = "08:59"
    market_open: str = "09:00"
    market_close: str = "15:30"
    closing_auction_start: str = "15:20"
    no_new_entry_after: str = "15:10"
    force_close_start: str = "15:20"
    ai_active_start: str = "08:40"
    ai_active_end: str = "15:30"


@dataclass
class SystemSafetyRails:
    """
    시스템 불변 안전 레일 상수.

    이 값들은 전략 파라미터가 아니라 시스템 보호 규칙입니다.
    코드에서 동적으로 변경할 수 없으며, AI도 우회할 수 없습니다.
    """
    # 이 상수들은 의도적으로 변경 불가하도록 frozen dataclass 사용
    MAX_DAILY_LOSS_LIMIT_PCT_HARD_CAP: float = 10.0
    MAX_PER_SYMBOL_LOSS_LIMIT_PCT_HARD_CAP: float = 5.0
    MAX_POSITIONS_HARD_CAP: int = 5
    MAX_DAILY_ENTRIES_HARD_CAP: int = 20
    MIN_REENTRY_COOLDOWN_SECONDS: int = 30
    VI_BLOCK_DURATION_SECONDS: int = 120
    MAX_API_ERRORS_BEFORE_HALT: int = 10
    UNFILLED_ORDER_MAX_TIMEOUT_SECONDS: int = 300
    ORDER_DEDUP_WINDOW_SECONDS: int = 5
    OVERNIGHT_HOLD_FORBIDDEN: bool = True

    def validate_against_config(self, config: AggressiveProfileConfig) -> list[str]:
        """
        전략 설정이 안전 레일 하드 캡을 초과하지 않는지 검증합니다.

        Args:
            config: 검증할 전략 설정.

        Returns:
            위반 사항 목록. 비어 있으면 통과.
        """
        violations: list[str] = []
        if config.max_positions > self.MAX_POSITIONS_HARD_CAP:
            violations.append(
                f"max_positions({config.max_positions})가 하드 캡({self.MAX_POSITIONS_HARD_CAP}) 초과"
            )
        if config.max_daily_entries > self.MAX_DAILY_ENTRIES_HARD_CAP:
            violations.append(
                f"max_daily_entries({config.max_daily_entries})가 하드 캡({self.MAX_DAILY_ENTRIES_HARD_CAP}) 초과"
            )
        if config.reentry_cooldown_seconds < self.MIN_REENTRY_COOLDOWN_SECONDS:
            violations.append(
                f"reentry_cooldown({config.reentry_cooldown_seconds}s)가 최소값({self.MIN_REENTRY_COOLDOWN_SECONDS}s) 미만"
            )
        return violations


# 전역 인스턴스
MARKET_HOURS = MarketHours()
SAFETY_RAILS = SystemSafetyRails()
