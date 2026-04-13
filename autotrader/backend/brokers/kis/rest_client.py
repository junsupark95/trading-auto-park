# -*- coding: utf-8 -*-
"""
한국투자증권 REST API 클라이언트.

rate limit 보호, backoff + 최대 재시도, timeout 처리를 포함합니다.
API 응답을 표준 모델로 매핑합니다.

공식 문서 확인 포인트:
  - 초당 호출 제한: 모의투자 더 낮음
  - TR ID: 실전은 T/J/C 시작, 모의는 V 시작으로 자동 변환
  - 응답 구조: rt_cd=0 성공, msg_cd, msg1
"""

import asyncio
import json
import logging
import time
from typing import Any, Optional

import httpx

from backend.brokers.kis.auth import KISAuth
from backend.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# 재시도 설정
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0
REQUEST_TIMEOUT_SECONDS = 15.0

# Rate limit: 모의투자는 느리게, 실전은 빠르게
RATE_LIMIT_PAPER = 0.5  # 초 (초당 2회)
RATE_LIMIT_LIVE = 0.05  # 초 (초당 20회)


class KISRestClient:
    """
    한국투자증권 REST API 클라이언트.

    rate limit 보호와 자동 재시도를 포함합니다.
    모든 API 호출의 응답을 구조화하여 반환합니다.

    Attributes:
        auth: 인증 관리자.
        error_count: 누적 API 오류 횟수.

    Example:
        >>> client = KISRestClient(auth)
        >>> result = await client.get("/uapi/domestic-stock/v1/quotations/inquire-price",
        ...     tr_id="FHKST01010100", params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "005930"})
    """

    def __init__(
        self,
        auth: KISAuth,
        settings: Optional[Settings] = None,
    ) -> None:
        self._auth = auth
        self._settings = settings or get_settings()
        self._http_client: Optional[httpx.AsyncClient] = None
        self._last_request_time: float = 0
        self._error_count: int = 0

    @property
    def error_count(self) -> int:
        """누적 API 오류 횟수."""
        return self._error_count

    def reset_error_count(self) -> None:
        """오류 카운트를 리셋합니다."""
        self._error_count = 0

    async def _get_client(self) -> httpx.AsyncClient:
        """HTTP 클라이언트를 반환합니다."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_SECONDS,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                ),
            )
        return self._http_client

    async def _rate_limit(self) -> None:
        """rate limit 보호를 위한 지연."""
        delay = RATE_LIMIT_PAPER if self._settings.is_paper else RATE_LIMIT_LIVE
        elapsed = time.time() - self._last_request_time
        if elapsed < delay:
            await asyncio.sleep(delay - elapsed)
        self._last_request_time = time.time()

    def _convert_tr_id(self, tr_id: str) -> str:
        """
        TR ID를 현재 모드에 맞게 변환합니다.

        기존 kis_auth.py 패턴 참조:
        실전은 T/J/C 시작, 모의는 V 시작으로 변환.
        """
        if self._settings.is_paper and tr_id and tr_id[0] in ("T", "J", "C"):
            return "V" + tr_id[1:]
        return tr_id

    async def get(
        self,
        path: str,
        tr_id: str,
        params: Optional[dict[str, Any]] = None,
        tr_cont: str = "",
    ) -> dict[str, Any]:
        """
        GET 요청을 수행합니다.

        Args:
            path: API 경로 (예: /uapi/domestic-stock/v1/quotations/inquire-price).
            tr_id: 트랜잭션 ID.
            params: 쿼리 파라미터.
            tr_cont: 연속 조회 키.

        Returns:
            API 응답 딕셔너리.

        Raises:
            KISApiError: API 오류.
        """
        return await self._request("GET", path, tr_id, params=params, tr_cont=tr_cont)

    async def post(
        self,
        path: str,
        tr_id: str,
        body: Optional[dict[str, Any]] = None,
        tr_cont: str = "",
    ) -> dict[str, Any]:
        """
        POST 요청을 수행합니다.

        Args:
            path: API 경로.
            tr_id: 트랜잭션 ID.
            body: 요청 본문.
            tr_cont: 연속 조회 키.

        Returns:
            API 응답 딕셔너리.
        """
        return await self._request("POST", path, tr_id, body=body, tr_cont=tr_cont)

    async def _request(
        self,
        method: str,
        path: str,
        tr_id: str,
        params: Optional[dict[str, Any]] = None,
        body: Optional[dict[str, Any]] = None,
        tr_cont: str = "",
    ) -> dict[str, Any]:
        """
        API 요청을 수행합니다 (재시도 포함).

        backoff + 최대 재시도 전략:
          - 1차 실패: 1초 대기
          - 2차 실패: 2초 대기
          - 3차 실패: 4초 대기 (최대)
          - 3번 실패 시 예외 발생

        Args:
            method: HTTP 메서드.
            path: API 경로.
            tr_id: 트랜잭션 ID.
            params: 쿼리 파라미터.
            body: 요청 본문.
            tr_cont: 연속 조회 키.

        Returns:
            API 응답 딕셔너리.

        Raises:
            KISApiError: 최대 재시도 후에도 실패.
        """
        await self._auth.ensure_token()

        converted_tr_id = self._convert_tr_id(tr_id)
        url = f"{self._auth.base_url}{path}"
        headers = self._auth.get_auth_headers()
        headers["tr_id"] = converted_tr_id
        headers["tr_cont"] = tr_cont

        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            await self._rate_limit()

            try:
                client = await self._get_client()

                if method == "GET":
                    response = await client.get(url, headers=headers, params=params)
                else:
                    response = await client.post(
                        url, headers=headers, content=json.dumps(body or {})
                    )

                # 응답 본문 파싱 시도 (KIS는 에러 시 500 상태코드와 함께 JSON을 반환하기도 함)
                try:
                    data = response.json()
                except ValueError:
                    data = {}

                rt_cd = data.get("rt_cd", "")
                msg_cd = data.get("msg_cd", data.get("message", ""))
                msg1 = data.get("msg1", "")

                # 1. 정상 응답
                if response.status_code == 200 and rt_cd == "0":
                    self._error_count = max(0, self._error_count - 1)
                    return data

                # 2. 토큰 만료/오류 처리 (EGW00123, EGW00121 등)
                if msg_cd in ("EGW00123", "EGW00121") or "token" in msg1.lower() or "토큰" in msg1:
                    logger.warning("토큰 만료 감지, 강제 재발급 및 재시도 진행")
                    self._auth.invalidate_token()
                    await self._auth.ensure_token()
                    headers["authorization"] = f"Bearer {self._auth.access_token}"
                    continue

                # 3. Rate Limit 초과 처리 (EGW00201)
                if msg_cd == "EGW00201" or "초과" in msg1:
                    backoff = min(
                        INITIAL_BACKOFF_SECONDS * (2 ** attempt),
                        MAX_BACKOFF_SECONDS,
                    )
                    await asyncio.sleep(backoff)
                    continue

                # 4. 기타 비즈니스 오류 로그 기록
                if msg_cd or msg1:
                    logger.warning(
                        "KIS API 오류 파싱됨",
                        extra={
                            "event": "kis_api_error_parsed",
                            "tr_id": converted_tr_id,
                            "msg_cd": msg_cd,
                            "msg1": msg1,
                            "status_code": response.status_code,
                        },
                    )

                # 5. 최대 재시도 및 기타 오류 예외 발생
                if response.status_code == 200:
                    raise KISApiError(
                        f"KIS API 오류: [{msg_cd}] {msg1}",
                        status_code=200,
                        error_code=msg_cd,
                    )
                else:
                    self._error_count += 1
                    raise KISApiError(
                        f"HTTP {response.status_code}: {response.text}",
                        status_code=response.status_code,
                        error_code=msg_cd,
                    )

            except httpx.TimeoutException as e:
                last_error = e
                self._error_count += 1
                logger.warning(
                    f"KIS API 타임아웃 (시도 {attempt + 1}/{MAX_RETRIES})",
                    extra={
                        "event": "kis_api_timeout",
                        "path": path,
                        "tr_id": converted_tr_id,
                        "attempt": attempt + 1,
                    },
                )
            except httpx.RequestError as e:
                last_error = e
                self._error_count += 1
                logger.warning(
                    f"KIS API 네트워크 오류 (시도 {attempt + 1}/{MAX_RETRIES})",
                    extra={
                        "event": "kis_api_network_error",
                        "error": str(e),
                        "attempt": attempt + 1,
                    },
                )
            except KISApiError:
                raise

            # Exponential backoff
            if attempt < MAX_RETRIES - 1:
                backoff = min(
                    INITIAL_BACKOFF_SECONDS * (2 ** attempt),
                    MAX_BACKOFF_SECONDS,
                )
                logger.info(f"재시도 대기: {backoff:.1f}초")
                await asyncio.sleep(backoff)

        # 최대 재시도 실패
        raise KISApiError(
            f"최대 재시도({MAX_RETRIES}회) 후 실패: {path}",
            status_code=0,
            original_error=last_error,
        )

    async def close(self) -> None:
        """리소스를 정리합니다."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()


class KISApiError(Exception):
    """KIS API 호출 오류."""

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        error_code: str = "",
        original_error: Optional[Exception] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.original_error = original_error
