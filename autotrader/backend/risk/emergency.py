# -*- coding: utf-8 -*-
"""
긴급 정지 모듈.

시스템 전역 긴급 거래 정지 기능을 제공합니다.
긴급 정지가 활성화되면 모든 신규 주문이 차단됩니다.
AI는 긴급 정지를 해제할 수 없으며, 수동으로만 해제 가능합니다.
"""

import logging
from datetime import datetime
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)


class EmergencyStopManager:
    """
    긴급 거래 정지 관리자.

    스레드 안전하게 긴급 정지 상태를 관리합니다.
    정지 활성화/비활성화 모든 이력을 기록합니다.

    Attributes:
        is_active: 긴급 정지 활성화 여부.

    Example:
        >>> esm = EmergencyStopManager()
        >>> esm.activate("시장 급변 감지")
        >>> assert esm.is_active
        >>> esm.deactivate("관리자 수동 해제")
    """

    def __init__(self) -> None:
        self._active: bool = False
        self._lock: Lock = Lock()
        self._activated_at: Optional[datetime] = None
        self._activated_reason: str = ""
        self._history: list[dict] = []

    @property
    def is_active(self) -> bool:
        """긴급 정지 활성화 여부."""
        with self._lock:
            return self._active

    @property
    def activated_at(self) -> Optional[datetime]:
        """활성화 시각."""
        return self._activated_at

    @property
    def reason(self) -> str:
        """활성화 사유."""
        return self._activated_reason

    def activate(self, reason: str) -> None:
        """
        긴급 정지를 활성화합니다.

        Args:
            reason: 정지 사유.
        """
        with self._lock:
            if self._active:
                logger.info("긴급 정지 이미 활성화 상태")
                return

            self._active = True
            self._activated_at = datetime.now()
            self._activated_reason = reason

            record = {
                "action": "ACTIVATE",
                "reason": reason,
                "timestamp": self._activated_at.isoformat(),
            }
            self._history.append(record)

            logger.critical(
                "🚨 긴급 거래 정지 활성화",
                extra={
                    "event": "emergency_stop_activated",
                    "reason": reason,
                    "timestamp": self._activated_at.isoformat(),
                },
            )

    def deactivate(self, reason: str = "수동 해제") -> None:
        """
        긴급 정지를 해제합니다.

        AI는 이 함수를 호출할 수 없습니다. 수동으로만 호출 가능합니다.

        Args:
            reason: 해제 사유.
        """
        with self._lock:
            if not self._active:
                logger.info("긴급 정지가 이미 비활성화 상태")
                return

            self._active = False
            deactivated_at = datetime.now()
            duration = (
                (deactivated_at - self._activated_at).total_seconds()
                if self._activated_at
                else 0
            )

            record = {
                "action": "DEACTIVATE",
                "reason": reason,
                "timestamp": deactivated_at.isoformat(),
                "duration_seconds": duration,
            }
            self._history.append(record)

            logger.warning(
                "✅ 긴급 거래 정지 해제",
                extra={
                    "event": "emergency_stop_deactivated",
                    "reason": reason,
                    "duration_seconds": duration,
                },
            )

            self._activated_at = None
            self._activated_reason = ""

    def get_status(self) -> dict:
        """현재 긴급 정지 상태를 반환합니다."""
        return {
            "is_active": self.is_active,
            "activated_at": (
                self._activated_at.isoformat() if self._activated_at else None
            ),
            "reason": self._activated_reason,
            "history_count": len(self._history),
        }

    def get_history(self) -> list[dict]:
        """정지/해제 이력을 반환합니다."""
        return self._history.copy()


# 싱글톤 인스턴스
_emergency_stop: Optional[EmergencyStopManager] = None


def get_emergency_stop() -> EmergencyStopManager:
    """긴급 정지 관리자 인스턴스를 반환합니다."""
    global _emergency_stop
    if _emergency_stop is None:
        _emergency_stop = EmergencyStopManager()
    return _emergency_stop
