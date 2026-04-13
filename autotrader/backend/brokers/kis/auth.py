# -*- coding: utf-8 -*-
"""
한국투자증권 Open API 인증 모듈.

기존 저장소의 kis_auth.py 인증 패턴을 참조하여 클래스 기반으로 재구현합니다.
- access token 발급 및 갱신
- 토큰 만료 자동 처리
- 모의/실전 환경 분기
- 웹소켓 접속키 발급

공식 문서 확인 포인트:
  - 접근토큰 발급: POST /oauth2/tokenP
  - 웹소켓 접속키 발급: POST /oauth2/Approval
  - 토큰 유효기간: 1일 (6시간 이내 재발급 시 기존 토큰 반환)
  - 토큰 발급 시 알림톡 발송됨
"""

import json
import logging
import time
from datetime import datetime
from typing import Optional

import httpx

from backend.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class KISAuth:
    """
    한국투자증권 Open API 인증 관리자.

    토큰 발급, 캐싱, 자동 갱신을 담당합니다.
    기존 kis_auth.py의 전역 상태 패턴 대신 인스턴스 기반으로 관리합니다.

    Attributes:
        access_token: 현재 유효한 접근 토큰.
        ws_approval_key: 웹소켓 접속키.

    Example:
        >>> auth = KISAuth()
        >>> await auth.ensure_token()
        >>> print(auth.access_token[:10])
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._access_token: str = ""
        self._token_expires_at: Optional[datetime] = None
        self._ws_approval_key: str = ""
        self._last_token_request: Optional[datetime] = None
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def access_token(self) -> str:
        """현재 접근 토큰."""
        return self._access_token

    @property
    def ws_approval_key(self) -> str:
        """웹소켓 접속키."""
        return self._ws_approval_key

    @property
    def is_authenticated(self) -> bool:
        """인증 완료 여부."""
        if not self._access_token:
            return False
        if self._token_expires_at and datetime.now() >= self._token_expires_at:
            return False
        return True

    @property
    def base_url(self) -> str:
        """현재 모드의 REST API 기본 URL."""
        return self._settings.active_rest_url

    @property
    def ws_url(self) -> str:
        """현재 모드의 WebSocket URL."""
        return self._settings.active_ws_url

    async def _get_client(self) -> httpx.AsyncClient:
        """HTTP 클라이언트를 반환합니다."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    def invalidate_token(self) -> None:
        """토큰 강제 만료 처리 (API에서 만료 에러 응답 시 호출)."""
        self._access_token = ""
        self._token_expires_at = None
        self._last_token_request = None

    async def ensure_token(self) -> str:
        """
        유효한 접근 토큰을 보장합니다.

        토큰이 없거나 만료되었으면 새로 발급합니다.

        Returns:
            유효한 접근 토큰.

        Raises:
            AuthenticationError: 토큰 발급 실패.
        """
        if self.is_authenticated:
            return self._access_token
        return await self._request_token()

    async def _request_token(self) -> str:
        """
        접근 토큰을 발급합니다.

        공식 문서 기준:
          - URL: {base_url}/oauth2/tokenP
          - Method: POST
          - Body: grant_type, appkey, appsecret

        Returns:
            발급된 접근 토큰.

        Raises:
            AuthenticationError: 발급 실패.
        """
        url = f"{self.base_url}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self._settings.active_app_key,
            "appsecret": self._settings.active_app_secret,
        }
        headers = {
            "Content-Type": "application/json",
        }

        try:
            client = await self._get_client()
            response = await client.post(url, json=body, headers=headers)

            if response.status_code != 200:
                raise AuthenticationError(
                    f"토큰 발급 실패: HTTP {response.status_code} - {response.text}"
                )

            data = response.json()
            self._access_token = data.get("access_token", "")
            expires_str = data.get("access_token_token_expired", "")

            if expires_str:
                self._token_expires_at = datetime.strptime(
                    expires_str, "%Y-%m-%d %H:%M:%S"
                )

            self._last_token_request = datetime.now()

            logger.info(
                "토큰 발급 완료",
                extra={
                    "event": "token_issued",
                    "mode": self._settings.trading_mode.value,
                    "expires_at": expires_str,
                    "token_prefix": self._access_token[:10] + "..." if self._access_token else "",
                },
            )
            return self._access_token

        except httpx.RequestError as e:
            raise AuthenticationError(f"토큰 요청 중 네트워크 오류: {e}") from e

    async def request_ws_approval_key(self) -> str:
        """
        웹소켓 접속키를 발급합니다.

        공식 문서 기준:
          - URL: {base_url}/oauth2/Approval
          - Method: POST
          - Body: grant_type, appkey, secretkey

        Returns:
            발급된 웹소켓 접속키.
        """
        url = f"{self.base_url}/oauth2/Approval"
        body = {
            "grant_type": "client_credentials",
            "appkey": self._settings.active_app_key,
            "secretkey": self._settings.active_app_secret,
        }

        try:
            client = await self._get_client()
            response = await client.post(url, json=body)

            if response.status_code != 200:
                raise AuthenticationError(
                    f"웹소켓 접속키 발급 실패: HTTP {response.status_code}"
                )

            data = response.json()
            self._ws_approval_key = data.get("approval_key", "")

            logger.info(
                "웹소켓 접속키 발급 완료",
                extra={"event": "ws_approval_key_issued"},
            )
            return self._ws_approval_key

        except httpx.RequestError as e:
            raise AuthenticationError(f"웹소켓 키 요청 중 네트워크 오류: {e}") from e

    def get_auth_headers(self) -> dict[str, str]:
        """
        API 호출에 필요한 인증 헤더를 반환합니다.

        Returns:
            인증 헤더 딕셔너리.
        """
        return {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self._access_token}",
            "appkey": self._settings.active_app_key,
            "appsecret": self._settings.active_app_secret,
            "custtype": "P",
        }

    async def close(self) -> None:
        """리소스를 정리합니다."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()


class AuthenticationError(Exception):
    """인증 관련 예외."""
    pass
