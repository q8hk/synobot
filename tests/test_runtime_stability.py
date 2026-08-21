import threading
import time
import unittest

import BotConfig
from ThreadTimer import ThreadTimer


class InteractiveLoginConfigurationTests(unittest.TestCase):
    def test_dsm_id_can_be_updated_for_interactive_login(self):
        config = BotConfig.BotConfig()

        config.SetDsmId('interactive-user')

        self.assertEqual(config.GetDsmId(), 'interactive-user')


class ThreadTimerTests(unittest.TestCase):
    def test_callback_exception_does_not_stop_future_runs(self):
        second_run = threading.Event()
        calls = []

        def callback():
            calls.append(len(calls) + 1)
            if len(calls) == 1:
                raise RuntimeError('expected test failure')
            second_run.set()

        timer = ThreadTimer(0.01, callback)
        timer.start()
        try:
            self.assertTrue(second_run.wait(0.5))
        finally:
            timer.cancel()

        self.assertGreaterEqual(len(calls), 2)

    def test_cancel_prevents_rescheduling(self):
        first_run = threading.Event()
        calls = []

        def callback():
            calls.append(1)
            first_run.set()

        timer = ThreadTimer(0.01, callback)
        timer.start()
        self.assertTrue(first_run.wait(0.5))
        timer.cancel()
        count_after_cancel = len(calls)

        time.sleep(0.05)

        self.assertEqual(len(calls), count_after_cancel)


if __name__ == '__main__':
    unittest.main()
