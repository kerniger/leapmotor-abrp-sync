#!/usr/bin/env python3
import subprocess
import json
import time
import requests
import argparse
import sys
import os

ABRP_URL = "https://api.iternio.com/1/tlm/send"

def main():
    parser = argparse.ArgumentParser(description="Push Leapmotor telemetry to ABRP")
    parser.add_argument("--vin", required=False, help="Vehicle VIN (optional, auto-detected if not provided)")
    parser.add_argument("--abrp-token", required=True, help="ABRP User Token")
    parser.add_argument("--username", help="Leapmotor username (or use LEAPMOTOR_USERNAME env var)")
    parser.add_argument("--password", help="Leapmotor password (or use LEAPMOTOR_PASSWORD env var)")
    parser.add_argument("--interval", type=int, default=300, help="Interval in seconds (default 300)")
    parser.add_argument("--once", action="store_true", help="Run only once and exit (for cron/GitHub Actions)")
    args = parser.parse_args()

    username = args.username or os.environ.get("LEAPMOTOR_USERNAME")
    password = args.password or os.environ.get("LEAPMOTOR_PASSWORD")

    vin = args.vin
    if not vin:
        print("Auto-detecting VIN from account...")
        cmd_list = [
            sys.executable,
            "leapmotor_client.py",
            "--cert-file", "custom_components/leapmotor/app_cert.pem",
            "--key-file", "custom_components/leapmotor/app_key.pem",
            "direct-login-vehicle-list"
        ]
        if username:
            cmd_list.extend(["--username", username])
        if password:
            cmd_list.extend(["--password", password])
            
        list_res = subprocess.run(cmd_list, capture_output=True, text=True)
        if list_res.returncode != 0:
            print(f"Error auto-detecting VIN: {list_res.stderr.strip()}")
            sys.exit(1)
            
        try:
            list_data = json.loads(list_res.stdout)
            body_str = list_data.get("vehicle_list", {}).get("body", "{}")
            body_json = json.loads(body_str)
            data_dict = body_json.get("data", {})
            for bucket in ("bindcars", "sharedcars"):
                for car in data_dict.get(bucket, []):
                    if car.get("vin"):
                        vin = car.get("vin")
                        break
                if vin:
                    break
        except Exception as e:
            print(f"Failed to parse VIN from account: {e}")
            sys.exit(1)
            
        if not vin:
            print("No vehicles found in your Leapmotor account!")
            sys.exit(1)
            
        masked_vin = f"***{vin[-4:]}" if len(vin) >= 4 else "***"
        print(f"Auto-detected VIN: {masked_vin}")
        
    cmd = [
        sys.executable,
        "leapmotor_client.py",
        "--cert-file", "custom_components/leapmotor/app_cert.pem",
        "--key-file", "custom_components/leapmotor/app_key.pem",
        "direct-login-vehicle-summary",
        "--vin", vin
    ]
    if username:
        cmd.extend(["--username", username])
    if password:
        cmd.extend(["--password", password])

    masked_vin = f"***{vin[-4:]}" if len(vin) >= 4 else "***"
    print(f"Starting Leapmotor to ABRP bridge for VIN {masked_vin}")
    print(f"Update interval: {args.interval} seconds")

    while True:
        try:
            # Call leapmotor_client.py directly

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"[{time.strftime('%X')}] Error fetching data: {result.stderr.strip()}")
            else:
                data = json.loads(result.stdout)
                summary = data.get("summary", {})
                status = summary.get("status", {})
                location = summary.get("location", {})
                
                # Extract raw signals from the requests block because the summary doesn't include everything
                raw_signal = {}
                try:
                    status_body = data.get("requests", {}).get("vehicle_status", {}).get("body", "{}")
                    status_json = json.loads(status_body)
                    raw_signal = status_json.get("data", {}).get("signal", {})
                except Exception:
                    pass

                # Signal 1939 = raw_charge_status_code. (Usually 1 = charging)
                raw_charge_status = raw_signal.get("1939")
                is_charging = (raw_charge_status == 1) if raw_charge_status is not None else False

                abrp_payload = {
                    "utc": int(time.time()),
                    "soc": status.get("battery_percent"),
                    "is_parked": status.get("is_parked"),
                    "lat": location.get("latitude"),
                    "lon": location.get("longitude"),
                    "is_charging": is_charging,
                    "odometer": status.get("odometer_km"),
                    "ext_temp": status.get("interior_temp_c")  # Using interior temp as fallback if external isn't available
                }
                
                # Filter out None values
                abrp_payload = {k: v for k, v in abrp_payload.items() if v is not None}
                
                # Push to ABRP
                abrp_api_key = "7310445a-0947-4adc-82f5-29bb882c5926"
                headers = {"Authorization": f"APIKEY {abrp_api_key}"}
                params = {"token": args.abrp_token, "tlm": json.dumps(abrp_payload)}
                resp = requests.post(ABRP_URL, headers=headers, params=params, timeout=15)
                
                if resp.status_code == 200:
                    print(f"[{time.strftime('%X')}] Successfully pushed to ABRP: SoC {abrp_payload.get('soc')}%")
                else:
                    print(f"[{time.strftime('%X')}] Failed to push to ABRP: {resp.status_code} {resp.text}")

        except Exception as e:
            print(f"[{time.strftime('%X')}] Unexpected error: {e}")

        if args.once:
            break
            
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
