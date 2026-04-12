# -*- coding: utf-8 -*-
"""
종목 스캐너 모듈.

장 시작 전후로 후보 종목을 선별합니다.
갭 상승, 거래대금 급증, 유동성, 관리종목 제외 등을 필터링합니다.

스캐닝 흐름:
  1. 거래량 순위 API로 후보 풀 확보 (상위 50종목)
  2. 시가 갭 필터 (gap_up_min ~ gap_up_max)
  3. 거래대금 서지 필터 (20일 평균 대비)
  4. 시가총액 필터 (극소형주 제외)
  5. 관리종목/투자유의/상한가 근접 제외
  6. 점수 계산 + 정렬
  7. 상위 N개 반환
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from backend.config.strategy_config import AggressiveProfileConfig

logger = logging.getLogger(__name__)


@dataclass
class ScanCandidate:
    """스캔된 후보 종목."""
    symbol: str
    name: str = ""
    current_price: int = 0
    open_price: int = 0
    prev_close: int = 0
    high_price: int = 0
    low_price: int = 0
    volume: int = 0
    trade_amount: int = 0  # 거래대금 (원)
    gap_pct: float = 0.0
    volume_ratio: float = 0.0  # 20일 평균 대비
    avg_volume_20d: int = 0
    market_cap: int = 0
    sector: str = ""
    rank_score: float = 0.0
    tags: list[str] = field(default_factory=list)
    excluded: bool = False
    exclude_reason: str = ""

    @property
    def spread_estimate_pct(self) -> float:
        """추정 스프레드 (호가 미조회 시 사용)."""
        if self.current_price > 0:
            # 호가 단위 기반 추정
            if self.current_price >= 500000:
                tick = 1000
            elif self.current_price >= 100000:
                tick = 500
            elif self.current_price >= 50000:
                tick = 100
            elif self.current_price >= 10000:
                tick = 50
            elif self.current_price >= 5000:
                tick = 10
            elif self.current_price >= 1000:
                tick = 5
            else:
                tick = 1
            return (tick / self.current_price) * 100
        return 0.0


class Scanner:
    """
    종목 스캐너.

    시장에서 모멘텀 후보 종목을 선별합니다.
    paper/live 모두 동일한 스캐닝 로직을 사용합니다.

    Example:
        >>> scanner = Scanner(config)
        >>> candidates = await scanner.scan(market_data)
        >>> for c in candidates:
        ...     print(f"{c.symbol} {c.name}: 갭 {c.gap_pct:.1f}% 거래량 {c.volume_ratio:.1f}x")
    """

    def __init__(self, config: Optional[AggressiveProfileConfig] = None) -> None:
        self._config = config or AggressiveProfileConfig()
        self._exclusion_list: set[str] = set()  # 제외 종목 (관리/투자주의)

    def add_exclusion(self, symbol: str, reason: str = "") -> None:
        """종목을 제외 목록에 추가합니다."""
        self._exclusion_list.add(symbol)
        logger.info(f"제외 종목 추가: {symbol} ({reason})")

    def clear_exclusions(self) -> None:
        """제외 목록을 초기화합니다."""
        self._exclusion_list.clear()

    async def scan(self, market_data) -> list[ScanCandidate]:
        """
        후보 종목을 스캔합니다.

        Args:
            market_data: KISMarketData 인스턴스.

        Returns:
            점수순으로 정렬된 후보 종목 리스트.
        """
        # 1. 거래량 순위로 후보 풀 확보
        try:
            volume_rank = await market_data.get_volume_rank(
                market="J", limit=50
            )
        except Exception as e:
            logger.error(f"거래량 순위 조회 실패: {e}")
            return []

        candidates: list[ScanCandidate] = []

        for item in volume_rank:
            symbol = item.get("symbol", "")
            if not symbol:
                continue

            candidate = ScanCandidate(
                symbol=symbol,
                name=item.get("name", ""),
                current_price=item.get("current_price", 0),
                prev_close=item.get("prev_close", 0),
                volume=item.get("volume", 0),
                trade_amount=item.get("trade_amount", 0),
                gap_pct=item.get("change_pct", 0.0),
            )

            # 갭 계산
            if candidate.prev_close > 0:
                candidate.gap_pct = (
                    (candidate.current_price - candidate.prev_close)
                    / candidate.prev_close * 100
                )

            # 필터링
            self._apply_filters(candidate)

            if not candidate.excluded:
                candidates.append(candidate)

        # 20일 평균 거래대금 조회 (상위 후보만)
        for c in candidates[:20]:
            try:
                c.avg_volume_20d = await market_data.calculate_avg_volume_20d(c.symbol)
                if c.avg_volume_20d > 0:
                    c.volume_ratio = c.trade_amount / c.avg_volume_20d
            except Exception:
                pass

        # 거래대금 서지 필터 적용
        candidates = [
            c for c in candidates
            if c.volume_ratio >= self._config.volume_surge_ratio
            or c.avg_volume_20d == 0  # 아직 미조회
        ]

        # 점수 계산
        for c in candidates:
            c.rank_score = self._calculate_score(c)

        # 점수순 정렬
        candidates.sort(key=lambda x: x.rank_score, reverse=True)

        logger.info(
            f"스캔 완료: {len(candidates)}개 후보",
            extra={
                "event": "scan_complete",
                "candidate_count": len(candidates),
                "top3": [
                    {"symbol": c.symbol, "name": c.name, "score": c.rank_score}
                    for c in candidates[:3]
                ],
            },
        )

        return candidates

    def _apply_filters(self, c: ScanCandidate) -> None:
        """필터를 적용합니다."""
        # 제외 목록 체크
        if c.symbol in self._exclusion_list:
            c.excluded = True
            c.exclude_reason = "제외 목록"
            return

        # 갭 필터
        if c.gap_pct < self._config.gap_up_min_pct:
            c.excluded = True
            c.exclude_reason = f"갭 부족: {c.gap_pct:.1f}%"
            return

        if c.gap_pct > self._config.gap_up_max_pct:
            c.excluded = True
            c.exclude_reason = f"갭 과다: {c.gap_pct:.1f}%"
            c.tags.append("NEAR_UPPER_LIMIT")
            return

        # 음봉/하락 제외
        if c.gap_pct <= 0:
            c.excluded = True
            c.exclude_reason = "하락 종목"
            return

        # 상한가 근접 체크 (29% 이상)
        if c.gap_pct >= 29.0:
            c.excluded = True
            c.exclude_reason = "상한가 근접"
            c.tags.append("UPPER_LIMIT")
            return

    def _calculate_score(self, c: ScanCandidate) -> float:
        """
        후보 종목 점수를 계산합니다.

        점수 = 갭 점수(40%) + 거래량 점수(40%) + 안정성 점수(20%)
        """
        # 갭 점수: 5% 전후가 최적
        gap_score = 0.0
        if 3.0 <= c.gap_pct <= 7.0:
            gap_score = 1.0
        elif 7.0 < c.gap_pct <= 12.0:
            gap_score = 0.7
        elif 1.0 <= c.gap_pct < 3.0:
            gap_score = 0.3

        # 거래량 점수
        vol_score = min(1.0, c.volume_ratio / 5.0) if c.volume_ratio > 0 else 0.5

        # 안정성 점수 (스프레드 낮을수록 좋음)
        spread = c.spread_estimate_pct
        stability_score = max(0, 1.0 - spread / 1.0) if spread > 0 else 0.5

        return gap_score * 0.4 + vol_score * 0.4 + stability_score * 0.2
