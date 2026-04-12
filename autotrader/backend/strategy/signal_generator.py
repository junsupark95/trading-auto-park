# -*- coding: utf-8 -*-
"""
시그널 통합 모듈.

스캐너, 진입 규칙, AI 분석, 리스크 체크를 통합하여
최종 진입/청산 결정을 내립니다.

의사결정 흐름:
  1. 스캐너 → 후보 종목 선별
  2. ORB 진입 규칙 → 시그널 생성
  3. AI 보조 분석 → 의견 수집 (있으면)
  4. 리스크 엔진 → 14개 하드 룰 체크
  5. 최종 결정: 하드 룰 모두 통과 → 주문 실행

AI는 하드 룰을 우회할 수 없습니다.
AI가 'allow'로 줘도 하드 룰 위반이면 차단.
AI가 'avoid'로 줘도 하드 룰 통과 + 규칙 시그널이면 진입 가능
(단, AI avoid는 경고 로그 남김).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from backend.ai.advisor import AIAdvisor
from backend.ai.schemas import AIAnalysisRequest, AIAnalysisResponse, ActionBias
from backend.config.strategy_config import AggressiveProfileConfig
from backend.risk.engine import RiskContext, RiskEngine
from backend.strategy.entry_rules import EntryRules, EntrySignal, OrbData
from backend.strategy.exit_rules import ExitRules, ExitSignal

logger = logging.getLogger(__name__)


@dataclass
class TradeDecision:
    """최종 매매 결정."""
    action: str  # "ENTER", "EXIT", "HOLD", "BLOCKED"
    symbol: str = ""
    direction: str = ""  # "BUY", "SELL"
    quantity: int = 0
    price: Optional[Decimal] = None
    signal: Optional[EntrySignal | ExitSignal] = None
    ai_analysis: Optional[AIAnalysisResponse] = None
    risk_result: Optional[object] = None
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)


class SignalGenerator:
    """
    시그널 통합 생성기.

    스캐너 → 규칙 → AI → 리스크를 순차적으로 평가하여
    최종 매매 결정을 생성합니다.

    Example:
        >>> gen = SignalGenerator(config, risk_engine, ai_advisor)
        >>> decision = await gen.evaluate_entry(symbol, orb, price, ctx)
        >>> if decision.action == "ENTER":
        ...     await order_manager.submit_buy(...)
    """

    def __init__(
        self,
        config: Optional[AggressiveProfileConfig] = None,
        risk_engine: Optional[RiskEngine] = None,
        ai_advisor: Optional[AIAdvisor] = None,
    ) -> None:
        self._config = config or AggressiveProfileConfig()
        self._entry_rules = EntryRules(self._config)
        self._exit_rules = ExitRules(self._config)
        self._risk_engine = risk_engine or RiskEngine()
        self._ai_advisor = ai_advisor

    async def evaluate_entry(
        self,
        symbol: str,
        orb: OrbData,
        current_price: Decimal,
        period_volume: int,
        orb_avg_volume: int,
        risk_ctx: RiskContext,
        ai_request: Optional[AIAnalysisRequest] = None,
    ) -> TradeDecision:
        """
        진입 가능성을 평가합니다.

        Args:
            symbol: 종목코드.
            orb: ORB 데이터.
            current_price: 현재가.
            period_volume: 현재 기간 거래량.
            orb_avg_volume: ORB 평균 거래량.
            risk_ctx: 리스크 컨텍스트.
            ai_request: AI 분석 요청 (선택적).

        Returns:
            TradeDecision: 최종 매매 결정.
        """
        decision = TradeDecision(action="HOLD", symbol=symbol)

        # 1. 규칙 기반 시그널 체크
        signal = self._entry_rules.check_breakout(
            orb, current_price, period_volume, orb_avg_volume
        )

        if signal is None:
            decision.reasons.append("ORB 돌파 조건 미충족")
            return decision

        decision.signal = signal
        decision.direction = "BUY"
        decision.price = current_price

        # 2. AI 보조 분석 (있으면)
        ai_result: Optional[AIAnalysisResponse] = None
        if self._ai_advisor and ai_request:
            ai_result = await self._ai_advisor.analyze_entry(ai_request)
            decision.ai_analysis = ai_result

            if ai_result:
                if ai_result.action_bias == ActionBias.AVOID:
                    decision.warnings.append(
                        f"AI avoid 의견: {ai_result.commentary}"
                    )
                    # AI avoid는 차단이 아니라 경고
                    logger.warning(
                        "AI avoid 의견 (진입 차단 아님)",
                        extra={
                            "event": "ai_avoid_warning",
                            "symbol": symbol,
                            "commentary": ai_result.commentary,
                            "confidence": ai_result.confidence,
                        },
                    )

                if ai_result.risk_flags:
                    decision.warnings.extend(
                        [f"AI 리스크: {f}" for f in ai_result.risk_flags]
                    )

        # 3. 리스크 엔진 하드 룰 체크 (최종 관문)
        risk_result = self._risk_engine.check_entry_allowed(risk_ctx)
        decision.risk_result = risk_result

        if not risk_result.passed:
            decision.action = "BLOCKED"
            decision.blocked_by = risk_result.violations
            decision.reasons.append("리스크 하드 룰 위반")
            return decision

        # 모든 조건 통과 → 진입
        decision.action = "ENTER"
        decision.reasons.append("ORB 돌파 + 하드 룰 통과")

        logger.info(
            "진입 결정",
            extra={
                "event": "entry_decision",
                "symbol": symbol,
                "action": "ENTER",
                "signal_strength": signal.strength,
                "ai_bias": ai_result.action_bias.value if ai_result else "N/A",
                "risk_warnings": risk_result.warnings,
            },
        )

        return decision

    def evaluate_exit(
        self,
        symbol: str,
        entry_price: Decimal,
        highest_price: Decimal,
        current_price: Decimal,
        entry_time: datetime,
        partial_exits_done: int = 0,
        current_time: Optional[datetime] = None,
    ) -> TradeDecision:
        """
        청산 필요성을 평가합니다.

        Args:
            symbol: 종목코드.
            entry_price: 진입가.
            highest_price: 보유 중 최고가.
            current_price: 현재가.
            entry_time: 진입 시각.
            partial_exits_done: 부분 익절 횟수.
            current_time: 현재 시각.

        Returns:
            TradeDecision: 청산 결정 또는 HOLD.
        """
        decision = TradeDecision(action="HOLD", symbol=symbol)

        signal = self._exit_rules.evaluate_all(
            symbol=symbol,
            entry_price=entry_price,
            highest_price=highest_price,
            current_price=current_price,
            entry_time=entry_time,
            partial_exits_done=partial_exits_done,
            current_time=current_time,
        )

        if signal is None:
            return decision

        decision.action = "EXIT"
        decision.direction = "SELL"
        decision.signal = signal
        decision.price = signal.target_price or current_price
        decision.reasons.append(signal.reason)

        logger.info(
            "청산 결정",
            extra={
                "event": "exit_decision",
                "symbol": symbol,
                "exit_type": signal.exit_type,
                "quantity_ratio": signal.quantity_ratio,
                "reason": signal.reason,
            },
        )

        return decision
