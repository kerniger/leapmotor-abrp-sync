"""Synthetic regressions; no cloud credentials or network access."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import leapmotor_to_abrp as bridge
from telemetry import build_payload, fetch_vehicle_status, parse_vehicle_timestamp

NOW = 1_790_121_600


def sample(**signal):
    return {"signal": {"sts": NOW * 1000, "1204": 65, **signal}}


def response(data, status=200, code=0):
    return {"status_code": status, "body": json.dumps({"code": code, "data": data})}


class TelemetryTests(unittest.TestCase):
    def payload(self, data, state=None, now=NOW):
        return build_payload(data, state or {}, now=now)

    def test_hvac_and_lock_are_not_charging_or_parking(self):
        result, _ = self.payload(sample(**{"1939": 1, "1298": 1, "1349": 35}))
        for field in ("is_charging", "is_parked", "ext_temp"):
            self.assertNotIn(field, result)

    def test_driving_and_ready_preclude_charging(self):
        for overrides in ({"1010": 1}, {"1010": 3}, {"1319": 40}, {"1258": 1}, {"1149": 0}, {"1149": 5}):
            with self.subTest(overrides=overrides):
                signal = {"1149": 2, "1178": -20, "1177": 400, "1200": 30, **overrides}
                result, _ = self.payload(sample(**signal))
                self.assertFalse(result["is_charging"])

    def test_charging_cases(self):
        for current, state, remaining, expected in (
            (-20, 2, 30, True), (-2.5, 1, 30, True),
            (0, 2, 30, True), (0, 2, 0, False),
            (0, 4, 30, False), (-1.5, 1, 0, False),
        ):
            with self.subTest(current=current, state=state, remaining=remaining):
                result, _ = self.payload(sample(**{"1178": current, "1177": 400, "1149": state, "1200": remaining}))
                self.assertEqual(result["is_charging"], expected)

    def test_parking_uses_gear_and_speed(self):
        for signal, parked in (({"1010": 0, "1298": 0}, True), ({"1010": 3, "1298": 1}, False), ({"1319": 15}, False)):
            result, _ = self.payload(sample(**signal))
            self.assertEqual(result["is_parked"], parked)

    def test_signed_coordinates_and_restart_memory(self):
        result, state = self.payload(sample(**{"3": -33, "2": -70, "3725": 33, "3724": 70}))
        self.assertEqual((result["lat"], result["lon"]), (-33, -70))
        state = json.loads(json.dumps(state))
        result, state = self.payload(sample(**{"sts": (NOW+1)*1000, "3725": 33.1, "3724": 70.1}), state, NOW+1)
        self.assertEqual((result["lat"], result["lon"]), (-33.1, -70.1))
        result, _ = self.payload(sample(**{"sts": (NOW+2)*1000, "3": 33.2, "2": 70.2}), state, NOW+2)
        self.assertEqual((result["lat"], result["lon"]), (-33.2, -70.2))

    def test_crossing_meridian_is_allowed(self):
        result, _ = self.payload(sample(**{"3": 40, "2": .2}), {"lon_sign": -1})
        self.assertEqual(result["lon"], .2)

    def test_unknown_or_invalid_coordinates_omitted(self):
        for signal in ({"3725": 33, "3724": 70}, {"3": 91, "2": 10}, {"3": "NaN", "2": 10}, {"3": 0, "2": 0}):
            result, _ = self.payload(sample(**signal))
            self.assertNotIn("lat", result)
            self.assertNotIn("lon", result)

    def test_timestamp_formats(self):
        for raw in (NOW, NOW*1000, str(NOW), "2026-09-23T00:00:00Z", "2026-09-23T02:00:00+02:00"):
            self.assertEqual(parse_vehicle_timestamp(raw), NOW)
        self.assertIsNone(parse_vehicle_timestamp("2026-09-23T00:00:00"))

    def test_reject_stale_future_missing_duplicate_and_out_of_order(self):
        for stamp in (None, 0, NOW-901, NOW+61, "NaN"):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                self.payload(sample(sts=stamp))
        for previous in (NOW, NOW+1):
            with self.assertRaises(ValueError):
                self.payload(sample(), {"last_utc": previous})

    def test_soc_validation_preserves_zero(self):
        result, _ = self.payload(sample(**{"1204": 0}))
        self.assertEqual(result["soc"], 0)
        for soc in (None, -1, 101, "NaN", "Infinity"):
            with self.assertRaises(ValueError):
                self.payload(sample(**{"1204": soc}))

    def test_t03_named_status(self):
        result, _ = self.payload({"soc": "50", "collectTimeMs": NOW*1000,
            "collectTime": "invalid", "gearStatus": 0, "totalMileage": 100,
            "batteryCurrent": -20, "batteryVoltage": 350, "chargeState": 2,
            "chargeRemainTime": 30})
        self.assertEqual(result, {"utc": NOW, "soc": 50, "is_parked": True, "is_charging": True, "odometer": 100})

    def test_numeric_signals_take_precedence(self):
        result, _ = self.payload({**sample(), "soc": 20})
        self.assertEqual(result["soc"], 65)


class EndpointTests(unittest.TestCase):
    def fetch(self, model, responses, shared=False):
        client = Mock()
        client.replay_request_curl.side_effect = responses
        cars = {"data": {"sharedcars" if shared else "bindcars": [{"vin": "TEST", "carType": model, "carId": "ID"}]}}
        result = fetch_vehicle_status(client, {}, "TEST", cars)
        return result, client.replay_request_curl.call_args_list

    def test_model_paths(self):
        for model, path in (("T03", "t03"), ("B05", "c10"), ("B10", "c10"), ("B11", "c10"), ("C10", "c10")):
            _, calls = self.fetch(model, [response(sample())])
            self.assertTrue(calls[0].kwargs["path"].endswith("/" + path))

    def test_404_fallback(self):
        _, calls = self.fetch("new", [{"status_code": 404, "body": "not found"}, response(sample())])
        self.assertTrue(calls[1].kwargs["path"].endswith("/c10"))

    def test_non_404_does_not_fallback(self):
        with self.assertRaises(ValueError):
            self.fetch("T03", [response({}, status=500)])

    def test_shared_retry(self):
        _, calls = self.fetch("B10", [response({}), response(sample())], shared=True)
        self.assertEqual(calls[1].kwargs["data"], "vin=TEST&carId=ID")

    def test_api_error_rejected(self):
        with self.assertRaises(ValueError):
            self.fetch("C10", [response(sample(), code=1001)])


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = {"requests": {"vehicle_status": response(sample(**{"3": -33, "2": -70}))}}
        self.client = patch.object(bridge, "run_client", return_value=self.data).start()
        self.post = patch.object(bridge.requests, "post", return_value=Mock(status_code=200, json=lambda: {"status": "ok"})).start()
        patch.object(bridge.time, "time", return_value=NOW).start()
        self.addCleanup(patch.stopall)

    def sync(self, vin="TEST", token="test-token"):
        return bridge.sync_once(vin, token, {}, self.tmp.name, 900)

    def test_success_persists_and_duplicate_skips(self):
        self.assertTrue(self.sync())
        self.assertFalse(self.sync())
        self.post.assert_called_once()
        sent = json.loads(self.post.call_args.kwargs["params"]["tlm"])
        self.assertEqual(sent["utc"], NOW)
        self.assertEqual(sent["lat"], -33)
        state = bridge.load_state(bridge.state_path(self.tmp.name, "TEST"), "test-token")
        self.assertEqual(state["last_utc"], NOW)

    def test_failure_is_retryable(self):
        for status, body in ((500, {"status": "error"}), (200, {"status": "error"})):
            self.post.return_value = Mock(status_code=status, json=lambda: body)
            with self.assertRaises(RuntimeError):
                self.sync()
            self.assertFalse(bridge.state_path(self.tmp.name, "TEST").exists())
        self.post.return_value = Mock(status_code=200, json=lambda: {"status": "ok"})
        self.assertTrue(self.sync())

    def test_stale_does_not_send(self):
        self.data["requests"]["vehicle_status"] = response(sample(sts=NOW-901))
        self.assertFalse(self.sync())
        self.post.assert_not_called()

    def test_vin_and_token_isolation(self):
        self.sync()
        self.sync(vin="OTHER")
        self.sync(token="replacement-token")
        self.assertEqual(self.post.call_count, 3)
        self.assertEqual(len(list(Path(self.tmp.name).glob("*.json"))), 2)

    def test_ambiguous_vehicle_selection(self):
        self.client.return_value = {"vehicle_list": response({"bindcars": [{"vin": "A"}, {"vin": "B"}]})}
        with self.assertRaisesRegex(RuntimeError, "LEAPMOTOR_VIN"):
            bridge.detect_vin({})

    def test_secrets_not_in_error_logs(self):
        with patch.object(bridge, "sync_once", side_effect=RuntimeError("SECRET")), patch.object(bridge.sys, "argv", ["bridge", "--once", "--vin", "TEST", "--abrp-token", "test-token"]):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(bridge.main(), 1)
            self.assertNotIn("SECRET", output.getvalue())


class ClientBoundaryTests(unittest.TestCase):
    def test_credentials_only_in_child_environment(self):
        env = {"LEAPMOTOR_USERNAME": "synthetic-user", "LEAPMOTOR_PASSWORD": "synthetic-password"}
        with patch.object(bridge.subprocess, "run", return_value=Mock(returncode=0, stdout='{}')) as run:
            bridge.run_client("direct-login-vehicle-summary", env, "TEST")
        self.assertEqual(run.call_args.kwargs["env"], env)
        self.assertNotIn("synthetic-password", run.call_args.args[0])
        self.assertNotIn("synthetic-user", run.call_args.args[0])

    def test_client_summary_matches_new_mapping(self):
        from leapmotor_client import normalize_vehicle_summary
        result = normalize_vehicle_summary(vin="TEST", user_id="TEST", list_json={}, picture_json={},
            status_json={"data": {"soc": 42, "gearStatus": 0,
                "driverDoorLockStatus": True, "collectTimeMs": NOW*1000,
                "signal": {"3": -33, "2": -70, "1939": 1}}})
        self.assertEqual(result["status"]["battery_percent"], 42)
        self.assertTrue(result["status"]["is_parked"])
        self.assertTrue(result["status"]["is_locked"])
        self.assertFalse(result["charging"]["is_charging"])
        self.assertEqual(result["location"]["longitude"], -70)
