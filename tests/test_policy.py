"""Run with: python -m unittest discover -s tests."""
import importlib.util
import pathlib
import unittest
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("policy", ROOT / "custom_components/heating_center/policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

class HeatingPolicyTests(unittest.TestCase):
    def test_invalid_temperature(self):
        for v in (None, "unavailable", float("nan"), -273, 400):
            self.assertIsNone(policy.valid_temp(v))
        self.assertEqual(policy.valid_temp("20.3"), 20.3)

    def test_device_change_is_detected(self):
        self.assertTrue(policy.needs_restore(27, 20))
        self.assertFalse(policy.needs_restore(20.1, 20))
        self.assertFalse(policy.needs_restore("unavailable", 20))

    def test_lock_states(self):
        self.assertTrue(policy.is_locked("LOCK"))
        self.assertTrue(policy.is_locked("on"))
        self.assertFalse(policy.is_locked("UNLOCK"))

    def test_schedule_switch_and_previous_day(self):
        schedule={"0":[{"time":"06:00","temp":20},{"time":"22:00","temp":17}],
                  "6":[{"time":"23:00","temp":16}]}
        mon = datetime(2026,11,2,5,0)
        self.assertEqual(policy.schedule_target(schedule, mon, 19), 16)
        self.assertEqual(policy.schedule_target(schedule, datetime(2026,11,2,8,0), 19), 20)
        self.assertEqual(policy.schedule_target(schedule, datetime(2026,11,2,23,0), 19), 17)

    def test_next_change(self):
        sch={"0":[{"time":"06:00","temp":20},{"time":"22:00","temp":17}],"1":[{"time":"08:00","temp":20}]}
        self.assertEqual(policy.next_schedule_change(sch, datetime(2026,11,2,10)).hour,22)
        self.assertEqual(policy.next_schedule_change(sch, datetime(2026,11,2,23)).day,3)

    def test_priority_frost_window_vacation_override_schedule(self):
        now = datetime(2026,11,2,8)
        room={"target":19,"schedule_enabled":True,"schedule":{"0":[{"time":"06:00","temp":20}]},
              "override_temp":23,"override_until":(now+timedelta(hours=1)).isoformat()}
        self.assertEqual(policy.room_target(room,"home",now),23)
        self.assertEqual(policy.room_target(room,"away",now),16)
        self.assertEqual(policy.room_target(room,"vacation",now),12)
        room["window_open"] = True
        self.assertEqual(policy.room_target(room,"home",now),12)

if __name__ == "__main__": unittest.main()
