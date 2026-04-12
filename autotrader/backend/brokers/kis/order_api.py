# -*- coding: utf-8 -*-
"""
한국투자증권 주문 API 래퍼.

주식 매수/매도/정정/취소 주문을 처리합니다.

공식 문서 확인 포인트 (TR ID):
  - 매수: TTTC0802U (실전) / VTTC0802U (모의)
  - 매도: TTTC0801U (실전) / VTTC0801U (모의)
  - 정정: TTTC0803U (실전) / VTTC0803U (모의)
  - 취소: TTTC0803U (동일 TR, 주문구분으로 분기)
  - 주문 조회: TTTC8001R (실전) / VTTC8001R (모의)

주의:
  - 실전/모의 TR ID가 다름 → rest_client에서 자동 변환
  - 주문 시 CANO(계좌번호 앞8), ACNT_PRDT_CD(뒤2) 필수
"""

import logging
from decimal import Decimal
from typing import Optional

from backend.brokers.base import (
    BaseBroker,
    AccountBalance,
    MarketPrice,
    OrderBook,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
    StockPosition,
)
from backend.brokers.kis.auth import KISAuth
from backend.brokers.kis.market_data import KISMarketData
from backend.brokers.kis.rest_client import KISRestClient
from backend.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# TR IDs (실전 기준, 모의는 rest_client에서 V로 자동 변환)
TR_BUY_ORDER = "TTTC0802U"
TR_SELL_ORDER = "TTTC0801U"
TR_MODIFY_CANCEL = "TTTC0803U"
TR_ORDER_INQUIRY = "TTTC8001R"

# 계좌 조회
TR_BALANCE = "TTTC8434R"  # 주식잔고조회

# API 경로
PATH_ORDER = "/uapi/domestic-stock/v1/trading/order-cash"
PATH_MODIFY_CANCEL = "/uapi/domestic-stock/v1/trading/order-rvsecncl"
PATH_BALANCE = "/uapi/domestic-stock/v1/trading/inquire-balance"
PATH_DAILY_CCLD = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"

# 주문 유형 코드 (한투 기준)
ORD_TYPE_LIMIT = "00"           # 지정가
ORD_TYPE_MARKET = "01"          # 시장가
ORD_TYPE_CONDITIONAL = "02"     # 조건부 지정가
ORD_TYPE_BEST_LIMIT = "03"      # 최유리 지정가
ORD_TYPE_FIRST_LIMIT = "04"     # 최우선 지정가


class KISOrderAPI(BaseBroker):
    """
    한국투자증권 주문 API 구현.

    BaseBroker 인터페이스를 구현하여 실제 KIS API와 통신합니다.

    Example:
        >>> auth = KISAuth()
        >>> api = KISOrderAPI(auth)
        >>> await api.connect()
        >>> balance = await api.get_balance()
    """

    def __init__(
        self,
        auth: KISAuth,
        settings: Optional[Settings] = None,
    ) -> None:
        self._auth = auth
        self._settings = settings or get_settings()
        self._rest_client = KISRestClient(auth, settings)
        self._market_data = KISMarketData(self._rest_client)
        self._connected: bool = False

    @property
    def market_data(self) -> KISMarketData:
        """시세 데이터 래퍼."""
        return self._market_data

    async def connect(self) -> bool:
        """KIS API에 연결합니다 (토큰 발급)."""
        try:
            await self._auth.ensure_token()
            self._connected = True
            logger.info(
                "KIS API 연결 완료",
                extra={
                    "event": "kis_connected",
                    "mode": self._settings.trading_mode.value,
                },
            )
            return True
        except Exception as e:
            logger.error(f"KIS API 연결 실패: {e}")
            return False

    async def disconnect(self) -> None:
        """연결을 종료합니다."""
        await self._auth.close()
        await self._rest_client.close()
        self._connected = False

    async def is_connected(self) -> bool:
        """연결 상태."""
        return self._connected and self._auth.is_authenticated

    async def get_balance(self) -> AccountBalance:
        """
        계좌 잔고를 조회합니다.

        TR ID: TTTC8434R (실전) / VTTC8434R (모의)
        """
        params = {
            "CANO": self._settings.active_account_no,
            "ACNT_PRDT_CD": self._settings.kis_account_prod,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        data = await self._rest_client.get(
            PATH_BALANCE,
            tr_id=TR_BALANCE,
            params=params,
        )

        output2 = data.get("output2", [{}])
        summary = output2[0] if output2 else {}

        return AccountBalance(
            total_equity=Decimal(summary.get("tot_evlu_amt", "0")),
            available_cash=Decimal(summary.get("dnca_tot_amt", "0")),
            total_profit_loss=Decimal(summary.get("evlu_pfls_smtl_amt", "0")),
            total_profit_loss_pct=Decimal(summary.get("evlu_pfls_rt", "0")),
        )

    async def get_positions(self) -> list[StockPosition]:
        """보유 종목을 조회합니다."""
        params = {
            "CANO": self._settings.active_account_no,
            "ACNT_PRDT_CD": self._settings.kis_account_prod,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        data = await self._rest_client.get(
            PATH_BALANCE,
            tr_id=TR_BALANCE,
            params=params,
        )

        output1 = data.get("output1", [])
        positions = []
        for item in output1:
            if int(item.get("hldg_qty", "0")) > 0:
                positions.append(StockPosition(
                    symbol=item.get("pdno", ""),
                    name=item.get("prdt_name", ""),
                    quantity=int(item.get("hldg_qty", "0")),
                    avg_price=Decimal(item.get("pchs_avg_pric", "0")),
                    current_price=Decimal(item.get("prpr", "0")),
                    profit_loss=Decimal(item.get("evlu_pfls_amt", "0")),
                    profit_loss_pct=Decimal(item.get("evlu_pfls_rt", "0")),
                ))

        return positions

    async def get_price(self, symbol: str) -> MarketPrice:
        """종목 현재가."""
        return await self._market_data.get_current_price(symbol)

    async def get_orderbook(self, symbol: str) -> OrderBook:
        """종목 호가."""
        return await self._market_data.get_orderbook(symbol)

    async def submit_order(self, request: OrderRequest) -> OrderResponse:
        """
        주문을 제출합니다.

        매수: TTTC0802U, 매도: TTTC0801U
        """
        tr_id = TR_BUY_ORDER if request.side == OrderSide.BUY else TR_SELL_ORDER

        # 주문 유형 코드 변환
        ord_dvsn = ORD_TYPE_MARKET if request.order_type == OrderType.MARKET else ORD_TYPE_LIMIT

        body = {
            "CANO": self._settings.active_account_no,
            "ACNT_PRDT_CD": self._settings.kis_account_prod,
            "PDNO": request.symbol,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(request.quantity),
            "ORD_UNPR": str(int(request.price)) if request.price else "0",
        }

        try:
            data = await self._rest_client.post(
                PATH_ORDER,
                tr_id=tr_id,
                body=body,
            )

            output = data.get("output", {})
            broker_order_id = output.get("ODNO", "")

            logger.info(
                "주문 제출 성공",
                extra={
                    "event": "order_submitted",
                    "symbol": request.symbol,
                    "side": request.side.value,
                    "quantity": request.quantity,
                    "broker_order_id": broker_order_id,
                },
            )

            return OrderResponse(
                success=True,
                broker_order_id=broker_order_id,
                status=OrderStatus.SUBMITTED,
                message=data.get("msg1", ""),
                raw_response=data,
            )

        except Exception as e:
            logger.error(
                "주문 제출 실패",
                extra={
                    "event": "order_submit_failed",
                    "symbol": request.symbol,
                    "error": str(e),
                },
            )
            return OrderResponse(
                success=False,
                status=OrderStatus.ERROR,
                message=str(e),
            )

    async def cancel_order(self, broker_order_id: str) -> OrderResponse:
        """
        주문을 취소합니다.

        TR ID: TTTC0803U (정정/취소 공용)
        """
        body = {
            "CANO": self._settings.active_account_no,
            "ACNT_PRDT_CD": self._settings.kis_account_prod,
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": broker_order_id,
            "ORD_DVSN": "00",
            "RVSE_CNCL_DVSN_CD": "02",  # 02: 취소
            "ORD_QTY": "0",  # 전량
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",  # 전량 취소
        }

        try:
            data = await self._rest_client.post(
                PATH_MODIFY_CANCEL,
                tr_id=TR_MODIFY_CANCEL,
                body=body,
            )

            return OrderResponse(
                success=True,
                broker_order_id=broker_order_id,
                status=OrderStatus.CANCELLED,
                message=data.get("msg1", ""),
                raw_response=data,
            )

        except Exception as e:
            return OrderResponse(
                success=False,
                broker_order_id=broker_order_id,
                status=OrderStatus.ERROR,
                message=str(e),
            )

    async def get_order_status(self, broker_order_id: str) -> OrderResponse:
        """
        주문 상태를 조회합니다.

        TR ID: TTTC8001R
        """
        params = {
            "CANO": self._settings.active_account_no,
            "ACNT_PRDT_CD": self._settings.kis_account_prod,
            "INQR_STRT_DT": "",
            "INQR_END_DT": "",
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "01",
            "ORD_GNO_BRNO": "",
            "ODNO": broker_order_id,
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        try:
            data = await self._rest_client.get(
                PATH_DAILY_CCLD,
                tr_id=TR_ORDER_INQUIRY,
                params=params,
            )

            output1 = data.get("output1", [])
            if output1:
                item = output1[0]
                filled_qty = int(item.get("tot_ccld_qty", "0"))
                ord_qty = int(item.get("ord_qty", "0"))

                if filled_qty >= ord_qty and ord_qty > 0:
                    status = OrderStatus.FILLED
                elif filled_qty > 0:
                    status = OrderStatus.PARTIAL
                else:
                    status = OrderStatus.SUBMITTED

                return OrderResponse(
                    success=True,
                    broker_order_id=broker_order_id,
                    status=status,
                    filled_quantity=filled_qty,
                    filled_price=Decimal(item.get("avg_prvs", "0")) if filled_qty > 0 else None,
                    raw_response=data,
                )

            return OrderResponse(
                success=True,
                broker_order_id=broker_order_id,
                status=OrderStatus.PENDING,
            )

        except Exception as e:
            return OrderResponse(
                success=False,
                broker_order_id=broker_order_id,
                status=OrderStatus.ERROR,
                message=str(e),
            )
