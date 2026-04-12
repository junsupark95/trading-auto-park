# -*- coding: utf-8 -*-
"""
전략 진입 규칙 모듈.

5분 ORB 기반 진입 조건을 정의합니다.
모든 진입은 하드 룰 통과 후에만 실행됩니다.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from backend.config.strategy_config import AggressiveProfileConfig

logger = logging.getLogger(__name__)


@dataclass
class OrbData:
    """Opening Range Breakout 데이터."""
    symbol: str
    orb_high: Decimal
    orb_low: Decimal
    orb_volume: int
    orb_start: datetime
    orb_end: datetime
    is_formed: bool = False


@dataclass
class EntrySignal:
    """진입 시그널."""
    symbol: str
    direction: str  # "BUY"
    price: Decimal
    signal_type: str  # "ORB_BREAKOUT"
    strength: float  # 0.0 ~ 1.0
    orb_data: Optional[OrbData] = None
    reasons: list[str] = None

    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []


class EntryRules:
    """
    진입 규칙 엔진.

    5분 ORB 돌파를 핵심 진입 조건으로 사용합니다.
    추가로 거래량 확인, 호가 스프레드 검증을 수행합니다.

    Example:
        >>> rules = EntryRules(config)
        >>> signal = rules.check_breakout(orb, current_price, current_volume)
    """

    def __init__(self, config: Optional[AggressiveProfileConfig] = None) -> None:
        self._config = config or AggressiveProfileConfig()

    def check_gap_filter(
        self,
        prev_close: Decimal,
        open_price: Decimal,
    ) -> tuple[bool, float]:
        """
        시가 갭 필터를 확인합니다.

        Args:
            prev_close: 전일 종가.
            open_price: 당일 시가.

        Returns:
            (통과 여부, 갭 비율 %).
        """
        if prev_close <= 0:
            return False, 0.0

        gap_pct = float((open_price - prev_close) / prev_close * 100)

        passed = (
            self._config.gap_up_min_pct <= gap_pct <= self._config.gap_up_max_pct
        )

        return passed, gap_pct

    def check_volume_filter(
        self,
        current_volume_amount: int,
        avg_volume_20d: int,
    ) -> tuple[bool, float]:
        """
        거래대금 서지 필터를 확인합니다.

        Args:
            current_volume_amount: 현재 거래대금 (원).
            avg_volume_20d: 20일 평균 거래대금.

        Returns:
            (통과 여부, 거래량 비율).
        """
        if avg_volume_20d <= 0:
            return False, 0.0

        ratio = current_volume_amount / avg_volume_20d

        # 최소 평균 거래대금 체크
        if avg_volume_20d < self._config.min_avg_volume_20d:
            return False, ratio

        # 서지 비율 체크
        passed = ratio >= self._config.volume_surge_ratio
        return passed, ratio

    def check_breakout(
        self,
        orb: OrbData,
        current_price: Decimal,
        period_volume: int,
        orb_avg_volume: int,
    ) -> Optional[EntrySignal]:
        """
        ORB 돌파를 확인합니다.

        5분 ORB 고가를 돌파하면서 거래량도 증가하면 진입 시그널을 생성합니다.

        Args:
            orb: ORB 데이터.
            current_price: 현재가.
            period_volume: 현재 기간 거래량.
            orb_avg_volume: ORB 기간 평균 거래량.

        Returns:
            EntrySignal 또는 None.
        """
        if not orb.is_formed:
            return None

        if current_price <= orb.orb_high:
            return None

        # 돌파 거래량 확인
        if orb_avg_volume > 0:
            vol_ratio = period_volume / orb_avg_volume
            if vol_ratio < self._config.breakout_volume_ratio:
                return None
        else:
            vol_ratio = 1.0

        # 시그널 강도 계산
        breakout_pct = float((current_price - orb.orb_high) / orb.orb_high * 100)
        strength = min(1.0, (breakout_pct / 2.0) * 0.5 + (vol_ratio / 5.0) * 0.5)

        reasons = [
            f"ORB 돌파: {current_price} > {orb.orb_high}",
            f"돌파 비율: {breakout_pct:.2f}%",
            f"거래량 비율: {vol_ratio:.1f}x",
        ]

        signal = EntrySignal(
            symbol=orb.symbol,
            direction="BUY",
            price=current_price,
            signal_type="ORB_BREAKOUT",
            strength=strength,
            orb_data=orb,
            reasons=reasons,
        )

        logger.info(
            "ORB 돌파 시그널 생성",
            extra={
                "event": "orb_breakout_signal",
                "symbol": orb.symbol,
                "price": str(current_price),
                "orb_high": str(orb.orb_high),
                "strength": strength,
            },
        )

        return signal

    def check_spread(
        self,
        spread_pct: float,
    ) -> bool:
        """호가 스프레드 체크."""
        return spread_pct <= self._config.max_spread_pct
