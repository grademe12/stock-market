import os
from unittest import TestCase
from unittest.mock import patch

from participant_runner.config import (
    HTTP_CONCURRENCY_DEFAULT,
    ConfigurationError,
    RunnerConfig,
)


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

    def test_reads_http_concurrency_cap(self) -> None:
        with patch.dict(os.environ, {"HTTP_CONCURRENCY": "32"}, clear=True):
            config = RunnerConfig.from_environment()

        self.assertEqual(config.http_concurrency, 32)

    def test_http_concurrency_defaults_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = RunnerConfig.from_environment()

        self.assertEqual(config.http_concurrency, HTTP_CONCURRENCY_DEFAULT)
        self.assertEqual(config.backend_shard_urls, ("http://127.0.0.1:8000",))

    def test_reads_backend_shard_urls(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BACKEND_BASE_URL": "http://127.0.0.1:8000",
                "BACKEND_SHARD_URLS": "http://backend:8000, http://backend-1:8000",
            },
            clear=True,
        ):
            config = RunnerConfig.from_environment()

        self.assertEqual(
            config.backend_shard_urls,
            ("http://backend:8000", "http://backend-1:8000"),
        )

    def test_rejects_http_concurrency_outside_range(self) -> None:
        with patch.dict(os.environ, {"HTTP_CONCURRENCY": "0"}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "HTTP_CONCURRENCY"):
                RunnerConfig.from_environment()
        with patch.dict(os.environ, {"HTTP_CONCURRENCY": "65"}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "HTTP_CONCURRENCY"):
                RunnerConfig.from_environment()

    def test_reads_runner_shard_index(self) -> None:
        with patch.dict(os.environ, {"RUNNER_SHARD_INDEX": "0"}, clear=True):
            config = RunnerConfig.from_environment()

        self.assertEqual(config.runner_shard_index, 0)

    def test_runner_shard_index_defaults_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = RunnerConfig.from_environment()

        self.assertIsNone(config.runner_shard_index)

    def test_rejects_negative_runner_shard_index(self) -> None:
        with patch.dict(os.environ, {"RUNNER_SHARD_INDEX": "-1"}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "RUNNER_SHARD_INDEX"):
                RunnerConfig.from_environment()

    def test_rejects_unsupported_strategy_filter(self) -> None:
        with patch.dict(os.environ, {"TRADER_STRATEGIES": "unknown"}, clear=True):
            with self.assertRaisesRegex(
                ConfigurationError,
                "unsupported TRADER_STRATEGIES: unknown",
            ):
                RunnerConfig.from_environment()
