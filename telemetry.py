"""Standalone EU telemetry helpers, ported from leapmotor-ha v0.7.3.

Only validated read-only status interpretation is shared; no HA dependency.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from dataclasses import dataclass
from typing import Any

def nonzero_state(raw: object) -> bool | None:
    """Return whether a numeric or boolean-like status value is non-zero."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    try:
        value = float(raw)
        return value != 0 if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        normalized = str(raw).strip().lower()
        if normalized in {"true", "yes", "on"}:
            return True
        if normalized in {"false", "no", "off"}:
            return False
        return None

def vehicle_precludes_charging(signals: dict[str, object]) -> bool:
    """Return whether motion or physical READY makes charging impossible."""
    gear = _safe_int(signals.get("1010"))
    speed = _safe_float(signals.get("1319"))
    vehicle_ready = nonzero_state(signals.get("1258"))
    return (
        gear in {1, 2, 3}
        or (speed is not None and speed > 0)
        or vehicle_ready is True
    )

def charge_connection_allows_charging(
    connection_status: object,
    legacy_plug_status: object,
) -> bool:
    """Reject explicit unplugged and drive-time cable states."""
    connection = _safe_int(connection_status)
    if connection is not None:
        # State 4 means connected but waiting for the configured schedule. It
        # does not prove charging, but real current may begin before the state
        # changes, so let the current/time checks make the final decision.
        return connection in {1, 2, 3, 4}
    legacy_plugged = nonzero_state(legacy_plug_status)
    return legacy_plugged is not False

def _safe_int(raw: object) -> int | None:
    """Return a status value as int or None."""
    if raw is None:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError, OverflowError):
        return None

def _safe_float(raw: object) -> float | None:
    """Return a status value as float or None."""
    if raw is None:
        return None
    try:
        value = float(raw)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None

def _status_data_signal(status_data: dict[str, Any]) -> dict[str, Any]:
    """Return the numeric signal map, including fallback values from named fields."""
    raw_signal = status_data.get("signal") or {}
    signal = dict(raw_signal) if isinstance(raw_signal, dict) else {}
    named_signal = _named_status_to_signal(status_data)
    for key, value in named_signal.items():
        if signal.get(key) is None:
            signal[key] = value
    return signal

def _named_status_to_signal(status_data: dict[str, Any]) -> dict[str, Any]:
    """Map legacy/named T03-style status fields to the APK numeric signal IDs."""
    mapped: dict[str, Any] = {}
    field_map = {
        "soc": "1204",
        "chargeRemainTime": "1200",
        "batteryCurrent": "1178",
        "batteryVoltage": "1177",
        "dcInputFastCharge": "1197",
        "expectedMileage": "3260",
        "speed": "1319",
        "totalMileage": "1318",
        "gearStatus": "1010",
        "latitude": "3725",
        "longitude": "3724",
        "acSwitch": "1938",
        "acSetting": "2183",
        "leftFrontWindowPercent": "3727",
        "rightFrontWindowPercent": "3728",
        "leftRearWindowPercent": "1879",
        "rightRearWindowPercent": "1880",
        "leftFrontTirePressure": "2646",
        "rightFrontTirePressure": "2653",
        "leftRearTirePressure": "2660",
        "rightRearTirePressure": "2667",
        "leftFrontTirePressureState": "2641",
        "rightFrontTirePressureState": "2648",
        "leftRearTirePressureState": "2655",
        "rightRearTirePressureState": "2662",
    }
    for source, target in field_map.items():
        if status_data.get(source) is not None:
            mapped[target] = status_data[source]

    if status_data.get("expectedMileage") is not None:
        mapped["2188"] = status_data["expectedMileage"]
    if status_data.get("acSetting") is not None:
        mapped["2184"] = status_data["acSetting"]

    bool_map = {
        "driverDoorLockStatus": "1298",
        "lbcmDriverDoorStatus": "1277",
        "rbcmDriverDoorStatus": "1278",
        "lbcmLeftRearDoorStatus": "1279",
        "rbcmRightRearDoorStatus": "1280",
        "bbcmBackDoorStatus": "1281",
        "driverWindowStatus": "1693",
        "rightFrontWindowStatus": "1694",
        "leftRearWindowStatus": "1695",
        "rightRearWindowStatus": "1696",
        "bcmKeyPositionOn1": "1256",
        "bcmKeyPositionOn2": "1257",
        "bcmKeyPositionOn3": "1258",
    }
    for source, target in bool_map.items():
        if status_data.get(source) is not None:
            mapped[target] = nonzero_state(status_data[source])

    if status_data.get("chargeState") is not None:
        charge_state = _safe_int(status_data.get("chargeState"))
        mapped["1149"] = charge_state
        mapped["47"] = 1 if charge_state in (1, 2) else 0
    if status_data.get("collectTimeMs") is not None:
        mapped["sts"] = status_data["collectTimeMs"]
    elif status_data.get("collectTime") is not None:
        mapped["sts"] = status_data["collectTime"]
    return mapped

def _derive_vehicle_state(signal: dict[str, Any]) -> str | None:
    """Return the movement state independent from charging and HVAC signals."""
    gear = _safe_int(signal.get("1010"))
    if gear is not None:
        if gear in (1, 3):
            return "driving"
        if gear in (0, 2):
            return "parked"

    speed = _safe_float(signal.get("1319"))
    if speed is not None:
        return "driving" if speed > 0 else "parked"

    on3 = nonzero_state(signal.get("1258"))
    if on3 is not None:
        return "parked"

    return None

def _vehicle_precludes_charging(signal: dict[str, Any]) -> bool:
    """Return whether the vehicle state makes cable charging impossible."""
    return vehicle_precludes_charging(signal)

def _is_charging(signal: dict[str, Any]) -> bool:
    """Return whether the vehicle is currently charging."""
    if _vehicle_precludes_charging(signal):
        return False

    remaining_charge_minutes = _safe_int(signal.get("1200"))
    charging_current_a = _safe_float(signal.get("1178"))
    charging_power_kw = _charging_power_kw(signal)
    connection_status = _safe_int(signal.get("1149"))
    # The cable state is authoritative when present. This prevents transient
    # pack current after READY/parking from becoming a charge while unplugged.
    if not charge_connection_allows_charging(
        connection_status,
        signal.get("47"),
    ):
        return False
    if charging_current_a is not None:
        # Confirmed charging sessions show a clearly non-zero current
        # (typically negative while energy flows into the pack). After
        # charge completion the backend can keep 1149=2 while current is 0.
        if abs(charging_current_a) < 1.0:
            # C10 REEV slow AC charging can bypass this pack-current signal.
            # Require both the explicit charging state and a positive remaining
            # time so connected-idle and transient cable states remain off.
            return connection_status == 2 and (
                remaining_charge_minutes is not None and remaining_charge_minutes > 0
            )
        # B10 can actively AC-charge around 2.5 A. C10 plugged-idle snapshots
        # can sit around 1.5 A, so the grey zone needs an extra confirmation.
        if abs(charging_current_a) < 3.0:
            return remaining_charge_minutes is not None and (
                remaining_charge_minutes > 0
                or (charging_power_kw is not None and charging_power_kw >= 1.0)
            )
        return remaining_charge_minutes is not None or (
            charging_power_kw is not None and charging_power_kw >= 1.0
        )

    if charging_power_kw is not None:
        return charging_power_kw >= 1.0 and remaining_charge_minutes is not None

    if connection_status == 2:
        return True
    if connection_status in (0, 1):
        return False

    return False

def _charging_power_kw(signal: dict[str, Any]) -> float | None:
    """Return charging power without using GPS longitude-like signal 2191."""
    if _vehicle_precludes_charging(signal):
        return 0.0

    current = _safe_float(signal.get("1178"))
    voltage = _safe_float(signal.get("1177"))
    if current is None or voltage is None:
        return None
    abs_current = abs(current)
    raw_power_kw = abs(current * voltage) / 1000.0
    if abs_current < 1.0:
        return 0.0
    # The C10 plugged-idle snapshot shows about 1.5 A without active charging,
    # while B10 can actively AC-charge around 2.5 A. In this grey zone, require
    # either remaining charge time or a clearly non-trivial calculated power.
    if abs_current < 3.0:
        remaining_charge_minutes = _safe_int(signal.get("1200"))
        if remaining_charge_minutes is None and raw_power_kw < 1.0:
            return None
    return round(raw_power_kw, 3)

MERIDIAN_CROSSING_DEGREES = 1.0
SIGN_FLIP_CONFIRMATIONS = 10

@dataclass(frozen=True, slots=True)
class CoordinateResolution:
    """Result of resolving one signed or unsigned coordinate axis."""

    value: float | None
    sign: int | None
    pending_flip_count: int
    source: str

def resolve_coordinate(
    *,
    signed_value: object,
    unsigned_value: object,
    remembered_sign: int | None,
    pending_flip_count: int = 0,
) -> CoordinateResolution:
    """Resolve one coordinate while guarding against lost minus signs."""
    signed = _safe_float(signed_value)
    if signed not in (None, 0.0):
        proposed_sign = -1 if signed < 0 else 1
        sign_is_authoritative = (
            remembered_sign is None
            or remembered_sign == proposed_sign
            or signed < 0
            or abs(signed) <= MERIDIAN_CROSSING_DEGREES
        )
        if sign_is_authoritative:
            return CoordinateResolution(signed, proposed_sign, 0, "signed_signal")

        confirmations = pending_flip_count + 1
        if confirmations >= SIGN_FLIP_CONFIRMATIONS:
            return CoordinateResolution(
                signed, proposed_sign, 0, "confirmed_hemisphere_crossing"
            )
        return CoordinateResolution(
            abs(signed) * remembered_sign,
            remembered_sign,
            confirmations,
            "remembered_sign_guard",
        )

    unsigned = _safe_float(unsigned_value)
    if unsigned is None:
        return CoordinateResolution(None, remembered_sign, 0, "unavailable")

    sign = remembered_sign or 1
    return CoordinateResolution(
        abs(unsigned) * sign,
        remembered_sign,
        0,
        "unsigned_signal_with_memory" if remembered_sign else "unsigned_signal",
    )

def vehicle_status_path(car_type: object) -> str:
    """Return the backend status path segment for a vehicle model."""
    normalized = str(car_type or "C10").strip().lower()
    if normalized in {"b05", "b10", "b11"}:
        return "c10"
    return normalized or "c10"


def parse_vehicle_timestamp(raw: object) -> int | None:
    """Accept epoch seconds/milliseconds or ISO with an explicit timezone."""
    numeric = _safe_float(raw)
    if numeric is not None:
        return int(numeric / 1000 if numeric >= 100_000_000_000 else numeric)
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        # Never interpret a timezone-less vehicle clock as the host timezone.
        return int(parsed.timestamp()) if parsed.tzinfo else None
    except (ValueError, OverflowError, OSError):
        return None


def checked_body(result: dict) -> dict:
    body = json.loads(result["body"])
    if result.get("status_code") != 200 or body.get("code") not in (0, "0"):
        raise ValueError("Leapmotor status request failed")
    if not isinstance(body.get("data"), dict):
        raise ValueError("Leapmotor status data missing")
    return body


def fetch_vehicle_status(client, headers: dict, vin: str, list_json: dict) -> dict:
    """Select the model endpoint, with a 404 fallback and shared-car retry."""
    from urllib.parse import quote
    entry = None
    shared = False
    for bucket in ("bindcars", "sharedcars"):
        for car in (list_json.get("data") or {}).get(bucket, []) or []:
            if str(car.get("vin")) == vin:
                entry, shared = car, bucket == "sharedcars"
                break
        if entry is not None:
            break
    if entry is None:
        raise ValueError("Selected VIN is not in this account")
    path = vehicle_status_path(entry.get("carType"))
    body = f"vin={quote(vin, safe='')}"
    def fetch(path, body):
        return client.replay_request_curl(
            path=f"/carownerservice/oversea/vehicle/v1/status/get/{quote(path, safe='')}",
            headers=headers, data=body,
        )
    result = fetch(path, body)
    if result.get("status_code") == 404 and path != "c10":
        path = "c10"
        result = fetch(path, body)
    parsed = checked_body(result)
    if shared and entry.get("carId") and not _status_data_signal(parsed["data"]):
        result = fetch(path, body + "&carId=" + quote(str(entry["carId"]), safe=""))
        checked_body(result)
    result["_status_endpoint_path"] = path
    return result


def build_payload(status_data: dict, state: dict, *, now: float, max_age: int = 900):
    """Return telemetry and next per-VIN state, or reject unusable/stale data.

    State is committed only after successful delivery. Unknown hemispheres and
    temperatures are omitted rather than guessed. Zero SOC remains valid.
    """
    signal = _status_data_signal(status_data)
    utc = parse_vehicle_timestamp(signal.get("sts"))
    if utc is None or utc <= 0 or now - utc > max_age or utc - now > 60:
        raise ValueError("Missing, stale or future vehicle timestamp")
    if utc <= state.get("last_utc", 0):
        raise ValueError("Vehicle sample already delivered or out of order")
    soc = _safe_float(signal.get("1204"))
    if soc is None or not 0 <= soc <= 100:
        raise ValueError("Missing or invalid battery percentage")
    payload = {"utc": utc, "soc": soc}
    movement = _derive_vehicle_state(signal)
    if movement is not None:
        payload["is_parked"] = movement == "parked"
    if _vehicle_precludes_charging(signal) or any(
        signal.get(k) is not None for k in ("1149", "47", "1178")
    ):
        payload["is_charging"] = _is_charging(signal)
    odometer = _safe_float(signal.get("1318"))
    if odometer is not None and odometer >= 0:
        payload["odometer"] = odometer
    next_state = dict(state, last_utc=utc)
    coordinates = {}
    for axis, signed_id, unsigned_ids, limit in (
        ("lat", "3", ("3725", "2190"), 90),
        ("lon", "2", ("3724", "2191"), 180),
    ):
        signed = _safe_float(signal.get(signed_id))
        unsigned = next((_safe_float(signal[k]) for k in unsigned_ids if signal.get(k) is not None), None)
        # Named coordinates with an explicit minus sign also establish hemisphere.
        if signed is None and unsigned is not None and unsigned < 0:
            signed = unsigned
        if signed is not None and abs(signed) > limit:
            continue
        if unsigned is not None and abs(unsigned) > limit:
            unsigned = None
        resolved = resolve_coordinate(signed_value=signed, unsigned_value=unsigned,
            remembered_sign=state.get(axis + "_sign"),
            pending_flip_count=state.get(axis + "_pending", 0))
        next_state[axis + "_sign"] = resolved.sign
        next_state[axis + "_pending"] = resolved.pending_flip_count
        if resolved.value is not None and resolved.sign is not None:
            coordinates[axis] = resolved.value
    if len(coordinates) == 2:
        payload.update(coordinates)
    return payload, next_state
