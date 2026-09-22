import argparse
from dataclasses import asdict
import logging
from pathlib import Path
import signal
from threading import Event

from exchange.market_session import MarketSession

from participant_runner.client import BackendApiClient, BackendApiError
from participant_runner.config import ConfigurationError, RunnerConfig
from participant_runner.coordinator import EventCoordinator
from participant_runner.metrics import MetricsServer, render_metrics
from participant_runner.profiles import InvalidTraderProfileError, build_participants
from participant_runner.runner import ParticipantRunner, run_until_stopped
from participant_runner.scenario import InvalidScenarioError, load_scenario


def main() -> int:
    parser = argparse.ArgumentParser(description="Run external simulated market participants")
    parser.add_argument("--once", action="store_true", help="execute one tick and exit")
    parser.add_argument(
        "--scenario",
        type=Path,
        help="JSON fixture of news shock events applied to event_reactive traders",
    )
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        config = RunnerConfig.from_environment()
        client = BackendApiClient(config.backend_base_url, config.request_timeout_ms)
        symbol_shards: dict[str, int] = {}
        if config.runner_shard_index is not None:
            symbol_shards = client.fetch_matcher_shards()
        participants = build_participants(
            client.fetch_trader_profiles(),
            trader_ids=config.trader_ids,
            trader_strategies=config.trader_strategies,
            max_traders=config.max_traders,
            runner_shard_index=config.runner_shard_index,
            symbol_shards=symbol_shards,
            tick_interval_ms=config.tick_interval_ms,
        )
        coordinator = _build_coordinator(arguments.scenario, config, participants)
    except (
        BackendApiError,
        ConfigurationError,
        InvalidTraderProfileError,
        InvalidScenarioError,
    ) as exc:
        logging.error("runner startup failed: %s", exc)
        return 1

    symbols = sorted({participant.symbol for participant in participants})
    logging.info(
        "loaded %s participant(s) http_concurrency=%s backend=%s "
        "market_mode=%s runner_shard=%s symbols=%s",
        len(participants),
        config.http_concurrency,
        config.backend_base_url,
        config.simulation_market_mode,
        config.runner_shard_index if config.runner_shard_index is not None else "all",
        ",".join(symbols) or "-",
    )
    runner = ParticipantRunner(
        client,
        participants,
        coordinator=coordinator,
        http_concurrency=config.http_concurrency,
    )
    metrics_server = _start_metrics(config, runner)
    market_session = MarketSession(config.simulation_market_mode)
    if arguments.once:
        if not market_session.is_open():
            logging.info(
                "runner once skipped: market is closed; next_open=%s",
                market_session.next_open().isoformat(),
            )
            try:
                logging.info("runner status: %s", asdict(runner.status()))
            finally:
                if metrics_server is not None:
                    metrics_server.stop()
                runner.close()
            return 0

        runner.tick_once()
        try:
            logging.info("runner status: %s", asdict(runner.cancel_all_open_orders()))
        finally:
            if metrics_server is not None:
                metrics_server.stop()
            runner.close()
        return 0

    stop_event = Event()
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    logging.info("runner started; press Ctrl+C to stop")
    try:
        logging.info(
            "runner stopped: %s",
            asdict(
                run_until_stopped(
                    runner,
                    config.tick_interval_ms,
                    config.status_log_interval_ticks,
                    stop_event,
                    market_session=market_session,
                )
            ),
        )
    finally:
        if metrics_server is not None:
            metrics_server.stop()
    return 0


def _build_coordinator(
    scenario_argument: Path | None,
    config: RunnerConfig,
    participants,
) -> EventCoordinator | None:
    scenario_path = scenario_argument or config.scenario_path
    if scenario_path is None:
        return None

    events = load_scenario(scenario_path)
    logging.info("loaded scenario %s events=%s", scenario_path, len(events))
    return EventCoordinator(
        events,
        participants,
        tick_interval_ms=config.tick_interval_ms,
    )


def _start_metrics(config: RunnerConfig, runner: ParticipantRunner) -> MetricsServer | None:
    if not config.metrics_port:
        return None
    strategy = ",".join(config.trader_strategies) or "all"
    shard = (
        str(config.runner_shard_index)
        if config.runner_shard_index is not None
        else "all"
    )

    def render() -> str:
        status = runner.status()
        return render_metrics(
            strategy=strategy,
            shard=shard,
            http_in_flight=status.http_in_flight,
            orders_submitted_total=status.orders_submitted_total,
            events_received_total=status.events_received_total,
            events_deduplicated_total=status.events_deduplicated_total,
            event_trader_pool_size=status.dormant_traders_total,
            activated_traders_total=status.activated_traders_total,
            reactions_planned_total=status.reactions_planned_total,
            reactions_submitted_total=status.reactions_submitted_total,
            reactions_dropped_total=status.reactions_dropped_total,
            scheduler_lag_max_ms=status.scheduler_lag_max_ms,
        )

    server = MetricsServer(config.metrics_bind, config.metrics_port, render)
    server.start()
    logging.info(
        "runner metrics listening on %s:%s",
        config.metrics_bind,
        server.port,
    )
    return server


if __name__ == "__main__":
    raise SystemExit(main())
