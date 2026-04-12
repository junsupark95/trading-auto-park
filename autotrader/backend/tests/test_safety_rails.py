# -*- coding: utf-8 -*-
"""안전 레일 테스트."""

import pytest
from decimal import Decimal

from backend.risk.safety_rails import (
    LiveTradingDisabledError,
    SafetyRailViolationError,
    validate_mode_separation,
    validate_not_averaging_down,
    validate_overnight_hold_forbidden,
)
from backend.risk.emergency import EmergencyStopManager
from backend.config.strategy_config import SAFETY_RAILS, AggressiveProfileConfig


class TestSafetyRails:
    """불변 안전 레일 테스트."""

    def test_no_averaging_down(self):
        """물타기 금지."""
        # 정상: 추가매수가 > 평균가
        assert validate_not_averaging_down(50000, 100, 51000)

        # 물타기 시도: 추가매수가 < 평균가
        with pytest.raises(SafetyRailViolationError, match="물타기"):
            validate_not_averaging_down(50000, 100, 49000)

    def test_mode_separation(self):
        """paper/live 모드 분리."""
        assert validate_mode_separation("paper", "paper")
        assert validate_mode_separation("live", "live")

        with pytest.raises(SafetyRailViolationError, match="모드 불일치"):
            validate_mode_separation("paper", "live")

    def test_overnight_hold_forbidden(self):
        """오버나이트 보유 금지."""
        assert validate_overnight_hold_forbidden(False, True)
        assert validate_overnight_hold_forbidden(False, False)
        assert validate_overnight_hold_forbidden(True, False)

        # 장 마감 시 포지션 보유 → 경고
        assert not validate_overnight_hold_forbidden(True, True)


class TestEmergencyStop:
    """긴급 정지 테스트."""

    def test_activate_deactivate(self, emergency_stop):
        """활성화/비활성화."""
        assert not emergency_stop.is_active

        emergency_stop.activate("테스트 정지")
        assert emergency_stop.is_active
        assert emergency_stop.reason == "테스트 정지"

        emergency_stop.deactivate("테스트 해제")
        assert not emergency_stop.is_active

    def test_double_activate(self, emergency_stop):
        """이중 활성화 안전."""
        emergency_stop.activate("첫번째")
        emergency_stop.activate("두번째")  # 무시됨
        assert emergency_stop.reason == "첫번째"

    def test_history(self, emergency_stop):
        """이력 추적."""
        emergency_stop.activate("정지")
        emergency_stop.deactivate("해제")
        history = emergency_stop.get_history()
        assert len(history) == 2
        assert history[0]["action"] == "ACTIVATE"
        assert history[1]["action"] == "DEACTIVATE"


class TestSafetyRailsConfig:
    """안전 레일 설정 검증 테스트."""

    def test_config_within_hard_cap(self):
        """설정이 하드 캡 이내."""
        config = AggressiveProfileConfig()
        violations = SAFETY_RAILS.validate_against_config(config)
        assert len(violations) == 0

    def test_config_exceeds_hard_cap(self):
        """설정이 하드 캡 초과 시 경고."""
        config = AggressiveProfileConfig(max_positions=10)
        violations = SAFETY_RAILS.validate_against_config(config)
        assert len(violations) > 0
