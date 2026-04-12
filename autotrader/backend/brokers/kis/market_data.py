# -*- coding: utf-8 -*-
"""
한국투자증권 시세 데이터 조회 래퍼.

REST API를 통해 주식 현재가, 일별 시세, 호가 등을 조회합니다.

공식 문서 확인 포인트 (TR ID):
  - 주식현재가 시세: FHKST01010100
  - 주식현재가 호가/예상체결: FHKST01010200
  - 주식현재가 일별: FHKST01010400
  - 주식현재가 체결: FHKST01010300
  - 국내주식기간별시세(일/주/월/년): FHKST03010100
  - 거래량순위: FHPST01710000
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from backend.brokers.base import MarketPrice, OrderBook, OrderBookEntry
from backend.brokers.kis.rest_client import KISRestClient
from backend.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# TR IDs
TR_INQUIRE_PRICE = "FHKST01010100"        # 주식현재가 시세
TR_INQUIRE_ASKING_PRICE = "FHKST01010200"  # 주식현재가 호가
TR_INQUIRE_DAILY_PRICE = "FHKST01010400"   # 주식현재가 일별
TR_VOLUME_RANK = "FHPST01710000"           # 거래량순위
TR_INQUIRE_DAILY_CHART = "FHKST03010100"   # 기간별시세

# API 경로
PATH_INQUIRE_PRICE = "/uapi/domestic-stock/v1/quotations/inquire-price"
PATH_ASKING_PRICE = "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
PATH_DAILY_PRICE = "/uapi/domestic-stock/v1/quotations/inquire-daily-price"
PATH_VOLUME_RANK = "/uapi/domestic-stock/v1/quotations/volume-rank"
PATH_DAILY_CHART = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"


class KISMarketData:
    """
    한국투자증권 시세 데이터 래퍼.

    REST API를 통해 시세 데이터를 조회하고 표준 모델로 변환합니다.

    Example:
        >>> md = KISMarketData(rest_client)
        >>> price = await md.get_current_price("005930")
        >>> print(f"삼성전자 현재가: {price.current_price}")
    """

    def __init__(self, rest_client: KISRestClient) -> None:
        self._client = rest_client

    async def get_current_price(self, symbol: str) -> MarketPrice:
        """
        종목 현재가를 조회합니다.

        Args:
            symbol: 종목코드 (6자리).

        Returns:
            MarketPrice: 현재가 데이터.
        """
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",  # 주식
            "FID_INPUT_ISCD": symbol,
        }

        data = await self._client.get(
            PATH_INQUIRE_PRICE,
            tr_id=TR_INQUIRE_PRICE,
            params=params,
        )

        output = data.get("output", {})

        return MarketPrice(
            symbol=symbol,
            current_price=Decimal(output.get("stck_prpr", "0")),
            open_price=Decimal(output.get("stck_oprc", "0")),
            high_price=Decimal(output.get("stck_hgpr", "0")),
            low_price=Decimal(output.get("stck_lwpr", "0")),
            prev_close=Decimal(output.get("stck_sdpr", "0")),
            volume=int(output.get("acml_vol", "0")),
            trade_amount=int(output.get("acml_tr_pbmn", "0")),
            change_pct=Decimal(output.get("prdy_ctrt", "0")),
            timestamp=datetime.now(),
        )

    async def get_orderbook(self, symbol: str) -> OrderBook:
        """
        종목 호가를 조회합니다.

        Args:
            symbol: 종목코드 (6자리).

        Returns:
            OrderBook: 호가 데이터.
        """
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
        }

        data = await self._client.get(
            PATH_ASKING_PRICE,
            tr_id=TR_INQUIRE_ASKING_PRICE,
            params=params,
        )

        output = data.get("output1", {})

        asks = []
        bids = []
        for i in range(1, 11):
            ask_price = output.get(f"askp{i}", "0")
            ask_qty = output.get(f"askp_rsqn{i}", "0")
            bid_price = output.get(f"bidp{i}", "0")
            bid_qty = output.get(f"bidp_rsqn{i}", "0")

            if int(ask_price) > 0:
                asks.append(OrderBookEntry(
                    price=Decimal(ask_price),
                    quantity=int(ask_qty),
                ))
            if int(bid_price) > 0:
                bids.append(OrderBookEntry(
                    price=Decimal(bid_price),
                    quantity=int(bid_qty),
                ))

        return OrderBook(
            symbol=symbol,
            asks=asks,
            bids=bids,
            timestamp=datetime.now(),
        )

    async def get_daily_prices(
        self,
        symbol: str,
        period: str = "D",
        count: int = 20,
    ) -> list[dict]:
        """
        일별/주별/월별 시세를 조회합니다.

        Args:
            symbol: 종목코드.
            period: 기간 구분 (D: 일, W: 주, M: 월).
            count: 조회 건수 (최대 100).

        Returns:
            시세 데이터 리스트 (최신순).
        """
        today = datetime.now().strftime("%Y%m%d")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_DATE_1": "",  # 시작일 (빈값이면 오늘 기준)
            "FID_INPUT_DATE_2": today,
            "FID_PERIOD_DIV_CODE": period,
            "FID_ORG_ADJ_PRC": "0",  # 원주가(수정주가 아님): 0
        }

        data = await self._client.get(
            PATH_DAILY_CHART,
            tr_id=TR_INQUIRE_DAILY_CHART,
            params=params,
        )

        output2 = data.get("output2", [])
        results = []
        for item in output2[:count]:
            results.append({
                "date": item.get("stck_bsop_date", ""),
                "open": int(item.get("stck_oprc", "0")),
                "high": int(item.get("stck_hgpr", "0")),
                "low": int(item.get("stck_lwpr", "0")),
                "close": int(item.get("stck_clpr", "0")),
                "volume": int(item.get("acml_vol", "0")),
                "trade_amount": int(item.get("acml_tr_pbmn", "0")),
            })

        return results

    async def get_volume_rank(
        self,
        market: str = "J",
        sort_by: str = "0",
        limit: int = 20,
    ) -> list[dict]:
        """
        거래량 순위를 조회합니다.

        Args:
            market: 시장 구분 (J: 전체, K: KOSPI, Q: KOSDAQ).
            sort_by: 정렬 기준 (0: 거래량, 1: 거래대금).
            limit: 조회 건수.

        Returns:
            거래량 순위 리스트.
        """
        params = {
            "FID_COND_MRKT_DIV_CODE": market,
            "FID_COND_SCR_DIV_CODE": "20101",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "0",
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "000000",
            "FID_INPUT_PRICE_1": "0",
            "FID_INPUT_PRICE_2": "0",
            "FID_VOL_CNT": "0",
            "FID_INPUT_DATE_1": "",
        }

        data = await self._client.get(
            PATH_VOLUME_RANK,
            tr_id=TR_VOLUME_RANK,
            params=params,
        )

        output = data.get("output", [])
        results = []
        for item in output[:limit]:
            results.append({
                "rank": int(item.get("data_rank", "0")),
                "symbol": item.get("mksc_shrn_iscd", ""),
                "name": item.get("hts_kor_isnm", ""),
                "current_price": int(item.get("stck_prpr", "0")),
                "change_pct": float(item.get("prdy_ctrt", "0")),
                "volume": int(item.get("acml_vol", "0")),
                "trade_amount": int(item.get("acml_tr_pbmn", "0")),
                "prev_close": int(item.get("stck_sdpr", "0")),
            })

        return results

    async def calculate_avg_volume_20d(self, symbol: str) -> int:
        """
        최근 20일 평균 거래대금을 계산합니다.

        Args:
            symbol: 종목코드.

        Returns:
            20일 평균 거래대금 (원).
        """
        daily_data = await self.get_daily_prices(symbol, period="D", count=20)
        if not daily_data:
            return 0

        total = sum(d["trade_amount"] for d in daily_data)
        return total // len(daily_data) if daily_data else 0
