import argparse
from dataclasses import asdict
import logging
import signal
from threading import Event

from participant_runner.client import BackendApiClient
from participant_runner.config import ConfigurationError, RunnerConfig
from participant_runner.profiles import InvalidTraderProfileError, build_participants
from participant_runner.runner import ParticipantRunner, run_until_stopped


def main() -> int:
    parser = argparse.ArgumentParser(description="Run external simulated market participants")
    parser.add_argument("--once", action="store_true", help="execute one tick and exit")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        config = RunnerConfig.from_environment()
        client = BackendApiClient(config.backend_base_url, config.request_timeout_ms)
        participants = build_participants(
            client.fetch_trader_profiles(),
            trader_ids=config.trader_ids,
            max_traders=config.max_traders,
        )
    except (BackendApiError, ConfigurationError, InvalidTraderProfileError) as exc:
        logging.error("runner startup failed: %s", exc)
        return 1

    logging.info("loaded %s participant(s)", len(participants))
    runner = ParticipantRunner(client, participants)
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
        asdict(run_until_stopped(runner, config.tick_interval_ms, stop_event)),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
