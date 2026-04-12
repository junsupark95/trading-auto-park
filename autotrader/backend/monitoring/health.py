# -*- coding: utf-8 -*-
"""
헬스체크 모듈.

API, WebSocket, DB, AI 각 서브시스템의 상태를 확인합니다.
하나라도 비정상이면 리스크 엔진에 API 비정상 컨텍스트를 전달합니다.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class ComponentStatus(str, Enum):
    """서브시스템 상태."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


@dataclass
class ComponentHealth:
    """단일 서브시스템 상태."""
    name: str
    status: ComponentStatus = ComponentStatus.UNKNOWN
    last_check: Optional[datetime] = None
    latency_ms: float = 0.0
    error_message: str = ""
    metadata: dict = field(default_factory=dict)

    def mark_healthy(self, latency_ms: float = 0) -> None:
        """정상 상태로 표시."""
        self.status = ComponentStatus.HEALTHY
        self.last_check = datetime.now()
        self.latency_ms = latency_ms
        self.error_message = ""

    def mark_degraded(self, msg: str, latency_ms: float = 0) -> None:
        """열화 상태로 표시."""
        self.status = ComponentStatus.DEGRADED
        self.last_check = datetime.now()
        self.latency_ms = latency_ms
        self.error_message = msg

    def mark_unhealthy(self, msg: str) -> None:
        """비정상 상태로 표시."""
        self.status = ComponentStatus.UNHEALTHY
        self.last_check = datetime.now()
        self.error_message = msg


class HealthChecker:
    """
    종합 헬스 체크 관리자.

    각 서브시스템의 상태를 추적하고 종합 상태를 판단합니다.

    Example:
        >>> checker = HealthChecker()
        >>> checker.update("REST_API", ComponentStatus.HEALTHY, latency_ms=150)
        >>> checker.update("WebSocket", ComponentStatus.DEGRADED, error="재연결 중")
        >>> print(checker.overall_status)
        ComponentStatus.DEGRADED
    """

    def __init__(self) -> None:
        self._components: dict[str, ComponentHealth] = {
            "REST_API": ComponentHealth(name="REST API"),
            "WebSocket": ComponentHealth(name="WebSocket"),
            "Database": ComponentHealth(name="Database"),
            "AI_Advisor": ComponentHealth(name="AI Advisor"),
        }

    @property
    def overall_status(self) -> ComponentStatus:
        """종합 상태. 하나라도 UNHEALTHY면 UNHEALTHY."""
        statuses = [c.status for c in self._components.values()]
        if ComponentStatus.UNHEALTHY in statuses:
            return ComponentStatus.UNHEALTHY
        if ComponentStatus.DEGRADED in statuses:
            return ComponentStatus.DEGRADED
        if all(s == ComponentStatus.HEALTHY for s in statuses):
            return ComponentStatus.HEALTHY
        return ComponentStatus.UNKNOWN

    @property
    def api_health_string(self) -> str:
        """리스크 엔진 컨텍스트용 상태 문자열."""
        status = self.overall_status
        return status.value

    def update(
        self,
        component: str,
        status: ComponentStatus,
        latency_ms: float = 0,
        error: str = "",
    ) -> None:
        """
        서브시스템 상태를 갱신합니다.

        Args:
            component: 서브시스템 이름.
            status: 상태.
            latency_ms: 응답 시간(ms).
            error: 에러 메시지.
        """
        if component not in self._components:
            self._components[component] = ComponentHealth(name=component)

        comp = self._components[component]
        if status == ComponentStatus.HEALTHY:
            comp.mark_healthy(latency_ms)
        elif status == ComponentStatus.DEGRADED:
            comp.mark_degraded(error, latency_ms)
        elif status == ComponentStatus.UNHEALTHY:
            comp.mark_unhealthy(error)

    def get_full_report(self) -> dict:
        """전체 헬스 리포트."""
        return {
            "overall": self.overall_status.value,
            "timestamp": datetime.now().isoformat(),
            "components": {
                name: {
                    "status": comp.status.value,
                    "last_check": comp.last_check.isoformat() if comp.last_check else None,
                    "latency_ms": comp.latency_ms,
                    "error": comp.error_message,
                }
                for name, comp in self._components.items()
            },
        }
