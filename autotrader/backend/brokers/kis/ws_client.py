# -*- coding: utf-8 -*-
"""
한국투자증권 WebSocket 클라이언트.

실시간 체결가, 호가, 체결 통보를 수신합니다.
끊김 감지 + 자동 재연결 로직을 포함합니다.

공식 문서 확인 포인트:
  - 웹소켓 URL: ws://ops.koreainvestment.com:21000 (실전)
  - 웹소켓 URL: ws://ops.koreainvestment.com:31000 (모의)
  - 체결가: H0STCNT0 (실전) / H0STCNT0 (모의 동일)
  - 호가: H0STASP0
  - 체결통보: H0STCNI0 (실전) / H0STCNI9 (모의)
  - 최대 구독: 40건
  - PINGPONG 응답 필수
  - 데이터 구분자: '^'
  - 암호화 데이터: AES-CBC-Base64 복호화 필요

기존 kis_auth.py의 KISWebSocket 패턴을 참조하되,
asyncio 기반 + 자동 재연결 + 구조화 로그로 재구현합니다.
"""

import asyncio
import json
import logging
import time
from base64 import b64decode
from datetime import datetime
from io import StringIO
from typing import Any, Callable, Coroutine, Optional

import websockets
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from backend.brokers.kis.auth import KISAuth
from backend.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# 상수
MAX_SUBSCRIPTIONS = 40
PING_INTERVAL_SECONDS = 30
RECONNECT_INITIAL_DELAY = 1.0
RECONNECT_MAX_DELAY = 60.0
RECONNECT_MAX_RETRIES = 50  # 장중 재연결 시도 충분히

# TR ID 매핑
TR_ID_REALTIME_PRICE = "H0STCNT0"       # 실시간 체결가
TR_ID_REALTIME_ORDERBOOK = "H0STASP0"   # 실시간 호가
TR_ID_EXECUTION_NOTICE = "H0STCNI0"     # 체결 통보 (실전)
TR_ID_EXECUTION_NOTICE_PAPER = "H0STCNI9"  # 체결 통보 (모의)

# 실시간 체결가 컬럼 (한투 공식 문서 기준)
REALTIME_PRICE_COLUMNS = [
    "MKSC_SHRN_ISCD",  # 유가증권 단축 종목코드
    "STCK_CNTG_HOUR",  # 주식 체결 시간
    "STCK_PRPR",       # 주식 현재가
    "PRDY_VRSS_SIGN",  # 전일 대비 부호
    "PRDY_VRSS",       # 전일 대비
    "PRDY_CTRT",       # 전일 대비율
    "WGHN_AVRG_STCK_PRC",  # 가중 평균 주식 가격
    "STCK_OPRC",       # 주식 시가
    "STCK_HGPR",       # 주식 최고가
    "STCK_LWPR",       # 주식 최저가
    "ASKP1",           # 매도호가1
    "BIDP1",           # 매수호가1
    "CNTG_VOL",        # 체결 거래량
    "ACML_VOL",        # 누적 거래량
    "ACML_TR_PBMN",    # 누적 거래 대금
    "SELN_CNTG_CSNU",  # 매도 체결 건수
    "SHNU_CNTG_CSNU",  # 매수 체결 건수
    "NTBY_CNTG_CSNU",  # 순매수 체결 건수
    "CTTR",            # 체결강도
    "SELN_CNTG_SMTN",  # 총 매도 수량
    "SHNU_CNTG_SMTN",  # 총 매수 수량
    "CCLD_DVSN",       # 체결구분
    "SHNU_RATE",       # 매수비율
    "PRDY_VOL_VRSS_ACML_VOL_RATE",  # 전일 거래량 대비 등락률
    "OPRC_HOUR",       # 시가 시간
    "OPRC_VRSS_PRPR_SIGN",  # 시가대비구분
    "OPRC_VRSS_PRPR",  # 시가대비
    "HGPR_HOUR",       # 최고가 시간
    "HGPR_VRSS_PRPR_SIGN",  # 고가대비구분
    "HGPR_VRSS_PRPR",  # 고가대비
    "LWPR_HOUR",       # 최저가 시간
    "LWPR_VRSS_PRPR_SIGN",  # 저가대비구분
    "LWPR_VRSS_PRPR",  # 저가대비
    "BSOP_DATE",       # 영업 일자
    "NEW_MKOP_CLS_CODE",  # 신 장운영 구분 코드
    "TRHT_YN",         # 거래정지 여부
    "ASKP_RSQN1",      # 매도호가 잔량1
    "BIDP_RSQN1",      # 매수호가 잔량1
    "TOTAL_ASKP_RSQN", # 총 매도호가 잔량
    "TOTAL_BIDP_RSQN", # 총 매수호가 잔량
    "VOL_TNRT",        # 거래량 회전율
    "PRDY_SMNS_HOUR_ACML_VOL",  # 전일 동시간 누적 거래량
    "PRDY_SMNS_HOUR_ACML_VOL_RATE",  # 전일 동시간 누적 거래량 비율
    "HOUR_CLS_CODE",   # 시간 구분 코드
    "MRKT_TRTM_CLS_CODE",  # 임의종료구분코드
    "VI_STND_PRC",     # VI적용구분코드
]

# 호가 컬럼 (한투 공식 문서 기준, 간략화)
REALTIME_ORDERBOOK_COLUMNS = [
    "MKSC_SHRN_ISCD",  # 종목코드
    "BSOP_HOUR",       # 영업시간
    "HOUR_CLS_CODE",   # 시간구분코드
    # 매도호가 1~10
    "ASKP1", "ASKP2", "ASKP3", "ASKP4", "ASKP5",
    "ASKP6", "ASKP7", "ASKP8", "ASKP9", "ASKP10",
    # 매수호가 1~10
    "BIDP1", "BIDP2", "BIDP3", "BIDP4", "BIDP5",
    "BIDP6", "BIDP7", "BIDP8", "BIDP9", "BIDP10",
    # 매도호가 잔량 1~10
    "ASKP_RSQN1", "ASKP_RSQN2", "ASKP_RSQN3", "ASKP_RSQN4", "ASKP_RSQN5",
    "ASKP_RSQN6", "ASKP_RSQN7", "ASKP_RSQN8", "ASKP_RSQN9", "ASKP_RSQN10",
    # 매수호가 잔량 1~10
    "BIDP_RSQN1", "BIDP_RSQN2", "BIDP_RSQN3", "BIDP_RSQN4", "BIDP_RSQN5",
    "BIDP_RSQN6", "BIDP_RSQN7", "BIDP_RSQN8", "BIDP_RSQN9", "BIDP_RSQN10",
    # 총잔량
    "TOTAL_ASKP_RSQN", "TOTAL_BIDP_RSQN",
    "OVTM_TOTAL_ASKP_RSQN", "OVTM_TOTAL_BIDP_RSQN",
    "ANTC_CNPR", "ANTC_CNQN", "ANTC_VOL", "ANTC_TR_PBMN",
    "ACML_VOL", "TOTAL_ASKP_RSQN_ICDC", "TOTAL_BIDP_RSQN_ICDC",
]

# 콜백 타입 정의
RealtimeCallback = Callable[[str, str, dict[str, str]], Coroutine[Any, Any, None]]
# (tr_id, symbol, data_dict) -> None


class KISWebSocketClient:
    """
    한국투자증권 실시간 WebSocket 클라이언트.

    실시간 체결가, 호가, 체결 통보를 수신합니다.
    끊김 시 자동 재연결하며, 재연결 후 기존 구독을 복원합니다.

    Attributes:
        is_connected: 연결 상태.
        subscription_count: 현재 구독 수.

    Example:
        >>> client = KISWebSocketClient(auth)
        >>> client.on_price = my_price_handler
        >>> await client.subscribe_price("005930")
        >>> await client.start()
    """

    def __init__(
        self,
        auth: KISAuth,
        settings: Optional[Settings] = None,
    ) -> None:
        self._auth = auth
        self._settings = settings or get_settings()
        self._ws: Optional[websockets.ClientConnection] = None
        self._is_connected: bool = False
        self._is_running: bool = False
        self._retry_count: int = 0

        # 구독 관리
        self._subscriptions: dict[str, set[str]] = {
            # tr_id -> set of symbols
        }
        # 암호화 키 관리
        self._encrypt_keys: dict[str, dict] = {}
        # (tr_id -> {"encrypt": "Y"/"N", "key": ..., "iv": ...})

        # 컬럼 매핑
        self._column_map: dict[str, list[str]] = {
            TR_ID_REALTIME_PRICE: REALTIME_PRICE_COLUMNS,
            TR_ID_REALTIME_ORDERBOOK: REALTIME_ORDERBOOK_COLUMNS,
        }

        # 콜백
        self.on_price: Optional[RealtimeCallback] = None
        self.on_orderbook: Optional[RealtimeCallback] = None
        self.on_execution: Optional[RealtimeCallback] = None
        self.on_disconnect: Optional[Callable[[], Coroutine[Any, Any, None]]] = None
        self.on_reconnect: Optional[Callable[[], Coroutine[Any, Any, None]]] = None

    @property
    def is_connected(self) -> bool:
        """연결 상태."""
        return self._is_connected

    @property
    def subscription_count(self) -> int:
        """현재 구독 수."""
        return sum(len(syms) for syms in self._subscriptions.values())

    async def start(self) -> None:
        """
        WebSocket 연결을 시작하고 메시지 수신 루프를 실행합니다.

        자동 재연결 포함. RECONNECT_MAX_RETRIES 초과 시 중단합니다.
        """
        self._is_running = True

        while self._is_running and self._retry_count < RECONNECT_MAX_RETRIES:
            try:
                await self._connect()
                await self._subscribe_all()
                await self._receive_loop()
            except websockets.ConnectionClosed as e:
                logger.warning(
                    "WebSocket 연결 종료",
                    extra={
                        "event": "ws_connection_closed",
                        "code": e.code,
                        "reason": str(e.reason),
                        "retry": self._retry_count,
                    },
                )
            except Exception as e:
                logger.error(
                    "WebSocket 오류",
                    extra={
                        "event": "ws_error",
                        "error": str(e),
                        "retry": self._retry_count,
                    },
                )

            self._is_connected = False
            if self.on_disconnect:
                await self.on_disconnect()

            if not self._is_running:
                break

            # 재연결 대기 (exponential backoff)
            delay = min(
                RECONNECT_INITIAL_DELAY * (2 ** self._retry_count),
                RECONNECT_MAX_DELAY,
            )
            self._retry_count += 1
            logger.info(
                f"WebSocket 재연결 대기: {delay:.1f}초 ({self._retry_count}/{RECONNECT_MAX_RETRIES})"
            )
            await asyncio.sleep(delay)

        if self._retry_count >= RECONNECT_MAX_RETRIES:
            logger.critical(
                "WebSocket 최대 재연결 초과 - 시스템 HALTED 전환 필요",
                extra={
                    "event": "ws_max_retries_exceeded",
                    "retries": self._retry_count,
                },
            )

    async def stop(self) -> None:
        """WebSocket 연결을 종료합니다."""
        self._is_running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._is_connected = False
        logger.info("WebSocket 클라이언트 종료")

    async def _connect(self) -> None:
        """WebSocket 연결을 수립합니다."""
        # approval_key 발급
        await self._auth.request_ws_approval_key()

        ws_url = f"{self._auth.ws_url}/tryitout/H0STCNT0"
        self._ws = await websockets.connect(ws_url)
        self._is_connected = True
        self._retry_count = 0  # 연결 성공 시 카운터 리셋

        logger.info(
            "WebSocket 연결 성공",
            extra={
                "event": "ws_connected",
                "url": ws_url,
                "mode": self._settings.trading_mode.value,
            },
        )

        if self.on_reconnect and self._retry_count > 0:
            await self.on_reconnect()

    async def _subscribe_all(self) -> None:
        """기존 구독을 모두 복원합니다 (재연결 후)."""
        for tr_id, symbols in self._subscriptions.items():
            for symbol in symbols:
                await self._send_subscribe(tr_id, symbol)

    async def subscribe_price(self, symbol: str) -> None:
        """
        실시간 체결가를 구독합니다.

        Args:
            symbol: 종목코드 (6자리).

        Raises:
            ValueError: 최대 구독 수 초과.
        """
        await self._add_subscription(TR_ID_REALTIME_PRICE, symbol)

    async def subscribe_orderbook(self, symbol: str) -> None:
        """
        실시간 호가를 구독합니다.

        Args:
            symbol: 종목코드 (6자리).
        """
        await self._add_subscription(TR_ID_REALTIME_ORDERBOOK, symbol)

    async def subscribe_execution(self) -> None:
        """
        체결 통보를 구독합니다.

        모의투자는 H0STCNI9, 실전은 H0STCNI0 사용.
        """
        tr_id = (
            TR_ID_EXECUTION_NOTICE_PAPER
            if self._settings.is_paper
            else TR_ID_EXECUTION_NOTICE
        )
        hts_id = self._settings.kis_hts_id
        await self._add_subscription(tr_id, hts_id)

    async def unsubscribe_price(self, symbol: str) -> None:
        """체결가 구독 해제."""
        await self._remove_subscription(TR_ID_REALTIME_PRICE, symbol)

    async def unsubscribe_orderbook(self, symbol: str) -> None:
        """호가 구독 해제."""
        await self._remove_subscription(TR_ID_REALTIME_ORDERBOOK, symbol)

    async def _add_subscription(self, tr_id: str, key: str) -> None:
        """구독을 추가합니다."""
        if self.subscription_count >= MAX_SUBSCRIPTIONS:
            raise ValueError(
                f"최대 구독 수({MAX_SUBSCRIPTIONS}) 초과. "
                "기존 구독을 해제한 후 추가하세요."
            )

        if tr_id not in self._subscriptions:
            self._subscriptions[tr_id] = set()

        self._subscriptions[tr_id].add(key)

        if self._is_connected:
            await self._send_subscribe(tr_id, key)

        logger.info(
            "구독 추가",
            extra={
                "event": "ws_subscribe",
                "tr_id": tr_id,
                "key": key,
                "total_subs": self.subscription_count,
            },
        )

    async def _remove_subscription(self, tr_id: str, key: str) -> None:
        """구독을 해제합니다."""
        if tr_id in self._subscriptions:
            self._subscriptions[tr_id].discard(key)

        if self._is_connected:
            await self._send_unsubscribe(tr_id, key)

    async def _send_subscribe(self, tr_id: str, key: str) -> None:
        """구독 메시지를 전송합니다."""
        msg = {
            "header": {
                "approval_key": self._auth.ws_approval_key,
                "custtype": "P",
                "tr_type": "1",  # 1: 등록
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": tr_id,
                    "tr_key": key,
                },
            },
        }
        if self._ws:
            await self._ws.send(json.dumps(msg))

    async def _send_unsubscribe(self, tr_id: str, key: str) -> None:
        """구독 해제 메시지를 전송합니다."""
        msg = {
            "header": {
                "approval_key": self._auth.ws_approval_key,
                "custtype": "P",
                "tr_type": "2",  # 2: 해제
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": tr_id,
                    "tr_key": key,
                },
            },
        }
        if self._ws:
            await self._ws.send(json.dumps(msg))

    async def _receive_loop(self) -> None:
        """메시지 수신 루프."""
        if not self._ws:
            return

        async for raw_message in self._ws:
            try:
                await self._handle_message(raw_message)
            except Exception as e:
                logger.error(
                    "메시지 처리 오류",
                    extra={
                        "event": "ws_message_error",
                        "error": str(e),
                        "raw_len": len(str(raw_message)),
                    },
                )

    async def _handle_message(self, raw: str) -> None:
        """
        수신 메시지를 처리합니다.

        메시지 형식:
          - '0' 또는 '1'로 시작: 데이터 메시지 (|로 구분)
          - JSON: 시스템 메시지 (구독 응답, PINGPONG)
        """
        if raw[0] in ("0", "1"):
            # 데이터 메시지: 0|H0STCNT0|004|data...
            parts = raw.split("|")
            if len(parts) < 4:
                return

            is_encrypted = parts[0] == "1"
            tr_id = parts[1]
            data_str = parts[3]

            # 암호화 복호화
            if is_encrypted and tr_id in self._encrypt_keys:
                keys = self._encrypt_keys[tr_id]
                data_str = self._aes_decrypt(
                    keys.get("key", ""),
                    keys.get("iv", ""),
                    data_str,
                )

            # 컬럼 매핑
            columns = self._column_map.get(tr_id, [])
            if columns:
                values = data_str.split("^")
                data_dict = {}
                for i, col in enumerate(columns):
                    if i < len(values):
                        data_dict[col] = values[i]

                symbol = data_dict.get("MKSC_SHRN_ISCD", "")

                # 콜백 호출
                if tr_id == TR_ID_REALTIME_PRICE and self.on_price:
                    await self.on_price(tr_id, symbol, data_dict)
                elif tr_id == TR_ID_REALTIME_ORDERBOOK and self.on_orderbook:
                    await self.on_orderbook(tr_id, symbol, data_dict)
                elif tr_id in (TR_ID_EXECUTION_NOTICE, TR_ID_EXECUTION_NOTICE_PAPER):
                    if self.on_execution:
                        await self.on_execution(tr_id, symbol, data_dict)
            else:
                # 체결통보 등 컬럼 미정의 TR
                if self.on_execution and tr_id in (
                    TR_ID_EXECUTION_NOTICE, TR_ID_EXECUTION_NOTICE_PAPER
                ):
                    await self.on_execution(tr_id, "", {"raw": data_str})

        else:
            # 시스템 메시지 (JSON)
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                return

            header = msg.get("header", {})
            tr_id = header.get("tr_id", "")

            # PINGPONG 응답
            if tr_id == "PINGPONG":
                if self._ws:
                    await self._ws.pong(raw)
                    logger.debug("PINGPONG 응답 전송")
                return

            # 구독 응답 처리
            body = msg.get("body", {})
            rt_cd = body.get("rt_cd", "")
            msg1 = body.get("msg1", "")

            if rt_cd == "0":
                # 구독 성공 - 암호화 키 저장
                output = body.get("output", {})
                if output:
                    self._encrypt_keys[tr_id] = {
                        "encrypt": header.get("encrypt", "N"),
                        "key": output.get("key", ""),
                        "iv": output.get("iv", ""),
                    }
                logger.info(
                    "구독 응답",
                    extra={
                        "event": "ws_subscribe_response",
                        "tr_id": tr_id,
                        "message": msg1,
                    },
                )
            else:
                logger.warning(
                    "구독 실패",
                    extra={
                        "event": "ws_subscribe_failed",
                        "tr_id": tr_id,
                        "rt_cd": rt_cd,
                        "message": msg1,
                    },
                )

    @staticmethod
    def _aes_decrypt(key: str, iv: str, cipher_text: str) -> str:
        """
        AES-CBC-Base64 복호화.

        기존 kis_auth.py의 aes_cbc_base64_dec 패턴 참조.
        """
        if not key or not iv:
            return cipher_text

        cipher = AES.new(
            key.encode("utf-8"),
            AES.MODE_CBC,
            iv.encode("utf-8"),
        )
        decrypted = unpad(
            cipher.decrypt(b64decode(cipher_text)),
            AES.block_size,
        )
        return decrypted.decode("utf-8")

    def get_status(self) -> dict:
        """WebSocket 상태 요약."""
        return {
            "connected": self._is_connected,
            "running": self._is_running,
            "retry_count": self._retry_count,
            "subscription_count": self.subscription_count,
            "subscriptions": {
                tr_id: list(syms) for tr_id, syms in self._subscriptions.items()
            },
        }
