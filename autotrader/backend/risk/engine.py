# -*- coding: utf-8 -*-
"""
리스크 엔진 모듈.

주문 실행 전 모든 하드 룰을 검증합니다.
AI가 allow를 줘도 이 하드 룰을 모두 통과해야만 주문이 가능합니다.
AI는 이 규칙을 우회하거나 해제할 수 없습니다.

14개 주문 전 하드 룰:
  1. live_trading == true
  2. confirm_live_orders == true
  3. emergency_stop == false
  4. api_health == healthy
  5. system_state != HALTED
  6. daily_loss_limit_not_hit == true
  7. per_symbol_loss_limit_not_hit == true
  8. max_positions_not_exceeded == true
  9. symbol_reentry_limit_not_hit == true
  10. reentry_cooldown_passed == true
  11. vi_block == false
  12. market_close_cutoff == false
  13. duplicate_order_check_passed == true
  14. unfilled_order_exposure_ok == true
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from backend.config.settings import Settings, TradingMode, get_settings
from backend.config.strategy_config import (
    AggressiveProfileConfig,
    MARKET_HOURS,
    SAFETY_RAILS,
)

logger = logging.getLogger(__name__)


@dataclass
class RiskCheckResult:
    """
    리스크 체크 결과.

    Attributes:
        passed: 모든 체크 통과 여부.
        violations: 위반 항목 목록.
        warnings: 경고 항목 목록.
    """
    passed: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_violation(self, rule: str, detail: str) -> None:
        """위반 사항을 추가합니다."""
        self.violations.append(f"[{rule}] {detail}")
        self.passed = False

    def add_warning(self, rule: str, detail: str) -> None:
        """경고 사항을 추가합니다."""
        self.warnings.append(f"[{rule}] {detail}")


@dataclass
class RiskContext:
    """
    리스크 체크에 필요한 컨텍스트 정보.

    주문 실행 전에 이 컨텍스트를 구성하여 RiskEngine에 전달합니다.
    """
    # 시스템 상태
    system_state: str = "IDLE"
    emergency_stop: bool = False
    api_health: str = "HEALTHY"

    # 포지션/주문 현황
    current_position_count: int = 0
    daily_entry_count: int = 0
    daily_realized_pnl: Decimal = Decimal("0")
    starting_capital: Decimal = Decimal("10000000")  # 1천만원 기본

    # 종목별 정보
    symbol: str = ""
    symbol_entry_count_today: int = 0
    symbol_realized_pnl: Decimal = Decimal("0")
    last_exit_time: Optional[datetime] = None
    has_pending_order_for_symbol: bool = False

    # VI 정보
    vi_triggered: bool = False
    vi_triggered_time: Optional[datetime] = None

    # 시간 정보
    current_time: Optional[datetime] = None

    # 미체결 정보
    unfilled_order_count: int = 0
    max_unfilled_orders: int = 3


class RiskEngine:
    """
    리스크 관리 엔진.

    주문 실행 전 14개 하드 룰을 모두 검증합니다.
    하나라도 위반되면 주문을 차단합니다.
    AI는 이 엔진의 규칙을 우회할 수 없습니다.

    Example:
        >>> engine = RiskEngine(settings, config)
        >>> result = engine.check_entry_allowed(context)
        >>> if result.passed:
        ...     # 주문 실행
        ... else:
        ...     logger.warning("주문 차단", violations=result.violations)
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        strategy_config: Optional[AggressiveProfileConfig] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._config = strategy_config or AggressiveProfileConfig()
        self._vi_blocks: dict[str, datetime] = {}  # symbol -> vi 발동 시각
        self._reentry_timestamps: dict[str, datetime] = {}  # symbol -> 최근 청산 시각

    def check_entry_allowed(self, ctx: RiskContext) -> RiskCheckResult:
        """
        진입(매수) 주문 전 모든 하드 룰을 검증합니다.

        Args:
            ctx: 리스크 컨텍스트.

        Returns:
            RiskCheckResult: 검증 결과.
        """
        result = RiskCheckResult(passed=True)
        now = ctx.current_time or datetime.now()

        # 1. live_trading 체크 (live 모드일 때만)
        if self._settings.is_live and not self._settings.live_trading:
            result.add_violation(
                "LIVE_TRADING",
                "실전 모드이지만 live_trading=false입니다",
            )

        # 2. confirm_live_orders 체크 (live 모드일 때만)
        if self._settings.is_live and not self._settings.confirm_live_orders:
            result.add_violation(
                "CONFIRM_LIVE_ORDERS",
                "실전 모드이지만 confirm_live_orders=false입니다",
            )

        # 3. emergency_stop 체크
        if ctx.emergency_stop:
            result.add_violation(
                "EMERGENCY_STOP",
                "긴급 정지가 활성화되어 있습니다",
            )

        # 4. api_health 체크
        if ctx.api_health != "HEALTHY":
            result.add_violation(
                "API_HEALTH",
                f"API 상태가 비정상입니다: {ctx.api_health}",
            )

        # 5. system_state 체크
        if ctx.system_state == "HALTED":
            result.add_violation(
                "SYSTEM_HALTED",
                "시스템이 HALTED 상태입니다",
            )

        # 6. 일일 손실 한도 체크
        if ctx.starting_capital > 0:
            daily_loss_pct = (
                float(ctx.daily_realized_pnl) / float(ctx.starting_capital)
            ) * 100
            if daily_loss_pct <= -self._settings.daily_loss_limit_pct:
                result.add_violation(
                    "DAILY_LOSS_LIMIT",
                    f"일일 손실 한도 도달: {daily_loss_pct:.2f}% "
                    f"(한도: -{self._settings.daily_loss_limit_pct}%)",
                )

        # 7. 종목당 손실 한도 체크
        if ctx.starting_capital > 0 and ctx.symbol:
            symbol_loss_pct = (
                float(ctx.symbol_realized_pnl) / float(ctx.starting_capital)
            ) * 100
            if symbol_loss_pct <= -self._settings.per_symbol_loss_limit_pct:
                result.add_violation(
                    "PER_SYMBOL_LOSS_LIMIT",
                    f"종목 [{ctx.symbol}] 손실 한도 도달: {symbol_loss_pct:.2f}%",
                )

        # 8. 최대 동시 보유 종목 수 체크
        if ctx.current_position_count >= self._config.max_positions:
            result.add_violation(
                "MAX_POSITIONS",
                f"최대 보유 종목 수 도달: {ctx.current_position_count}/{self._config.max_positions}",
            )

        # 9. 종목당 재진입 횟수 체크
        if ctx.symbol_entry_count_today >= self._config.per_symbol_max_entries:
            result.add_violation(
                "SYMBOL_REENTRY_LIMIT",
                f"종목 [{ctx.symbol}] 재진입 한도: "
                f"{ctx.symbol_entry_count_today}/{self._config.per_symbol_max_entries}",
            )

        # 10. 재진입 쿨다운 체크
        if ctx.last_exit_time:
            cooldown_end = ctx.last_exit_time + timedelta(
                seconds=self._config.reentry_cooldown_seconds
            )
            if now < cooldown_end:
                remaining = (cooldown_end - now).total_seconds()
                result.add_violation(
                    "REENTRY_COOLDOWN",
                    f"재진입 쿨다운 중 (잔여: {remaining:.0f}초)",
                )

        # 11. VI 차단 체크
        if ctx.vi_triggered and ctx.vi_triggered_time:
            vi_end = ctx.vi_triggered_time + timedelta(
                seconds=SAFETY_RAILS.VI_BLOCK_DURATION_SECONDS
            )
            if now < vi_end:
                result.add_violation(
                    "VI_BLOCK",
                    f"VI 발동 후 차단 중 (종목: {ctx.symbol})",
                )

        # 12. 장 마감 차단 체크
        current_time_str = now.strftime("%H:%M")
        if current_time_str >= self._config.entry_hard_cutoff:
            result.add_violation(
                "MARKET_CLOSE_CUTOFF",
                f"신규 진입 마감 시간 초과: {current_time_str} >= {self._config.entry_hard_cutoff}",
            )
        elif current_time_str >= "15:20":
            result.add_violation(
                "CLOSING_AUCTION",
                "종가 단일가 구간 신규 진입 금지",
            )

        # 진입 시간 전 체크
        if current_time_str < self._config.entry_start_time:
            result.add_violation(
                "ENTRY_TOO_EARLY",
                f"진입 시작 시간 전: {current_time_str} < {self._config.entry_start_time}",
            )

        # 13. 중복 주문 체크
        if ctx.has_pending_order_for_symbol:
            result.add_violation(
                "DUPLICATE_ORDER",
                f"종목 [{ctx.symbol}]에 대해 이미 미체결 주문이 존재합니다",
            )

        # 14. 미체결 주문 노출 체크
        if ctx.unfilled_order_count >= ctx.max_unfilled_orders:
            result.add_violation(
                "UNFILLED_EXPOSURE",
                f"미체결 주문이 너무 많습니다: {ctx.unfilled_order_count}/{ctx.max_unfilled_orders}",
            )

        # ---- 추가 경고 (차단은 아님) ----
        # 일일 최대 진입 횟수 경고
        if ctx.daily_entry_count >= self._config.max_daily_entries:
            result.add_violation(
                "MAX_DAILY_ENTRIES",
                f"일일 최대 진입 횟수 도달: {ctx.daily_entry_count}/{self._config.max_daily_entries}",
            )

        # 주요 마감 이후 진입 제한
        if (
            current_time_str >= self._config.entry_primary_cutoff
            and current_time_str < self._config.entry_hard_cutoff
        ):
            post_cutoff_entries = ctx.daily_entry_count  # 간단화
            if post_cutoff_entries >= self._config.post_cutoff_max_entries:
                result.add_warning(
                    "POST_CUTOFF",
                    f"주요 마감({self._config.entry_primary_cutoff}) 이후 진입 제한 중",
                )

        # 결과 로그
        if not result.passed:
            logger.warning(
                "진입 차단",
                extra={
                    "event": "entry_blocked",
                    "symbol": ctx.symbol,
                    "violations": result.violations,
                    "warnings": result.warnings,
                },
            )
        else:
            logger.info(
                "진입 허용",
                extra={
                    "event": "entry_allowed",
                    "symbol": ctx.symbol,
                    "warnings": result.warnings,
                },
            )

        return result

    def check_exit_allowed(self, ctx: RiskContext) -> RiskCheckResult:
        """
        청산(매도) 주문 전 필수 체크를 수행합니다.

        청산은 진입보다 제한이 적습니다 (포지션 보호 우선).
        API 상태가 비정상이어도 손절 주문은 시도합니다.

        Args:
            ctx: 리스크 컨텍스트.

        Returns:
            RiskCheckResult: 검증 결과.
        """
        result = RiskCheckResult(passed=True)

        # 청산은 emergency_stop 중에도 허용 (기존 포지션 정리)
        # 단, HALTED 상태에서도 청산은 허용

        # 중복 매도 주문 체크
        if ctx.has_pending_order_for_symbol:
            result.add_violation(
                "DUPLICATE_SELL_ORDER",
                f"종목 [{ctx.symbol}]에 대해 이미 매도 주문이 존재합니다",
            )

        return result

    def register_vi_event(self, symbol: str) -> None:
        """VI 발동을 등록합니다."""
        self._vi_blocks[symbol] = datetime.now()
        logger.warning(
            "VI 발동 등록",
            extra={"event": "vi_registered", "symbol": symbol},
        )

    def register_exit(self, symbol: str) -> None:
        """종목 청산을 등록합니다 (쿨다운 추적용)."""
        self._reentry_timestamps[symbol] = datetime.now()

    def is_vi_blocked(self, symbol: str) -> bool:
        """종목이 VI 차단 중인지 확인합니다."""
        if symbol not in self._vi_blocks:
            return False
        vi_time = self._vi_blocks[symbol]
        return (datetime.now() - vi_time).total_seconds() < SAFETY_RAILS.VI_BLOCK_DURATION_SECONDS

    def get_risk_summary(self) -> dict:
        """현재 리스크 상태 요약을 반환합니다."""
        return {
            "vi_blocks": {
                sym: dt.isoformat() for sym, dt in self._vi_blocks.items()
                if self.is_vi_blocked(sym)
            },
            "reentry_cooldowns": {
                sym: dt.isoformat() for sym, dt in self._reentry_timestamps.items()
            },
            "daily_loss_limit_pct": self._settings.daily_loss_limit_pct,
            "per_symbol_loss_limit_pct": self._settings.per_symbol_loss_limit_pct,
            "max_positions": self._config.max_positions,
        }
