# -*- coding: utf-8 -*-
"""
전략 엔진 오케스트레이터.

모든 서브시스템을 통합하여 하나의 트레이딩 루프를 실행합니다.

루프 절차 (장중):
  1. 시간 체크 → 장 시작/마감 전이
  2. 헬스 체크 (API, WS, DB)
  3. 포지션 보유 중이면 → 청산 평가
  4. 포지션 미보유면 → 스캐닝 + ORB 감시
  5. 시그널 발생 → 리스크 체크 → 주문 실행
  6. 미체결 타임아웃 관리
  7. 메트릭 갱신
  8. 10:00 이전이면 1초 간격, 이후 2초 간격

설계 원칙:
  - 모든 예외는 로그로 남기고 루프 지속 (조용한 실패 금지, 명확한 로그)
  - API 오류 5회 누적 → HALTED
  - HALTED 후 자동 복구 없음 → 수동 해제 필요
"""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from backend.ai.advisor import AIAdvisor
from backend.brokers.base import BaseBroker
from backend.config.settings import Settings, get_settings
from backend.config.strategy_config import AggressiveProfileConfig, MARKET_HOURS
from backend.execution.fill_tracker import FillTracker
from backend.execution.order_manager import OrderManager
from backend.monitoring.health import ComponentStatus, HealthChecker
from backend.monitoring.metrics import MetricsCollector
from backend.risk.emergency import get_emergency_stop
from backend.risk.engine import RiskContext, RiskEngine
from backend.strategy.entry_rules import EntryRules, OrbData
from backend.strategy.exit_rules import ExitRules
from backend.strategy.scanner import Scanner
from backend.strategy.signal_generator import SignalGenerator
from backend.strategy.state_machine import (
    InvalidTransitionError,
    StateMachine,
    TradingEvent,
    TradingState,
)

logger = logging.getLogger(__name__)

# API 오류 누적 임계치
MAX_API_ERRORS_BEFORE_HALT = 5


class TradingEngine:
    """
    전략 엔진 오케스트레이터.

    모든 서브시스템을 통합하여 자동매매 루프를 실행합니다.

    Attributes:
        state_machine: 상태 기계.
        is_running: 실행 중 여부.

    Example:
        >>> engine = TradingEngine(broker, settings)
        >>> await engine.start()  # 장 시작 시 호출
    """

    def __init__(
        self,
        broker: BaseBroker,
        settings: Optional[Settings] = None,
        config: Optional[AggressiveProfileConfig] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._config = config or AggressiveProfileConfig()
        self._broker = broker

        # 서브시스템 초기화
        self.state_machine = StateMachine()
        self._risk_engine = RiskEngine(self._settings, self._config)
        self._order_manager = OrderManager(broker)
        self._fill_tracker = FillTracker(broker, timeout_seconds=60)
        self._scanner = Scanner(self._config)
        self._signal_gen = SignalGenerator(self._config, self._risk_engine)
        self._entry_rules = EntryRules(self._config)
        self._exit_rules = ExitRules(self._config)
        self._health = HealthChecker()
        self._metrics = MetricsCollector()
        self._emergency = get_emergency_stop()

        # AI (선택적)
        self._ai: Optional[AIAdvisor] = None
        if self._settings.ai_enabled:
            self._ai = AIAdvisor(self._settings)
            self._signal_gen = SignalGenerator(
                self._config, self._risk_engine, self._ai
            )

        # ORB 데이터
        self._orb_data: dict[str, OrbData] = {}

        # 포지션 추적 (메모리)
        self._positions: dict[str, dict] = {}  # symbol -> position info

        # 루프 제어
        self._is_running = False
        self._api_error_count = 0

    @property
    def is_running(self) -> bool:
        """엔진 실행 중 여부."""
        return self._is_running

    async def start(self) -> None:
        """
        매매 루프를 시작합니다.

        장 시작 전에 호출하면 장 시작까지 대기합니다.
        """
        self._is_running = True

        logger.info(
            "🚀 트레이딩 엔진 시작",
            extra={
                "event": "engine_start",
                "mode": self._settings.trading_mode.value,
                "live_trading": self._settings.live_trading,
            },
        )

        try:
            # 브로커 연결
            connected = await self._broker.connect()
            if connected:
                self._health.update("REST_API", ComponentStatus.HEALTHY)
            else:
                self._health.update(
                    "REST_API", ComponentStatus.UNHEALTHY, error="연결 실패"
                )

            # 장 시작 대기 → 메인 루프
            while self._is_running:
                await self._main_loop_tick()

        except Exception as e:
            logger.critical(
                f"엔진 치명적 오류: {e}",
                extra={"event": "engine_fatal_error", "error": str(e)},
            )
        finally:
            self._is_running = False
            logger.info("트레이딩 엔진 종료")

    async def stop(self) -> None:
        """매매 루프를 안전하게 중지합니다."""
        logger.info("엔진 종료 요청")
        self._is_running = False

    async def _main_loop_tick(self) -> None:
        """메인 루프 1틱."""
        now = datetime.now()
        current_time = now.strftime("%H:%M:%S")
        current_hm = now.strftime("%H:%M")

        # HALTED 상태면 대기만
        if self.state_machine.is_halted:
            await asyncio.sleep(5)
            return

        # 긴급 정지 확인
        if self._emergency.is_active:
            if not self.state_machine.is_halted:
                self.state_machine.force_halt("긴급 정지 활성화")
            await asyncio.sleep(5)
            return

        # 장 시간 체크
        if current_hm < MARKET_HOURS.market_open:
            # 장전 대기
            if self.state_machine.current_state != TradingState.IDLE:
                try:
                    self.state_machine.transition(
                        TradingEvent.MARKET_CLOSE, reason="장전"
                    )
                except InvalidTransitionError:
                    pass
            await asyncio.sleep(10)
            return

        if current_hm >= MARKET_HOURS.market_close:
            # 장 마감 후
            await self._handle_market_close()
            await asyncio.sleep(30)
            return

        # 장중: 상태에 따른 처리
        state = self.state_machine.current_state

        if state == TradingState.IDLE:
            # IDLE → SCANNING
            self.state_machine.transition(
                TradingEvent.MARKET_OPEN, reason="장중 진입"
            )

        elif state == TradingState.SCANNING:
            await self._do_scanning()

        elif state in (TradingState.WATCHING, TradingState.READY_TO_BUY):
            await self._do_watching()

        elif state == TradingState.POSITION_OPEN:
            await self._do_position_management()

        elif state in (TradingState.BUY_ORDER_SENT, TradingState.SELL_ORDER_SENT):
            await self._do_order_tracking()

        elif state == TradingState.CLOSED:
            # 청산 완료 → 다시 스캐닝
            self.state_machine.reset_to_scanning("청산 완료 후 복귀")

        elif state == TradingState.ERROR:
            # 에러 → 복구 시도 (API 상태 확인 후)
            self._api_error_count += 1
            if self._api_error_count >= MAX_API_ERRORS_BEFORE_HALT:
                self.state_machine.force_halt(
                    f"API 오류 {self._api_error_count}회 누적"
                )
                self._metrics.record_api_error()
            else:
                await asyncio.sleep(5)
                try:
                    self.state_machine.transition(
                        TradingEvent.RECONNECT_SUCCESS, reason="에러 복구 시도"
                    )
                except InvalidTransitionError:
                    pass

        # 미체결 주문 타임아웃 관리
        timed_out = await self._fill_tracker.check_timeouts()
        for order in timed_out:
            logger.warning(f"미체결 타임아웃 취소: {order.get('symbol')}")

        # 폴링 간격 결정 (장초반은 빠르게)
        if current_hm < "10:00":
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(2)

    async def _do_scanning(self) -> None:
        """스캐닝 상태: 후보 종목 탐색 (1분 간격 주기)."""
        try:
            # 현재 시간이 진입 시작 시간 전이면 스캔 대기
            now = datetime.now()
            current_hm = now.strftime("%H:%M")

            if current_hm < self._config.entry_start_time:
                await asyncio.sleep(2)
                return

            # 이미 최대 포지션이면 스캐닝 불필요
            if len(self._positions) >= self._config.max_positions:
                await asyncio.sleep(5)
                return

            # 1분 스캔 인터벌 체크 (AI 호출 무료 한도와 연동)
            import time
            if not hasattr(self, "_last_scan_time"):
                self._last_scan_time = 0.0

            if time.time() - self._last_scan_time < 60.0:
                await asyncio.sleep(1)
                return

            self._last_scan_time = time.time()

            logger.info("스캐닝 시작 (1분 주기)")
            candidates = await self._scanner.scan(self._broker.market_data)

            if candidates:
                # 가장 점수가 높은 최상위 후보 1개를 감시 상태로 전이
                best = candidates[0]
                if best.symbol not in self._orb_data:
                    self._orb_data[best.symbol] = OrbData()
                
                try:
                    self.state_machine.transition(
                        TradingEvent.BREAKOUT_DETECTED,
                        symbol=best.symbol,
                        reason=f"스캔 최상위 포착: 갭 {best.gap_pct:.1f}%"
                    )
                except InvalidTransitionError:
                    pass

        except Exception as e:
            logger.error(f"스캐닝 중 예기치 않은 오류: {e}")
            self._metrics.record_api_error()

    async def _do_watching(self) -> None:
        """감시 상태: ORB 형성 대기 및 돌파 확인."""
        # 구현: WebSocket에서 실시간 체결가 수신 시 ORB 고저 갱신
        await asyncio.sleep(1)

    async def _do_position_management(self) -> None:
        """포지션 관리: 청산 조건 평가."""
        for symbol, pos in list(self._positions.items()):
            try:
                decision = self._signal_gen.evaluate_exit(
                    symbol=symbol,
                    entry_price=Decimal(str(pos["entry_price"])),
                    highest_price=Decimal(str(pos.get("highest_price", pos["entry_price"]))),
                    current_price=Decimal(str(pos.get("current_price", pos["entry_price"]))),
                    entry_time=pos["entry_time"],
                    partial_exits_done=pos.get("partial_exits", 0),
                )

                if decision.action == "EXIT" and decision.signal:
                    quantity = int(
                        pos["quantity"] * decision.signal.quantity_ratio
                    )
                    if quantity > 0:
                        await self._order_manager.submit_sell(
                            symbol=symbol,
                            quantity=quantity,
                            reason=decision.signal.exit_type,
                        )
                        self.state_machine.transition(
                            TradingEvent.SELL_ORDER_SENT,
                            reason=decision.signal.exit_type,
                            symbol=symbol,
                        )
                        self._metrics.record_exit()

            except Exception as e:
                logger.error(f"포지션 관리 오류 ({symbol}): {e}")

    async def _do_order_tracking(self) -> None:
        """주문 추적: 체결 대기."""
        newly_filled = await self._fill_tracker.poll_order_status()
        for filled in newly_filled:
            side = filled.get("side", "")
            symbol = filled.get("symbol", "")
            if side == "BUY":
                self.state_machine.transition(
                    TradingEvent.BUY_ORDER_FILLED  , symbol=symbol
                )
                self._metrics.record_entry()
            elif side == "SELL":
                self.state_machine.transition(
                    TradingEvent.SELL_ORDER_FILLED, symbol=symbol
                )

        await asyncio.sleep(1)

    async def _handle_market_close(self) -> None:
        """장 마감 처리: 보유 포지션 강제 청산."""
        if self._positions:
            logger.warning(
                "장 마감 - 보유 포지션 강제 청산",
                extra={
                    "event": "market_close_force_sell",
                    "positions": list(self._positions.keys()),
                },
            )

            for symbol, pos in list(self._positions.items()):
                try:
                    await self._order_manager.submit_sell(
                        symbol=symbol,
                        quantity=pos["quantity"],
                        reason="FORCE_CLOSE_MARKET_END",
                    )
                except Exception as e:
                    logger.critical(f"장마감 강제 청산 실패: {symbol} - {e}")

        # AI 일일 카운터 리셋
        if self._ai:
            self._ai.reset_daily_counter()

        # IDLE 전이
        try:
            self.state_machine.transition(
                TradingEvent.MARKET_CLOSE, reason="장 마감"
            )
        except InvalidTransitionError:
            pass

    def build_risk_context(
        self,
        symbol: str,
    ) -> RiskContext:
        """현재 상태로 리스크 컨텍스트를 구성합니다."""
        return RiskContext(
            system_state=self.state_machine.current_state.value,
            emergency_stop=self._emergency.is_active,
            api_health=self._health.api_health_string,
            current_position_count=len(self._positions),
            daily_entry_count=self._metrics.today.entry_count,
            daily_realized_pnl=self._metrics.today.realized_pnl,
            starting_capital=Decimal(str(self._settings.starting_capital)),
            symbol=symbol,
            symbol_entry_count_today=0,  # TODO: DB에서 조회
            current_time=datetime.now(),
            unfilled_order_count=self._fill_tracker.pending_count,
            has_pending_order_for_symbol=symbol in self._fill_tracker.pending_symbols,
        )

    def get_status(self) -> dict:
        """엔진 전체 상태."""
        return {
            "running": self._is_running,
            "state": self.state_machine.get_state_summary(),
            "positions": len(self._positions),
            "metrics": self._metrics.get_summary(),
            "health": self._health.get_full_report(),
            "risk": self._risk_engine.get_risk_summary(),
            "fill_tracker": self._fill_tracker.get_summary(),
            "emergency": self._emergency.get_status(),
            "ai": self._ai.get_status() if self._ai else {"enabled": False},
        }
