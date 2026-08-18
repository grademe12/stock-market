from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from exchange.participants import DirectionHint, EventPreset, NewsShockEvent


class InvalidScenarioError(ValueError):
    pass


def load_scenario(path: Path) -> tuple[NewsShockEvent, ...]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidScenarioError(f"scenario file could not be read: {path}") from exc

    try:
        raw = json.loads(raw_text)
    except ValueError as exc:
        raise InvalidScenarioError("scenario file must contain valid JSON") from exc
    return parse_scenario(raw)


def parse_scenario(raw: Any) -> tuple[NewsShockEvent, ...]:
    if not isinstance(raw, Mapping) or "events" not in raw:
        raise InvalidScenarioError("scenario must be an object with an events list")

    events = raw["events"]
    if not isinstance(events, list) or not events:
        raise InvalidScenarioError("events must be a non-empty list")

    parsed: list[NewsShockEvent] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(events):
        event = _parse_event(index, item)
        if event.event_id in seen_ids:
            raise InvalidScenarioError(f"duplicate event_id: {event.event_id}")
        seen_ids.add(event.event_id)
        parsed.append(event)
    return tuple(parsed)


def _parse_event(index: int, item: Any) -> NewsShockEvent:
    if not isinstance(item, Mapping):
        raise InvalidScenarioError(f"events[{index}] must be an object")

    missing = [
        field
        for field in ("event_id", "symbol", "starts_after_ms", "preset")
        if field not in item
    ]
    if missing:
        raise InvalidScenarioError(
            f"events[{index}] is missing required fields: {', '.join(missing)}"
        )

    try:
        preset = EventPreset(item["preset"])
        direction_hint = DirectionHint(item.get("direction_hint", DirectionHint.NONE))
        return NewsShockEvent(
            event_id=str(item["event_id"]),
            symbol=str(item["symbol"]),
            starts_after_ms=item["starts_after_ms"],
            preset=preset,
            direction_hint=direction_hint,
            label=str(item.get("label", "")),
            source=str(item.get("source", "fixture")),
            seed=item.get("seed", 42),
        )
    except ValueError as exc:
        raise InvalidScenarioError(f"events[{index}] is invalid: {exc}") from exc
