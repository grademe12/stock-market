import argparse
from dataclasses import asdict
import logging
from pathlib import Path
import signal
from threading import Event

from participant_runner.client import BackendApiClient, BackendApiError
from participant_runner.config import ConfigurationError, RunnerConfig
from participant_runner.coordinator import EventCoordinator
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
        participants = build_participants(
            client.fetch_trader_profiles(),
            trader_ids=config.trader_ids,
            trader_strategies=config.trader_strategies,
            max_traders=config.max_traders,
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

    logging.info(
        "loaded %s participant(s) http_concurrency=%s",
        len(participants),
        config.http_concurrency,
    )
    runner = ParticipantRunner(
        client,
        participants,
        coordinator=coordinator,
        http_concurrency=config.http_concurrency,
    )
    if arguments.once:
        runner.tick_once()
        logging.info("runner status: %s", asdict(runner.cancel_all_open_orders()))
        return 0

    stop_event = Event()
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    logging.info("runner started; press Ctrl+C to stop")
    logging.info(
        "runner stopped: %s",
        asdict(
            run_until_stopped(
                runner,
                config.tick_interval_ms,
                config.status_log_interval_ticks,
                stop_event,
            )
        ),
    )
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


if __name__ == "__main__":
    raise SystemExit(main())
