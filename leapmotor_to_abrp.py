#!/usr/bin/env python3
"""Forward validated, fresh EU vehicle telemetry to ABRP."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import requests

from telemetry import build_payload, checked_body

ABRP_URL = "https://api.iternio.com/1/tlm/send"
ABRP_API_KEY = "7310445a-0947-4adc-82f5-29bb882c5926"
ROOT = Path(__file__).resolve().parent


class ConfigurationError(RuntimeError):
    """Actionable configuration errors containing no private data."""


def run_client(command, env, vin=None):
    cmd = [sys.executable, str(ROOT / "leapmotor_client.py"),
           "--cert-file", str(ROOT / "custom_components/leapmotor/app_cert.pem"),
           "--key-file", str(ROOT / "custom_components/leapmotor/app_key.pem"), command]
    if vin:
        cmd.extend(["--vin", vin])
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=180)
    if result.returncode:
        # The diagnostic client may print credentials in errors: never relay them.
        raise RuntimeError("Leapmotor client failed")
    return json.loads(result.stdout)


def detect_vin(env):
    result = run_client("direct-login-vehicle-list", env)
    data = checked_body(result["vehicle_list"])["data"]
    vins = {str(car["vin"]) for bucket in ("bindcars", "sharedcars")
            for car in data.get(bucket, []) or [] if car.get("vin")}
    if len(vins) != 1:
        raise ConfigurationError("Set LEAPMOTOR_VIN/--vin explicitly: account must have exactly one vehicle for auto-detection")
    return vins.pop()


def state_path(directory, vin):
    return Path(directory) / (hashlib.sha256(vin.encode()).hexdigest() + ".json")


def load_state(path, token):
    try:
        state = json.loads(path.read_text())
    except FileNotFoundError:
        state = {}
    token_id = hashlib.sha256(token.encode()).hexdigest()
    if state.get("token_id") != token_id:
        state.pop("last_utc", None)
    state["token_id"] = token_id
    return state


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".telemetry-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(state, stream)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def sync_once(vin, token, env, directory, max_age):
    result = run_client("direct-login-vehicle-summary", env, vin)
    data = checked_body(result["requests"]["vehicle_status"])["data"]
    path = state_path(directory, vin)
    state = load_state(path, token)
    try:
        payload, next_state = build_payload(data, state, now=time.time(), max_age=max_age)
    except ValueError as error:
        print(f"Skipping telemetry: {error}", flush=True)
        return False
    response = requests.post(ABRP_URL,
        headers={"Authorization": f"APIKEY {ABRP_API_KEY}"},
        params={"token": token, "tlm": json.dumps(payload)}, timeout=15)
    if response.status_code != 200:
        raise RuntimeError(f"ABRP HTTP {response.status_code}")
    # ABRP may report an application error with HTTP 200.
    if response.json().get("status") != "ok":
        raise RuntimeError("ABRP rejected telemetry")
    save_state(path, next_state)
    print(f"Successfully pushed to ABRP: SoC {payload['soc']}%", flush=True)
    return True


def positive_int(raw):
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vin", default=os.getenv("LEAPMOTOR_VIN"))
    parser.add_argument("--abrp-token", default=os.getenv("ABRP_TOKEN"))
    parser.add_argument("--username", default=os.getenv("LEAPMOTOR_USERNAME"))
    parser.add_argument("--password", default=os.getenv("LEAPMOTOR_PASSWORD"))
    parser.add_argument("--interval", type=positive_int, default=os.getenv("SYNC_INTERVAL", "300"))
    parser.add_argument("--max-age", type=positive_int, default=os.getenv("MAX_TELEMETRY_AGE", "900"))
    parser.add_argument("--state-dir", default=os.getenv("TELEMETRY_STATE_DIR", str(ROOT / "state")))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not args.abrp_token:
        parser.error("--abrp-token or ABRP_TOKEN is required")
    env = os.environ.copy()
    for key, value in (("LEAPMOTOR_USERNAME", args.username), ("LEAPMOTOR_PASSWORD", args.password)):
        if value:
            env[key] = value
    vin = args.vin
    while True:
        try:
            vin = vin or detect_vin(env)
            sync_once(vin, args.abrp_token, env, args.state_dir, args.max_age)
        except ConfigurationError as error:
            print(str(error), flush=True)
            return 1
        except Exception as error:
            # HTTP errors can include URLs/tokens; raw client output is sensitive.
            print(f"Sync failed ({type(error).__name__}); check credentials, VIN and service availability", flush=True)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
