from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from exchange.participants import DirectionHint, EventPreset

from participant_runner.scenario import InvalidScenarioError, load_scenario, parse_scenario


class ScenarioLoaderTests(TestCase):
    def valid_payload(self, **overrides):
        event = {
            "event_id": "shock-001",
            "symbol": "005930",
            "starts_after_ms": 30_000,
            "preset": "breaking_news",
            "direction_hint": "MIXED",
            "label": "fixture",
            "source": "fixture",
            "seed": 42,
        }
        event.update(overrides)
        return {"events": [event]}

    def test_parse_scenario_accepts_the_documented_fixture_shape(self) -> None:
        events = parse_scenario(self.valid_payload())

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_id, "shock-001")
        self.assertEqual(events[0].preset, EventPreset.BREAKING_NEWS)
        self.assertEqual(events[0].direction_hint, DirectionHint.MIXED)
        self.assertEqual(events[0].starts_after_ms, 30_000)

    def test_parse_scenario_rejects_duplicates_and_missing_fields(self) -> None:
        with self.assertRaisesRegex(InvalidScenarioError, "duplicate event_id"):
            parse_scenario(
                {
                    "events": [
                        self.valid_payload()["events"][0],
                        self.valid_payload()["events"][0],
                    ]
                }
            )
        with self.assertRaisesRegex(InvalidScenarioError, "missing required fields"):
            parse_scenario({"events": [{"event_id": "shock-001"}]})
        with self.assertRaisesRegex(InvalidScenarioError, "non-empty list"):
            parse_scenario({"events": []})

    def test_load_scenario_reads_json_from_disk(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "breaking_news.json"
            path.write_text(
                '{"events":[{"event_id":"shock-001","symbol":"005930",'
                '"starts_after_ms":0,"preset":"mixed_reaction"}]}',
                encoding="utf-8",
            )

            events = load_scenario(path)

        self.assertEqual(events[0].event_id, "shock-001")
        self.assertEqual(events[0].direction_hint, DirectionHint.NONE)
        self.assertEqual(events[0].seed, 42)

    def test_bundled_breaking_news_fixture_loads(self) -> None:
        events = load_scenario(
            Path(__file__).resolve().parents[1] / "scenarios" / "breaking_news.json"
        )

        self.assertEqual(events[0].event_id, "shock-001")
        self.assertEqual(events[0].starts_after_ms, 30_000)
        self.assertEqual(events[0].preset, EventPreset.BREAKING_NEWS)
