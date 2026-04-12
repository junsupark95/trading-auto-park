# -*- coding: utf-8 -*-
"""진입/청산 규칙 테스트."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from backend.strategy.entry_rules import EntryRules, OrbData
from backend.strategy.exit_rules import ExitRules


class TestEntryRules:
    """진입 규칙 테스트."""

    def test_gap_filter_pass(self, strategy_config):
        """갭 필터 통과."""
        rules = EntryRules(strategy_config)
        passed, gap = rules.check_gap_filter(Decimal("50000"), Decimal("52000"))
        assert passed
        assert 3.0 <= gap <= 15.0

    def test_gap_filter_too_low(self, strategy_config):
        """갭 너무 낮음."""
        rules = EntryRules(strategy_config)
        passed, gap = rules.check_gap_filter(Decimal("50000"), Decimal("50500"))
        assert not passed

    def test_gap_filter_too_high(self, strategy_config):
        """갭 너무 높음 (상한가 근접)."""
        rules = EntryRules(strategy_config)
        passed, gap = rules.check_gap_filter(Decimal("50000"), Decimal("60000"))
        assert not passed

    def test_volume_filter_pass(self, strategy_config):
        """거래대금 서지 필터 통과."""
        rules = EntryRules(strategy_config)
        passed, ratio = rules.check_volume_filter(20_000_000_000, 5_000_000_000)
        assert passed
        assert ratio >= 3.0

    def test_volume_filter_low_avg(self, strategy_config):
        """평균 거래대금 부족."""
        rules = EntryRules(strategy_config)
        passed, ratio = rules.check_volume_filter(10_000_000_000, 1_000_000_000)
        assert not passed

    def test_orb_breakout(self, strategy_config):
        """ORB 돌파 시그널 생성."""
        rules = EntryRules(strategy_config)
        orb = OrbData(
            symbol="005930",
            orb_high=Decimal("52000"),
            orb_low=Decimal("50000"),
            orb_volume=100000,
            orb_start=datetime(2026, 4, 12, 9, 0),
            orb_end=datetime(2026, 4, 12, 9, 5),
            is_formed=True,
        )
        signal = rules.check_breakout(orb, Decimal("53000"), 200000, 100000)
        assert signal is not None
        assert signal.direction == "BUY"
        assert signal.signal_type == "ORB_BREAKOUT"

    def test_no_breakout_below_high(self, strategy_config):
        """ORB 고가 미달 시 시그널 없음."""
        rules = EntryRules(strategy_config)
        orb = OrbData(
            symbol="005930",
            orb_high=Decimal("52000"),
            orb_low=Decimal("50000"),
            orb_volume=100000,
            orb_start=datetime(2026, 4, 12, 9, 0),
            orb_end=datetime(2026, 4, 12, 9, 5),
            is_formed=True,
        )
        signal = rules.check_breakout(orb, Decimal("51500"), 200000, 100000)
        assert signal is None


class TestExitRules:
    """청산 규칙 테스트."""

    def test_stop_loss_triggers(self, strategy_config):
        """손절 트리거."""
        rules = ExitRules(strategy_config)
        signal = rules.check_stop_loss("005930", Decimal("50000"), Decimal("49200"))
        assert signal is not None
        assert signal.exit_type == "STOP_LOSS"
        assert signal.quantity_ratio == 1.0

    def test_no_stop_loss_within_range(self, strategy_config):
        """손절 범위 이내."""
        rules = ExitRules(strategy_config)
        signal = rules.check_stop_loss("005930", Decimal("50000"), Decimal("49500"))
        assert signal is None

    def test_partial_take_profit(self, strategy_config):
        """부분 익절."""
        rules = ExitRules(strategy_config)
        signal = rules.check_partial_take_profit(
            "005930", Decimal("50000"), Decimal("51100"), partial_exits_done=0
        )
        assert signal is not None
        assert signal.exit_type == "PARTIAL_TAKE_PROFIT"
        assert signal.quantity_ratio == 0.5

    def test_partial_take_profit_once_only(self, strategy_config):
        """부분 익절은 1회만."""
        rules = ExitRules(strategy_config)
        signal = rules.check_partial_take_profit(
            "005930", Decimal("50000"), Decimal("51100"), partial_exits_done=1
        )
        assert signal is None

    def test_trailing_stop(self, strategy_config):
        """트레일링 스탑."""
        rules = ExitRules(strategy_config)
        signal = rules.check_trailing_stop(
            "005930",
            entry_price=Decimal("50000"),
            highest_price=Decimal("52000"),
            current_price=Decimal("51400"),
        )
        assert signal is not None
        assert signal.exit_type == "TRAILING_STOP"

    def test_time_exit(self, strategy_config):
        """시간 청산."""
        rules = ExitRules(strategy_config)
        entry_time = datetime(2026, 4, 12, 9, 10)
        signal = rules.check_time_exit(
            "005930",
            entry_time,
            current_time=datetime(2026, 4, 12, 11, 15),
        )
        assert signal is not None
        assert signal.exit_type == "TIME_EXIT"

    def test_force_close(self, strategy_config):
        """장마감 강제 청산."""
        rules = ExitRules(strategy_config)
        signal = rules.check_force_close(
            "005930",
            current_time=datetime(2026, 4, 12, 15, 21),
        )
        assert signal is not None
        assert signal.exit_type == "FORCE_CLOSE"

    def test_evaluate_all_priority(self, strategy_config):
        """청산 우선순위: 강제청산 > 손절."""
        rules = ExitRules(strategy_config)
        signal = rules.evaluate_all(
            symbol="005930",
            entry_price=Decimal("50000"),
            highest_price=Decimal("50000"),
            current_price=Decimal("48000"),  # 손절 조건도 충족
            entry_time=datetime(2026, 4, 12, 9, 10),
            current_time=datetime(2026, 4, 12, 15, 25),  # 강제청산 시간
        )
        assert signal is not None
        assert signal.exit_type == "FORCE_CLOSE"  # 강제청산이 우선
