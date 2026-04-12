# -*- coding: utf-8 -*-
"""
AI 보조 분석 어드바이저 모듈.

Gemini 2.5 Flash Lite를 사용하여 장중 이벤트 기반으로 호출합니다.
AI는 보조 분석기이지 최종 매매 결정권자가 아닙니다.

AI 호출 원칙:
  - 틱마다 호출 금지 → 이벤트 기반만 허용
  - 동일 종목 반복 호출 쿨다운
  - 하루 500회 상한
  - 규칙 기반 스캐너 상위 후보군에만 호출
  - JSON 스키마 필수, 파싱 실패 시 무효 처리
  - AI 장애 시 규칙 기반 엔진 단독 운용 지속
"""

import json
import logging
import time
from datetime import datetime
from typing import Optional

from backend.ai.schemas import AIAnalysisRequest, AIAnalysisResponse, ActionBias
from backend.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# AI 프롬프트 시스템 메시지
SYSTEM_PROMPT = """당신은 한국 주식시장(코스피/코스닥) 장초반 모멘텀 데이트레이딩 보조 분석기입니다.

역할:
- 스캔된 후보 종목의 진입 적합성 분석
- 뉴스/공시/재료 해석
- 테마 지속성 평가
- 과열/추격 위험 평가
- 진입 보류/허용 의견 제공

절대 금지 사항:
- 최종 주문 실행 결정을 내리지 마세요
- 손절을 하지 말라고 조언하지 마세요
- 리스크 차단을 무시하라고 하지 마세요
- 물타기를 권유하지 마세요

반드시 아래 JSON 스키마로만 응답하세요. 다른 형식은 무효 처리됩니다."""

ANALYSIS_PROMPT_TEMPLATE = """종목 분석 요청:

종목코드: {symbol} ({symbol_name})
현재가: {current_price:,}원 (전일대비 {gap_pct:+.1f}%)
시가: {open_price:,}원 / 고가: {high_price:,}원 / 저가: {low_price:,}원
거래량 비율: {volume_ratio:.1f}x (20일 평균 대비)
거래대금: {trade_amount:,}원
ORB 고가: {orb_high:,}원 / 저가: {orb_low:,}원
호가 스프레드: {spread_pct:.2f}%
업종: {sector}
시장 센티먼트: {market_sentiment}
뉴스/공시: {news_summary}

다음 JSON 형식으로만 응답하세요:
{{"symbol": "{symbol}", "action_bias": "allow|watch|avoid", "entry_score": 0.0~1.0, "exit_urgency": 0.0~1.0, "confidence": 0.0~1.0, "risk_flags": [...], "reason_codes": [...], "commentary": "..."}}"""


class AIAdvisor:
    """
    AI 보조 분석 어드바이저.

    Gemini 2.5 Flash Lite를 이벤트 기반으로 호출합니다.
    일일 호출 상한과 종목별 쿨다운을 관리합니다.
    AI 장애 시 자동으로 비활성화되며, 규칙 기반 엔진만 운용됩니다.

    Attributes:
        is_available: AI 호출 가능 여부.
        daily_call_count: 금일 AI 호출 횟수.

    Example:
        >>> advisor = AIAdvisor()
        >>> result = await advisor.analyze_entry(request)
        >>> if result and result.action_bias == ActionBias.ALLOW:
        ...     # AI가 허용 의견, 하지만 하드 룰 통과는 별도
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._daily_call_count: int = 0
        self._last_call_per_symbol: dict[str, float] = {}
        self._is_degraded: bool = False
        self._consecutive_errors: int = 0
        self._client = None

    @property
    def is_available(self) -> bool:
        """AI 호출 가능 여부."""
        if not self._settings.ai_enabled:
            return False
        if self._is_degraded:
            return False
        if self._daily_call_count >= self._settings.ai_daily_call_limit:
            return False
        return True

    @property
    def daily_call_count(self) -> int:
        """금일 호출 횟수."""
        return self._daily_call_count

    def _check_cooldown(self, symbol: str) -> bool:
        """종목 쿨다운 확인. True이면 호출 가능."""
        last_call = self._last_call_per_symbol.get(symbol, 0)
        return (time.time() - last_call) >= self._settings.ai_cooldown_seconds

    async def _init_client(self) -> None:
        """Gemini 클라이언트 초기화."""
        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=self._settings.gemini_api_key)
            except ImportError:
                logger.warning("google-genai 패키지 미설치 - AI 비활성화")
                self._is_degraded = True
            except Exception as e:
                logger.error(f"Gemini 클라이언트 초기화 실패: {e}")
                self._is_degraded = True

    async def analyze_entry(
        self,
        request: AIAnalysisRequest,
    ) -> Optional[AIAnalysisResponse]:
        """
        종목 진입 분석을 AI에 요청합니다.

        AI 응답이 JSON 스키마를 벗어나면 무효 처리합니다.
        AI 장애 시에도 None을 반환하며 규칙 엔진은 계속 운용됩니다.

        Args:
            request: 분석 요청 데이터.

        Returns:
            AI 분석 결과. 실패 또는 쿨다운 중이면 None.
        """
        if not self.is_available:
            return None

        if not self._check_cooldown(request.symbol):
            logger.debug(f"AI 쿨다운 중: {request.symbol}")
            return None

        await self._init_client()
        if self._client is None:
            return None

        try:
            prompt = ANALYSIS_PROMPT_TEMPLATE.format(**request.model_dump())

            response = self._client.models.generate_content(
                model=self._settings.gemini_model,
                contents=prompt,
                config={
                    "system_instruction": SYSTEM_PROMPT,
                    "response_mime_type": "application/json",
                    "temperature": 0.3,
                    "max_output_tokens": 500,
                },
            )

            # 호출 카운트 업데이트
            self._daily_call_count += 1
            self._last_call_per_symbol[request.symbol] = time.time()

            # 응답 파싱
            raw_text = response.text.strip()
            parsed = json.loads(raw_text)
            result = AIAnalysisResponse(**parsed)

            self._consecutive_errors = 0

            logger.info(
                "AI 분석 완료",
                extra={
                    "event": "ai_analysis_complete",
                    "symbol": request.symbol,
                    "action_bias": result.action_bias.value,
                    "entry_score": result.entry_score,
                    "confidence": result.confidence,
                    "daily_calls": self._daily_call_count,
                },
            )

            return result

        except json.JSONDecodeError as e:
            self._consecutive_errors += 1
            logger.warning(
                "AI 응답 JSON 파싱 실패 - 무효 처리",
                extra={
                    "event": "ai_json_parse_error",
                    "symbol": request.symbol,
                    "error": str(e),
                    "consecutive_errors": self._consecutive_errors,
                },
            )
            return None

        except Exception as e:
            self._consecutive_errors += 1
            logger.warning(
                "AI 호출 실패 - 규칙 엔진 단독 운용 지속",
                extra={
                    "event": "ai_call_error",
                    "symbol": request.symbol,
                    "error": str(e),
                    "consecutive_errors": self._consecutive_errors,
                },
            )

            # 연속 3회 이상 실패 시 AI 비활성화
            if self._consecutive_errors >= 3:
                self._is_degraded = True
                logger.error(
                    "AI 연속 실패 3회 - 자동 비활성화",
                    extra={"event": "ai_degraded"},
                )

            return None

    def reset_daily_counter(self) -> None:
        """일일 호출 카운터를 리셋합니다 (매일 장 시작 시)."""
        self._daily_call_count = 0
        self._last_call_per_symbol.clear()
        self._consecutive_errors = 0
        self._is_degraded = False
        logger.info("AI 일일 카운터 리셋")

    def get_status(self) -> dict:
        """AI 상태 요약."""
        return {
            "enabled": self._settings.ai_enabled,
            "available": self.is_available,
            "degraded": self._is_degraded,
            "daily_calls": self._daily_call_count,
            "daily_limit": self._settings.ai_daily_call_limit,
            "consecutive_errors": self._consecutive_errors,
            "model": self._settings.gemini_model,
        }
