"""Tests for offline voice guidance engine."""

import unittest
from voice import VoiceGuidance


class VoiceGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.voice = VoiceGuidance(mode="mock", cooldown_s=1.0)

    def tearDown(self):
        self.voice.close()

    def test_speak_records_history(self):
        lat = self.voice.speak("PathAble ready")
        self.assertGreaterEqual(lat, 0.0)
        self.assertLess(lat, 300.0)  # Must be well within the 300 ms budget
        self.assertEqual(self.voice.get_last_spoken(), "PathAble ready")
        self.assertEqual(len(self.voice.get_history()), 1)
        self.assertEqual(self.voice.get_history()[0].latency_scope, "queue_dispatch")
        self.assertIsNone(self.voice.get_history()[0].audible_start_latency_ms)

    def test_debouncing_prevents_spamming(self):
        # First speak
        self.voice.speak("Obstacle ahead. Step slightly right.", now=10.0)
        # Duplicate within cooldown (10.2s < 10.0s + 1.0s)
        self.voice.speak("Obstacle ahead. Step slightly right.", now=10.2)
        self.assertEqual(len(self.voice.get_history()), 1)

        # Different message speaks immediately
        self.voice.speak("Please wait.", now=10.3)
        self.assertEqual(len(self.voice.get_history()), 2)

        # After cooldown expired (11.5s > 10.3s + 1.0s)
        self.voice.speak("Obstacle ahead. Step slightly right.", now=11.5)
        self.assertEqual(len(self.voice.get_history()), 3)

    def test_force_bypasses_cooldown(self):
        self.voice.speak("Please wait.", now=1.0)
        self.voice.speak("Please wait.", force=True, now=1.1)
        self.assertEqual(len(self.voice.get_history()), 2)

    def test_empty_string_ignored(self):
        self.voice.speak("")
        self.voice.speak("   ")
        self.assertEqual(len(self.voice.get_history()), 0)

    def test_mock_playback_is_reported_as_simulated(self):
        self.voice.speak('Route replay test')
        self.voice.wait_until_done()
        status = self.voice.get_playback_status()
        self.assertEqual(status['state'], 'simulated')
        self.assertEqual(status['mode'], 'mock')
        self.assertEqual(status['text'], 'Route replay test')


if __name__ == "__main__":
    unittest.main()
