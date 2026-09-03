import os
from unittest import TestCase
from unittest.mock import patch

from participant_runner.config import ConfigurationError, RunnerConfig


class RunnerConfigTests(TestCase):
    def test_reads_strategy_filter(self) -> None:
        with patch.dict(
            os.environ,
            {"TRADER_STRATEGIES": "momentum,liquidity_provider"},
            clear=True,
        ):
            config = RunnerConfig.from_environment()

        self.assertEqual(
            config.trader_strategies,
            ("momentum", "liquidity_provider"),
        )

    def test_rejects_unsupported_strategy_filter(self) -> None:
        with patch.dict(os.environ, {"TRADER_STRATEGIES": "unknown"}, clear=True):
            with self.assertRaisesRegex(
                ConfigurationError,
                "unsupported TRADER_STRATEGIES: unknown",
            ):
                RunnerConfig.from_environment()
