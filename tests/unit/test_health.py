import unittest

from brandpilot.health import HealthService


class HealthServiceTests(unittest.TestCase):
    def test_component_failures_are_visible_and_degraded(self):
        def database_failure():
            raise ConnectionError("database unavailable")

        report = HealthService(database_failure, lambda: None).ready()
        self.assertEqual(report.status, "degraded")
        self.assertEqual(report.components["database"]["status"], "failed")
        self.assertEqual(report.components["storage"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
