from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cogames"))

spec = importlib.util.spec_from_file_location(
    "guided_bot_coworld_policy_player",
    ROOT / "coworld" / "policy_player.py",
)
assert spec is not None and spec.loader is not None
policy_player = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = policy_player
spec.loader.exec_module(policy_player)


class PolicyPlayerHelpersTest(unittest.TestCase):
    def test_normalize_colon_args_accepts_bitworld_runner_style(self) -> None:
        self.assertEqual(
            policy_player.normalize_colon_args(
                [
                    "--address:host.docker.internal",
                    "--port:2000",
                    "--name:guided_bot-t1",
                    "--slot:3",
                    "--token:s3cr3t",
                ]
            ),
            [
                "--address=host.docker.internal",
                "--port=2000",
                "--name=guided_bot-t1",
                "--slot=3",
                "--token=s3cr3t",
            ],
        )

    def test_bitscreen_url_adds_missing_path_and_join_params(self) -> None:
        url = policy_player.bitscreen_connect_url(
            address="ignored",
            port=1234,
            name="guided bot",
            token="tok",
            slot=2,
            url="ws://engine:8080",
        )
        self.assertEqual(
            url,
            "ws://engine:8080/player?name=guided+bot&slot=2&token=tok",
        )

    def test_bitscreen_url_preserves_runner_supplied_query(self) -> None:
        url = policy_player.bitscreen_connect_url(
            address="ignored",
            port=1234,
            name="guided",
            token="local",
            slot=7,
            url="ws://game:8080/player?slot=4&token=runner",
        )
        self.assertEqual(
            url,
            "ws://game:8080/player?slot=4&token=runner&name=guided",
        )
        self.assertEqual(policy_player.slot_from_url(url), 4)

    def test_unpack_bitscreen_frame_uses_low_nibble_first(self) -> None:
        frame = policy_player.unpack_bitscreen_frame(bytes([0x21]) * 8192)
        self.assertEqual(frame.shape, (128, 128))
        self.assertEqual(int(frame[0, 0]), 1)
        self.assertEqual(int(frame[0, 1]), 2)


if __name__ == "__main__":
    unittest.main()
