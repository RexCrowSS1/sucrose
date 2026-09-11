from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

import aiohttp

import bot
from varah.config import Settings


class StartupTests(unittest.TestCase):
    def test_missing_or_example_token_rejected(self):
        for token in ("", "isi_token_bot_di_sini"):
            with self.assertRaisesRegex(ValueError, "DISCORD_TOKEN"):
                Settings(token=token).require_token()

    def test_network_failure_prints_actionable_message_without_traceback(self):
        def fail(coroutine):
            coroutine.close()
            raise aiohttp.ClientConnectionError()
        output = StringIO()
        with patch("sys.argv", ["bot.py"]), patch("bot.asyncio.run", side_effect=fail), redirect_stdout(output):
            self.assertEqual(bot.main(), 1)
        self.assertIn("Periksa koneksi internet", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
