#!/usr/bin/env python3
"""Minimal Leapmotor API client based on current reverse-engineering findings."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import urllib3
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


DEFAULT_BASE_URL = "https://appgateway.leapmotor-international.de"
DEFAULT_APP_VERSION = "1.12.3"
DEFAULT_DEVICE_ID = "bd605e5c599944efb846bcf70f1449d8"
DEFAULT_SOURCE = "leapmotor"
DEFAULT_CHANNEL = "1"
DEFAULT_LANGUAGE = "de-DE"
DEFAULT_DEVICE_TYPE = "1"
DEFAULT_P12_ENC_ALG = "1"
KNOWN_ACCOUNT_P12_PASSWORDS = (
    "e/t9jEgLfrGMOvQ",
    "VPlWT5wK7RU1bXN",
    "BAqKLV0OoE2HgQ8",
    "qeyhKynw0rKjieT",
)

# Confirmed offline against captured app traffic for at least one request class.
DEFAULT_SIGN_KEY_HEX = (
    "c0318e06835e11e15addbd9bd2d9a38e859a77cc0121ad39fe2aedf45a1b5b3c"
)

_P12_MODULE_SPEC = importlib.util.spec_from_file_location(
    "leapmotor_p12",
    Path(__file__).resolve().parent / "custom_components" / "leapmotor" / "p12.py",
)
if _P12_MODULE_SPEC is None or _P12_MODULE_SPEC.loader is None:
    raise RuntimeError("Could not load Leapmotor P12 derivation module")
_P12_MODULE = importlib.util.module_from_spec(_P12_MODULE_SPEC)
_P12_MODULE_SPEC.loader.exec_module(_P12_MODULE)
derive_account_p12_password = _P12_MODULE.derive_account_p12_password


@dataclass
class Credentials:
    username: str
    password: str


@dataclass
class LeapmotorConfig:
    base_url: str = DEFAULT_BASE_URL
    app_version: str = DEFAULT_APP_VERSION
    device_id: str = DEFAULT_DEVICE_ID
    source: str = DEFAULT_SOURCE
    channel: str = DEFAULT_CHANNEL
    accept_language: str = DEFAULT_LANGUAGE
    device_type: str = DEFAULT_DEVICE_TYPE
    p12_enc_alg: str = DEFAULT_P12_ENC_ALG
    sign_key_hex: str = DEFAULT_SIGN_KEY_HEX
    # TLS verification is disabled by default because the endpoint presents an untrusted chain
    verify_tls: bool = False
    timeout_seconds: float = 20.0
    cert_file: str | None = None
    key_file: str | None = None
    derived_sign_ikm: str | None = None
    derived_sign_salt: str | None = None
    derived_sign_info: str | None = None










def load_local_access(path: str | Path = "LOCAL_ACCESS.md") -> Credentials | None:
    local_path = Path(path)
    if not local_path.exists():
        return None

    content = local_path.read_text(encoding="utf-8")
    username_match = re.search(r"Benutzername:\s*`([^`]+)`", content)
    password_match = re.search(r"Passwort:\s*`([^`]+)`", content)
    if not username_match or not password_match:
        return None

    return Credentials(
        username=username_match.group(1),
        password=password_match.group(1),
    )


def load_credentials(args: argparse.Namespace) -> Credentials:
    username = args.username or os.getenv("LEAPMOTOR_USERNAME")
    password = args.password or os.getenv("LEAPMOTOR_PASSWORD")

    if username and password:
        return Credentials(username=username, password=password)

    local_access = load_local_access()
    if local_access:
        return local_access

    raise SystemExit(
        "Keine Zugangsdaten gefunden. "
        "Nutze --username/--password, Umgebungsvariablen oder LOCAL_ACCESS.md."
    )


def extract_p12_to_pem(*, p12_bytes: bytes, password: str) -> tuple[str, str]:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".p12") as p12_file:
        p12_file.write(p12_bytes)
        p12_path = Path(p12_file.name)
    with tempfile.NamedTemporaryFile(delete=False, suffix="-cert.pem") as cert_file:
        cert_path = Path(cert_file.name)
    with tempfile.NamedTemporaryFile(delete=False, suffix="-key.pem") as key_file:
        key_path = Path(key_file.name)

    subprocess.run(
        [
            "openssl",
            "pkcs12",
            "-legacy",
            "-in",
            str(p12_path),
            "-clcerts",
            "-nokeys",
            "-out",
            str(cert_path),
            "-passin",
            f"pass:{password}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "openssl",
            "pkcs12",
            "-legacy",
            "-in",
            str(p12_path),
            "-nocerts",
            "-nodes",
            "-out",
            str(key_path),
            "-passin",
            f"pass:{password}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        p12_path.unlink(missing_ok=True)
    except OSError:
        pass
    return str(cert_path), str(key_path)


def find_cached_account_pem_pair(user_id: str, search_dir: str | Path = "findings") -> tuple[str, str] | None:
    base = Path(search_dir)
    cert_candidates = sorted(base.glob(f"login-base64Cert-{user_id}-*-cert.pem"))
    key_candidates = sorted(base.glob(f"login-base64Cert-{user_id}-*-key.pem"))
    if cert_candidates and key_candidates:
        return str(cert_candidates[-1]), str(key_candidates[-1])

    return None


class LeapmotorClient:
    def __init__(self, config: LeapmotorConfig):
        self.config = config
        self.session = requests.Session()

    @property
    def sign_key(self) -> bytes:
        if (
            self.config.derived_sign_ikm is not None
            and self.config.derived_sign_salt is not None
            and self.config.derived_sign_info is not None
        ):
            return derive_sign_key(
                ikm=self.config.derived_sign_ikm,
                salt=self.config.derived_sign_salt,
                info=self.config.derived_sign_info,
            )
        return bytes.fromhex(self.config.sign_key_hex)

    @property
    def client_cert(self) -> tuple[str, str] | None:
        if self.config.cert_file and self.config.key_file:
            return (self.config.cert_file, self.config.key_file)
        return None

    def build_sign_input(
        self,
        *,
        nonce: str,
        timestamp: str,
        vin: str | None = None,
        extra_prefix: str = "",
        extra_infix: str = "",
        extra_suffix: str = "",
        include_device_type: bool = True,
    ) -> str:
        parts = [
            extra_prefix,
            self.config.accept_language,
            self.config.channel,
            self.config.device_id,
        ]
        if include_device_type:
            parts.append(self.config.device_type)
        parts.extend(
            [
                extra_infix,
                nonce,
                self.config.source,
                timestamp,
                extra_suffix,
                self.config.app_version,
            ]
        )
        if vin:
            parts.append(vin)
        return "".join(parts)

    def sign(self, sign_input: str) -> str:
        return hmac.new(
            self.sign_key,
            sign_input.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def build_headers(
        self,
        *,
        nonce: str | None = None,
        timestamp: str | None = None,
        vin: str | None = None,
        extra_prefix: str = "",
        extra_infix: str = "",
        extra_suffix: str = "",
        include_device_type: bool = True,
    ) -> tuple[dict[str, str], str]:
        nonce = nonce or str(random.randint(100000, 9999999))
        timestamp = timestamp or str(int(time.time() * 1000))
        sign_input = self.build_sign_input(
            nonce=nonce,
            timestamp=timestamp,
            vin=vin,
            extra_prefix=extra_prefix,
            extra_infix=extra_infix,
            extra_suffix=extra_suffix,
            include_device_type=include_device_type,
        )
        headers = {
            "Content-Type": "application/json",
            "acceptLanguage": self.config.accept_language,
            "channel": self.config.channel,
            "deviceType": self.config.device_type,
            "X-P12_ENC_ALG": self.config.p12_enc_alg,
            "source": self.config.source,
            "version": self.config.app_version,
            "nonce": nonce,
            "deviceId": self.config.device_id,
            "timestamp": timestamp,
            "sign": self.sign(sign_input),
        }
        return headers, sign_input

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        vin: str | None = None,
        extra_prefix: str = "",
        include_auth_token: str | None = None,
    ) -> requests.Response:
        headers, _ = self.build_headers(vin=vin, extra_prefix=extra_prefix)
        if include_auth_token:
            headers["Authorization"] = include_auth_token

        url = f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
        return self.session.request(
            method=method.upper(),
            url=url,
            headers=headers,
            json=json_body,
            timeout=self.config.timeout_seconds,
            verify=self.config.verify_tls,
            cert=self.client_cert,
        )

    def login(self, credentials: Credentials) -> tuple[requests.Response, dict[str, Any]]:
        payload = {
            "username": credentials.username,
            "password": credentials.password,
            "loginType": 2,
        }
        headers, sign_input = self.build_headers()
        url = (
            f"{self.config.base_url.rstrip('/')}"
            "/carownerservice/oversea/acct/v1/login"
        )
        response = self.session.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.config.timeout_seconds,
            verify=self.config.verify_tls,
            cert=self.client_cert,
        )
        meta = {
            "url": url,
            "headers": headers,
            "payload": payload,
            "sign_input": sign_input,
        }
        return response, meta

    def replay_request(
        self,
        *,
        path: str,
        headers: dict[str, str],
        data: str | None = None,
    ) -> requests.Response:
        url = f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
        return self.session.post(
            url,
            headers=headers,
            data=data,
            timeout=self.config.timeout_seconds,
            verify=self.config.verify_tls,
            cert=self.client_cert,
        )

    def replay_request_curl(
        self,
        *,
        path: str,
        headers: dict[str, str],
        data: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
        cert_file = key_file = None
        if self.client_cert:
            cert_file, key_file = self.client_cert
        with tempfile.NamedTemporaryFile() as header_file, tempfile.NamedTemporaryFile() as body_file:
            cmd = [
                "curl",
                "--silent",
                "--show-error",
                "--insecure" if not self.config.verify_tls else "--fail-with-body",
                "-X",
                "POST",
                url,
                "-D",
                header_file.name,
                "-o",
                body_file.name,
            ]
            if cert_file and key_file:
                cmd.extend(["--cert", cert_file, "--key", key_file])
            for key, value in headers.items():
                cmd.extend(["-H", f"{key}: {value}"])
            if data is not None:
                cmd.extend(["--data", data])

            result = subprocess.run(cmd, capture_output=True, text=True)
            body_text = Path(body_file.name).read_text(encoding="utf-8", errors="replace")
            header_text = Path(header_file.name).read_text(encoding="utf-8", errors="replace")
            status_code = 0
            for line in header_text.splitlines():
                if line.startswith("HTTP/"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        status_code = int(parts[1])
            return {
                "status_code": status_code,
                "headers_raw": header_text,
                "body": body_text,
                "curl_cmd": cmd,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Leapmotor API helper based on current RE findings.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="API base URL.",
    )
    parser.add_argument(
        "--app-version",
        default=DEFAULT_APP_VERSION,
        help="App version used in signed headers.",
    )
    parser.add_argument(
        "--device-id",
        default=DEFAULT_DEVICE_ID,
        help="Device ID used in signed headers.",
    )
    parser.add_argument(
        "--verify-tls",
        action="store_true",
        help="Enable TLS verification. Disabled by default because the endpoint currently presents an untrusted chain in this environment.",
    )
    parser.add_argument(
        "--sign-key-hex",
        default=DEFAULT_SIGN_KEY_HEX,
        help="HMAC-SHA256 key in hex.",
    )
    parser.add_argument("--derived-sign-ikm", help="Ikm for HKDF-derived sign key.")
    parser.add_argument("--derived-sign-salt", help="Salt for HKDF-derived sign key.")
    parser.add_argument("--derived-sign-info", help="Info for HKDF-derived sign key.")
    parser.add_argument(
        "--cert-file",
        help="PEM client certificate for direct mTLS requests.",
    )
    parser.add_argument(
        "--key-file",
        help="PEM private key for direct mTLS requests.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="Attempt a login request.")
    login_parser.add_argument("--username", help="Leapmotor username/email.")
    login_parser.add_argument("--password", help="Leapmotor password.")
    login_parser.add_argument(
        "--dump-request",
        action="store_true",
        help="Print signed request metadata before sending.",
    )

    login_form_curl_parser = subparsers.add_parser(
        "login-form-curl",
        help="Send acct/v1/login as form-encoded curl request with configurable sign input.",
    )
    login_form_curl_parser.add_argument("--username", help="Leapmotor username/email.")
    login_form_curl_parser.add_argument("--password", help="Leapmotor password.")
    login_form_curl_parser.add_argument(
        "--policy-id",
        default="20260204",
        help="policyId value for the current login form flow.",
    )
    login_form_curl_parser.add_argument(
        "--login-method",
        default="1",
        help="loginMethod value for the current login form flow.",
    )
    login_form_curl_parser.add_argument(
        "--is-recover-acct",
        default="0",
        help="isRecoverAcct value for the current login form flow.",
    )
    login_form_curl_parser.add_argument(
        "--firebase-token",
        default="",
        help="Optional fireBaseToken or similar device-side login context to include in the sign input.",
    )
    login_form_curl_parser.add_argument("--nonce", help="Override generated nonce.")
    login_form_curl_parser.add_argument("--timestamp", help="Override generated timestamp.")
    login_form_curl_parser.add_argument(
        "--extra-prefix",
        default="",
        help="Optional prefix for the login sign input.",
    )
    login_form_curl_parser.add_argument(
        "--extra-infix",
        default="",
        help="Optional infix inserted after deviceId and before nonce. If --firebase-token is set, it is appended here.",
    )
    login_form_curl_parser.add_argument(
        "--extra-suffix",
        default="",
        help="Optional suffix inserted after timestamp and before version.",
    )
    login_form_curl_parser.add_argument(
        "--omit-device-type",
        action="store_true",
        help="Omit deviceType from the sign input.",
    )
    login_form_curl_parser.add_argument(
        "--dump-request",
        action="store_true",
        help="Print request metadata before sending.",
    )

    sign_parser = subparsers.add_parser(
        "sign-sample",
        help="Generate one signed header set without sending a request.",
    )
    sign_parser.add_argument("--nonce", help="Override generated nonce.")
    sign_parser.add_argument("--timestamp", help="Override generated timestamp.")
    sign_parser.add_argument("--vin", help="Optional VIN suffix for sign input.")
    sign_parser.add_argument(
        "--extra-prefix",
        default="",
        help="Optional prefix seen in some non-login request classes.",
    )
    sign_parser.add_argument(
        "--extra-infix",
        default="",
        help="Optional infix inserted after deviceId and before nonce.",
    )
    sign_parser.add_argument(
        "--extra-suffix",
        default="",
        help="Optional suffix inserted after timestamp and before version.",
    )
    sign_parser.add_argument(
        "--omit-device-type",
        action="store_true",
        help="Omit deviceType from the sign input for modern request classes.",
    )

    jwt_parser = subparsers.add_parser(
        "decode-jwt",
        help="Decode a JWT payload without signature verification.",
    )
    jwt_parser.add_argument("--token", required=True, help="JWT access or refresh token.")

    derive_key_parser = subparsers.add_parser(
        "derive-sign-key",
        help="Derive the runtime sign key from signIkm/signSalt/signInfo.",
    )
    derive_key_parser.add_argument("--ikm", required=True, help="signIkm value.")
    derive_key_parser.add_argument("--salt", required=True, help="signSalt value.")
    derive_key_parser.add_argument("--info", required=True, help="signInfo value.")


    acct_get_parser = subparsers.add_parser(
        "acct-get-replay",
        help="Replay a verified acct/v1/get request via mTLS using captured headers.",
    )
    acct_get_parser.add_argument("--token", required=True, help="Current access token.")
    acct_get_parser.add_argument("--user-id", default="109118", help="Current user ID.")

    acct_get_generated_parser = subparsers.add_parser(
        "acct-get-generated",
        help="Send acct/v1/get with freshly generated nonce/timestamp/sign.",
    )
    acct_get_generated_parser.add_argument("--token", required=True, help="Current access token.")
    acct_get_generated_parser.add_argument("--user-id", default="109118", help="Current user ID.")

    token_refresh_generated_parser = subparsers.add_parser(
        "token-refresh-generated",
        help="Send acct/v1/token/refresh with freshly generated nonce/timestamp/sign.",
    )
    token_refresh_generated_parser.add_argument("--token", required=True, help="Current access token.")
    token_refresh_generated_parser.add_argument("--refresh-token", required=True, help="Current refresh token.")
    token_refresh_generated_parser.add_argument("--user-id", default="109118", help="Current user ID.")

    cert_sync_generated_parser = subparsers.add_parser(
        "cert-sync-generated",
        help="Send vehicle/v1/cert/sync with freshly generated nonce/timestamp/sign.",
    )
    cert_sync_generated_parser.add_argument("--token", required=True, help="Current access token.")
    cert_sync_generated_parser.add_argument("--user-id", default="109118", help="Current user ID.")

    device_save_parser = subparsers.add_parser(
        "device-save-replay",
        help="Replay a verified appDevice/deviceInfo/save request via mTLS using captured headers.",
    )
    device_save_parser.add_argument("--token", required=True, help="Current access token.")
    device_save_parser.add_argument("--user-id", default="109118", help="Current user ID.")
    device_save_parser.add_argument(
        "--body",
        default="model=BTV-DL09%2CHuawei&appversion=1.12.3&version=14&deviceID=bd605e5c599944efb846bcf70f1449d8",
        help="Form-encoded body to send.",
    )

    device_save_generated_parser = subparsers.add_parser(
        "device-save-generated",
        help="Send appDevice/deviceInfo/save with freshly generated nonce/timestamp/sign.",
    )
    device_save_generated_parser.add_argument("--token", required=True, help="Current access token.")
    device_save_generated_parser.add_argument("--user-id", default="109118", help="Current user ID.")
    device_save_generated_parser.add_argument(
        "--sign-mode",
        default="double_device_id_device_type",
        choices=["legacy", "time_offset", "double_device_id_device_type"],
        help="Sign input mode to use.",
    )
    device_save_generated_parser.add_argument(
        "--body",
        default="model=BTV-DL09%2CHuawei&appversion=1.12.3&version=14&deviceID=bd605e5c599944efb846bcf70f1449d8",
        help="Form-encoded body to send.",
    )

    sync_generated_parser = subparsers.add_parser(
        "sync-generated",
        help="Send common/v1/sync with freshly generated nonce/timestamp/sign.",
    )
    sync_generated_parser.add_argument("--token", required=True, help="Current access token.")
    sync_generated_parser.add_argument("--user-id", default="109118", help="Current user ID.")
    sync_generated_parser.add_argument(
        "--sign-mode",
        default="time_offset",
        choices=["legacy", "time_offset", "double_device_id", "double_device_id_device_type"],
        help="Sign input mode to use.",
    )
    sync_generated_parser.add_argument(
        "--body",
        default="type=timeOffset&vin=",
        help="Form-encoded body to send.",
    )

    vehicle_list_generated_parser = subparsers.add_parser(
        "vehicle-list-generated",
        help="Send vehicle/v1/list with freshly generated nonce/timestamp/sign.",
    )
    vehicle_list_generated_parser.add_argument("--token", required=True, help="Current access token.")
    vehicle_list_generated_parser.add_argument("--user-id", default="109118", help="Current user ID.")

    direct_login_vehicle_list_parser = subparsers.add_parser(
        "direct-login-vehicle-list",
        help="Login with static app cert, derive account cert, then call vehicle/v1/list.",
    )
    direct_login_vehicle_list_parser.add_argument("--username", help="Leapmotor username/email.")
    direct_login_vehicle_list_parser.add_argument("--password", help="Leapmotor password.")
    direct_login_vehicle_list_parser.add_argument(
        "--account-p12-password",
        default=None,
        help="Optional fallback password for the account PKCS12; normally derived from login data.",
    )

    direct_login_vehicle_status_parser = subparsers.add_parser(
        "direct-login-vehicle-status",
        help="Login with static app cert, derive account cert, then call vehicle/v1/status/get/c10 via curl.",
    )
    direct_login_vehicle_status_parser.add_argument("--username", help="Leapmotor username/email.")
    direct_login_vehicle_status_parser.add_argument("--password", help="Leapmotor password.")
    direct_login_vehicle_status_parser.add_argument("--vin", required=True, help="VIN to query.")
    direct_login_vehicle_status_parser.add_argument(
        "--account-p12-password",
        default=None,
        help="Optional fallback password for the account PKCS12; normally derived from login data.",
    )

    direct_login_carpicture_parser = subparsers.add_parser(
        "direct-login-carpicture",
        help="Login with static app cert, derive account cert, then call vehicle/v1/carpicture/key.",
    )
    direct_login_carpicture_parser.add_argument("--username", help="Leapmotor username/email.")
    direct_login_carpicture_parser.add_argument("--password", help="Leapmotor password.")
    direct_login_carpicture_parser.add_argument("--vin", required=True, help="VIN to query.")
    direct_login_carpicture_parser.add_argument(
        "--account-p12-password",
        default=None,
        help="Optional fallback password for the account PKCS12; normally derived from login data.",
    )

    direct_login_vehicle_summary_parser = subparsers.add_parser(
        "direct-login-vehicle-summary",
        help="Login with static app cert, derive account cert, then fetch a normalized vehicle summary.",
    )
    direct_login_vehicle_summary_parser.add_argument("--username", help="Leapmotor username/email.")
    direct_login_vehicle_summary_parser.add_argument("--password", help="Leapmotor password.")
    direct_login_vehicle_summary_parser.add_argument("--vin", required=True, help="VIN to query.")
    direct_login_vehicle_summary_parser.add_argument(
        "--account-p12-password",
        default=None,
        help="Optional fallback password for the account PKCS12; normally derived from login data.",
    )

    carpicture_generated_parser = subparsers.add_parser(
        "carpicture-generated",
        help="Send vehicle/v1/carpicture/key with freshly generated nonce/timestamp/sign.",
    )
    carpicture_generated_parser.add_argument("--token", required=True, help="Current access token.")
    carpicture_generated_parser.add_argument(
        "--body",
        default="deviceID=&vin=",
        help="Form-encoded body to send.",
    )

    vehicle_status_curl_parser = subparsers.add_parser(
        "vehicle-status-replay-curl",
        help="Replay vehicle/v1/status/get/c10 via curl/libcurl instead of requests.",
    )
    vehicle_status_curl_parser.add_argument("--token", required=True, help="Current access token.")
    vehicle_status_curl_parser.add_argument("--user-id", default="105673", help="Current user ID.")
    vehicle_status_curl_parser.add_argument("--sign", required=True, help="Captured sign header.")
    vehicle_status_curl_parser.add_argument("--nonce", required=True, help="Captured nonce header.")
    vehicle_status_curl_parser.add_argument("--timestamp", required=True, help="Captured timestamp header.")
    vehicle_status_curl_parser.add_argument("--vin", required=True, help="VIN to query.")

    vehicle_status_generated_curl_parser = subparsers.add_parser(
        "vehicle-status-generated-curl",
        help="Send vehicle/v1/status/get/c10 with freshly generated nonce/timestamp/sign via curl/libcurl.",
    )
    vehicle_status_generated_curl_parser.add_argument("--token", required=True, help="Current access token.")
    vehicle_status_generated_curl_parser.add_argument("--user-id", default="105673", help="Current user ID.")
    vehicle_status_generated_curl_parser.add_argument("--vin", required=True, help="VIN to query.")

    return parser


def print_json(data: Any) -> None:
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Kein JWT mit drei Segmenten.")

    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    raw = base64.urlsafe_b64decode(payload)
    return json.loads(raw.decode("utf-8"))


def derive_session_device_id(token: str | None) -> str:
    if not token:
        return DEFAULT_DEVICE_ID
    try:
        payload = decode_jwt_payload(token)
    except Exception:
        return DEFAULT_DEVICE_ID
    user_name = str(payload.get("user_name") or "")
    parts = user_name.split(",")
    if len(parts) >= 4 and parts[2]:
        return parts[2]
    return DEFAULT_DEVICE_ID




def derive_sign_key(*, ikm: str, salt: str, info: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt.encode("utf-8"),
        info=info.encode("utf-8"),
    ).derive(ikm.encode("utf-8"))


def parse_json_body(body: str) -> dict[str, Any]:
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ungueltiger JSON-Body: {exc}") from exc


def aes_cbc_pkcs7_encrypt_b64(plaintext: str, *, key_text: str, iv_text: str) -> str:
    key = key_text.encode("utf-8")
    iv = iv_text.encode("utf-8")
    if len(key) not in (16, 24, 32):
        raise ValueError(f"ungueltige AES-Schluessellaenge: {len(key)}")
    if len(iv) != 16:
        raise ValueError(f"ungueltige IV-Laenge: {len(iv)}")

    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(ciphertext).decode("ascii")




def build_vehicle_api_headers(
    client: LeapmotorClient,
    *,
    sign_mode: str,
    vin: str,
    user_id: str | None = None,
) -> tuple[dict[str, str], str]:
    if sign_mode == "status_like":
        return client.build_headers(vin=vin, include_device_type=True)
    if sign_mode == "legacy":
        return client.build_headers(include_device_type=True)
    if sign_mode == "picture_like":
        return client.build_headers(
            vin=vin,
            extra_infix=client.config.device_id + client.config.device_type,
            include_device_type=False,
        )
    if sign_mode == "userid_false":
        if not user_id:
            raise ValueError("userid_false braucht user_id")
        return client.build_headers(
            extra_prefix=f"{client.config.accept_language}{user_id}false{client.config.channel}",
            extra_infix=client.config.device_id,
            include_device_type=False,
        )
    if sign_mode == "userid_true":
        if not user_id:
            raise ValueError("userid_true braucht user_id")
        return client.build_headers(
            extra_prefix=f"{client.config.accept_language}{user_id}true{client.config.channel}",
            extra_infix=client.config.device_id,
            include_device_type=False,
        )
    raise ValueError(f"Unbekannter remote ctl sign mode: {sign_mode}")












def login_with_static_cert(
    *,
    static_client: LeapmotorClient,
    credentials: Credentials,
    account_p12_password: str | None,
) -> tuple[dict[str, Any], dict[str, Any], LeapmotorClient]:
    login_headers, login_sign_input = build_login_headers(
        client=static_client,
        username=credentials.username,
        password=credentials.password,
        policy_id="20260204",
        login_method="1",
        is_recover_acct="0",
    )
    login_body = build_login_form_body(
        username=credentials.username,
        password=credentials.password,
        policy_id="20260204",
        login_method="1",
        is_recover_acct="0",
    )
    login_result = static_client.replay_request_curl(
        path="/carownerservice/oversea/acct/v1/login",
        headers=login_headers,
        data=login_body,
    )
    login_json = parse_json_body(login_result["body"])
    if login_json.get("code") != 0:
        raise ValueError(f"Login fehlgeschlagen: {login_result['body']}")

    login_data = login_json["data"]
    last_p12_error: subprocess.CalledProcessError | None = None
    password_candidates = build_account_p12_password_candidates(login_data, account_p12_password)
    cert_file = key_file = None
    for password_candidate in password_candidates:
        try:
            cert_file, key_file = extract_p12_to_pem(
                p12_bytes=base64.b64decode(login_data["base64Cert"]),
                password=password_candidate,
            )
            break
        except subprocess.CalledProcessError as exc:
            last_p12_error = exc
    if not cert_file or not key_file:
        cached = find_cached_account_pem_pair(str(login_data["id"]))
        if not cached:
            if last_p12_error:
                raise last_p12_error
            raise ValueError("Kein nutzbares Account-Zertifikat gefunden.")
        cert_file, key_file = cached
    account_client = LeapmotorClient(
        LeapmotorConfig(
            base_url=static_client.config.base_url,
            app_version=static_client.config.app_version,
            device_id=derive_session_device_id(str(login_data["token"])),
            source=static_client.config.source,
            channel=static_client.config.channel,
            accept_language=static_client.config.accept_language,
            device_type=static_client.config.device_type,
            p12_enc_alg=static_client.config.p12_enc_alg,
            verify_tls=static_client.config.verify_tls,
            timeout_seconds=static_client.config.timeout_seconds,
            cert_file=cert_file,
            key_file=key_file,
            derived_sign_ikm=str(login_data["signIkm"]),
            derived_sign_salt=str(login_data["signSalt"]),
            derived_sign_info=str(login_data["signInfo"]),
        )
    )
    login_meta = {
        "status_code": login_result["status_code"],
        "request": {
            "headers": login_headers,
            "sign_input": login_sign_input,
            "body": login_body,
        },
        "body": login_result["body"],
    }
    return login_data, login_meta, account_client


def build_account_p12_password_candidates(
    login_data: dict[str, Any],
    provided_password: str | None = None,
) -> list[str]:
    candidates = []
    if provided_password:
        candidates.append(provided_password)
    try:
        derived_password = derive_account_p12_password(login_data["id"], str(login_data["uid"]))
    except (KeyError, TypeError, ValueError):
        derived_password = None
    if derived_password and derived_password not in candidates:
        candidates.append(derived_password)
    candidates.extend(password for password in KNOWN_ACCOUNT_P12_PASSWORDS if password not in candidates)
    return candidates


def extract_account_p12_to_pem(
    *,
    login_data: dict[str, Any],
    provided_password: str | None = None,
) -> tuple[str, str]:
    last_error: subprocess.CalledProcessError | None = None
    p12_bytes = base64.b64decode(login_data["base64Cert"])
    for password in build_account_p12_password_candidates(login_data, provided_password):
        try:
            return extract_p12_to_pem(p12_bytes=p12_bytes, password=password)
        except subprocess.CalledProcessError as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise ValueError("Kein nutzbares Account-Zertifikat gefunden.")


def fetch_vehicle_binding(
    *,
    account_client: LeapmotorClient,
    login_data: dict[str, Any],
    vin: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    list_headers, list_sign_input = build_vehicle_api_headers(
        account_client,
        sign_mode="legacy",
        vin="",
        user_id=str(login_data["id"]),
    )
    list_headers.update(
        {
            "Content-Type": "application/x-www-form-urlencoded",
            "userId": str(login_data["id"]),
            "token": login_data["token"],
        }
    )
    list_result = account_client.replay_request_curl(
        path="/carownerservice/oversea/vehicle/v1/list",
        headers=list_headers,
        data="",
    )
    list_json = parse_json_body(list_result["body"])
    if list_json.get("code") != 0:
        raise ValueError(f"vehicle/v1/list fehlgeschlagen: {list_result['body']}")

    found = None
    list_data = list_json.get("data") or {}
    for bucket in ("bindcars", "sharedcars"):
        for item in list_data.get(bucket, []) or []:
            if str(item.get("vin")) == vin:
                found = {
                    "bucket": bucket,
                    "vin": str(item.get("vin")),
                    "carId": str(item.get("carId")) if item.get("carId") is not None else None,
                    "carType": item.get("carType"),
                    "nickName": item.get("nickName"),
                }
                break
        if found:
            break

    meta = {
        "request": {
            "path": "/carownerservice/oversea/vehicle/v1/list",
            "headers": list_headers,
            "sign_input": list_sign_input,
            "body": "",
        },
        "response": list_result,
        "body_json": list_json,
    }
    if not found:
        raise ValueError(
            f"VIN {vin} ist im aktuell angemeldeten Konto {login_data['id']} nicht vorhanden."
        )
    return found, meta


def build_static_session_client(
    *,
    static_client: LeapmotorClient,
    login_data: dict[str, Any],
) -> LeapmotorClient:
    """Reuse the static app cert with the current session-derived HMAC material."""
    return LeapmotorClient(
        LeapmotorConfig(
            base_url=static_client.config.base_url,
            app_version=static_client.config.app_version,
            device_id=static_client.config.device_id,
            source=static_client.config.source,
            channel=static_client.config.channel,
            accept_language=static_client.config.accept_language,
            device_type=static_client.config.device_type,
            p12_enc_alg=static_client.config.p12_enc_alg,
            verify_tls=static_client.config.verify_tls,
            timeout_seconds=static_client.config.timeout_seconds,
            cert_file=static_client.config.cert_file,
            key_file=static_client.config.key_file,
            derived_sign_ikm=str(login_data["signIkm"]),
            derived_sign_salt=str(login_data["signSalt"]),
            derived_sign_info=str(login_data["signInfo"]),
        )
    )




















def normalize_vehicle_summary(
    *,
    vin: str,
    user_id: str,
    list_json: dict[str, Any],
    status_json: dict[str, Any],
    picture_json: dict[str, Any],
) -> dict[str, Any]:
    def to_bar(raw: Any) -> Any:
        if raw is None:
            return None
        try:
            return round(float(raw) / 100.0, 2)
        except (TypeError, ValueError):
            return None

    list_data = list_json.get("data") or {}
    vehicle_entry = None
    vehicle_bucket = None
    for bucket_name in ("bindcars", "sharedcars"):
        for entry in list_data.get(bucket_name, []) or []:
            if str(entry.get("vin")) == vin:
                vehicle_entry = entry
                vehicle_bucket = bucket_name
                break
        if vehicle_entry:
            break

    status_data = status_json.get("data") or {}
    signal = status_data.get("signal") or {}
    config = status_data.get("config") or {}
    charge_plan = config.get("3") or {}
    bt_config = config.get("4") or {}
    picture_data = picture_json.get("data") or {}
    parked_signal = signal.get("1298")

    return {
        "vehicle": {
            "vin": vin,
            "user_id": user_id,
            "car_id": vehicle_entry.get("carId") if vehicle_entry else None,
            "car_type": vehicle_entry.get("carType") if vehicle_entry else None,
            "nickname": vehicle_entry.get("nickName") if vehicle_entry else None,
            "is_shared": vehicle_bucket == "sharedcars",
        },
        "status": {
            "battery_percent": signal.get("1204"),
            "remaining_range_km": signal.get("3260"),
            "odometer_km": signal.get("1318"),
            "is_locked": signal.get("47") == 1 if signal.get("47") is not None else None,
            "is_parked": parked_signal == 1 if parked_signal is not None else None,
            "interior_temp_c": signal.get("1349"),
            "climate_set_temp_left_c": signal.get("2183"),
            "climate_set_temp_right_c": signal.get("2184"),
            "last_vehicle_timestamp": signal.get("sts"),
        },
        "location": {
            "latitude": signal.get("3725", signal.get("2190")),
            "longitude": signal.get("3724", signal.get("2191")),
            "privacy_gps": status_data.get("privacyGPS"),
            "privacy_data": status_data.get("privacyData"),
        },
        "charging": {
            "charge_limit_percent": charge_plan.get("percent"),
            "charging_planned_enabled": charge_plan.get("isEnable"),
            "charging_planned_start": charge_plan.get("beginTime"),
            "charging_planned_end": charge_plan.get("endTime"),
            "charging_target_percent": charge_plan.get("percent"),
        },
        "bluetooth": {
            "bluetooth_key_enabled_or_present": bool(bt_config),
            "bluetooth_mac": bt_config.get("mac"),
            "bluetooth_version": bt_config.get("version"),
        },
        "media": {
            "carpicture_key": picture_data.get("key"),
            "carpicture_url": picture_data.get("shareBindUrl"),
        },
        "diagnostics": {
            "tire_pressure_front_left_bar": to_bar(signal.get("2667")),
            "tire_pressure_front_right_bar": to_bar(signal.get("2653")),
            "tire_pressure_rear_left_bar": to_bar(signal.get("2646")),
            "tire_pressure_rear_right_bar": to_bar(signal.get("2660")),
        },
        "sources": {
            "vehicle_bucket": vehicle_bucket,
            "range_signal": "3260",
            "battery_signal": "1204",
            "odometer_signal": "1318",
            "lock_signal": "47",
            "parked_signal": "1298 (inferred from UI state 'Geparkt')",
            "interior_temp_signal": "1349",
            "climate_left_signal": "2183",
            "climate_right_signal": "2184",
            "charge_limit_source": "config.3.percent",
            "location_signals": {
                "longitude": "3724/2191",
                "latitude": "3725/2190",
            },
            "tire_pressure_signals": {
                "front_left_bar": "2667 (inferred from activity_lpcar_health.xml lf slot)",
                "front_right_bar": "2653 (inferred from activity_lpcar_health.xml rf slot)",
                "rear_left_bar": "2646 (inferred from activity_lpcar_health.xml lr slot)",
                "rear_right_bar": "2660 (inferred from activity_lpcar_health.xml rr slot)",
            },
            "status_endpoint": "/carownerservice/oversea/vehicle/v1/status/get/c10",
            "list_endpoint": "/carownerservice/oversea/vehicle/v1/list",
            "carpicture_endpoint": "/carownerservice/oversea/vehicle/v1/carpicture/key",
        },
    }


def build_replay_headers(
    *,
    sign: str,
    nonce: str,
    timestamp: str,
    token: str,
    user_id: str,
    content_type: str | None = None,
) -> dict[str, str]:
    headers = {
        "acceptLanguage": DEFAULT_LANGUAGE,
        "channel": DEFAULT_CHANNEL,
        "deviceType": DEFAULT_DEVICE_TYPE,
        "X-P12_ENC_ALG": DEFAULT_P12_ENC_ALG,
        "source": DEFAULT_SOURCE,
        "version": DEFAULT_APP_VERSION,
        "nonce": nonce,
        "deviceId": DEFAULT_DEVICE_ID,
        "timestamp": timestamp,
        "sign": sign,
        "userId": user_id,
        "token": token,
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def build_sign_mode_headers(
    client: LeapmotorClient,
    *,
    mode: str,
    nonce: str | None = None,
    timestamp: str | None = None,
) -> tuple[dict[str, str], str]:
    if mode == "legacy":
        return client.build_headers(
            nonce=nonce,
            timestamp=timestamp,
            include_device_type=True,
        )
    if mode == "time_offset":
        return client.build_headers(
            nonce=nonce,
            timestamp=timestamp,
            extra_suffix="timeOffset",
            include_device_type=False,
        )
    if mode == "double_device_id":
        return client.build_headers(
            nonce=nonce,
            timestamp=timestamp,
            extra_infix=client.config.device_id,
            include_device_type=False,
        )
    if mode == "double_device_id_device_type":
        return client.build_headers(
            nonce=nonce,
            timestamp=timestamp,
            extra_infix=client.config.device_id + client.config.device_type,
            include_device_type=False,
        )
    raise ValueError(f"Unbekannter sign mode: {mode}")


def build_login_form_body(
    *,
    username: str,
    password: str,
    policy_id: str,
    login_method: str,
    is_recover_acct: str,
) -> str:
    return (
        f"isRecoverAcct={is_recover_acct}"
        f"&password={requests.utils.quote(password, safe='')}"
        f"&policyId={requests.utils.quote(policy_id, safe='')}"
        f"&loginMethod={requests.utils.quote(login_method, safe='')}"
        f"&email={requests.utils.quote(username, safe='')}"
    )


def build_login_sign_input(
    *,
    client: LeapmotorClient,
    username: str,
    password: str,
    policy_id: str,
    login_method: str,
    is_recover_acct: str,
    nonce: str,
    timestamp: str,
) -> str:
    return "".join(
        [
            client.config.accept_language,
            client.config.device_type,
            client.config.device_id,
            login_method,
            username,
            is_recover_acct,
            login_method,
            nonce,
            password,
            policy_id,
            client.config.source,
            timestamp,
            client.config.app_version,
        ]
    )


def build_login_headers(
    *,
    client: LeapmotorClient,
    username: str,
    password: str,
    policy_id: str,
    login_method: str,
    is_recover_acct: str,
    nonce: str | None = None,
    timestamp: str | None = None,
) -> tuple[dict[str, str], str]:
    nonce = nonce or str(random.randint(100000, 9999999))
    timestamp = timestamp or str(int(time.time() * 1000))
    sign_input = build_login_sign_input(
        client=client,
        username=username,
        password=password,
        policy_id=policy_id,
        login_method=login_method,
        is_recover_acct=is_recover_acct,
        nonce=nonce,
        timestamp=timestamp,
    )
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "acceptLanguage": client.config.accept_language,
        "channel": client.config.channel,
        "deviceType": client.config.device_type,
        "X-P12_ENC_ALG": client.config.p12_enc_alg,
        "source": client.config.source,
        "version": client.config.app_version,
        "nonce": nonce,
        "deviceId": client.config.device_id,
        "timestamp": timestamp,
        "sign": hashlib.sha256(sign_input.encode("utf-8")).hexdigest(),
    }
    return headers, sign_input


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    config = LeapmotorConfig(
        base_url=args.base_url,
        app_version=args.app_version,
        device_id=args.device_id,
        sign_key_hex=args.sign_key_hex,
        verify_tls=args.verify_tls,
        cert_file=args.cert_file,
        key_file=args.key_file,
        derived_sign_ikm=args.derived_sign_ikm,
        derived_sign_salt=args.derived_sign_salt,
        derived_sign_info=args.derived_sign_info,
    )
    client = LeapmotorClient(config)

    if args.command == "sign-sample":
        headers, sign_input = client.build_headers(
            nonce=args.nonce,
            timestamp=args.timestamp,
            vin=args.vin,
            extra_prefix=args.extra_prefix,
            extra_infix=args.extra_infix,
            extra_suffix=args.extra_suffix,
            include_device_type=not args.omit_device_type,
        )
        print_json({"headers": headers, "sign_input": sign_input})
        return 0

    if args.command == "login":
        credentials = load_credentials(args)
        try:
            response, meta = client.login(credentials)
        except requests.exceptions.SSLError as exc:
            print_json(
                {
                    "error": "ssl_error",
                    "detail": str(exc),
                    "hint": "Teste erneut ohne --verify-tls oder mit passender CA-Kette.",
                }
            )
            return 2
        except requests.exceptions.RequestException as exc:
            print_json(
                {
                    "error": "request_failed",
                    "detail": str(exc),
                    "hint": "Aktueller Stand spricht fuer weitere TLS-/mTLS-/Transport-Huerden trotz korrekter sign-Berechnung.",
                }
            )
            return 3

        if args.dump_request:
            print_json({"request": meta})

        output: dict[str, Any] = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
        }
        try:
            output["json"] = response.json()
        except ValueError:
            output["text"] = response.text
        print_json(output)
        return 0

    if args.command == "login-form-curl":
        credentials = load_credentials(args)
        headers, sign_input = build_login_headers(
            client=client,
            username=credentials.username,
            password=credentials.password,
            policy_id=args.policy_id,
            login_method=args.login_method,
            is_recover_acct=args.is_recover_acct,
            nonce=args.nonce,
            timestamp=args.timestamp,
        )
        body = build_login_form_body(
            username=credentials.username,
            password=credentials.password,
            policy_id=args.policy_id,
            login_method=args.login_method,
            is_recover_acct=args.is_recover_acct,
        )
        if args.dump_request:
            print_json(
                {
                    "request": {
                        "headers": headers,
                        "sign_input": sign_input,
                        "body": body,
                    }
                }
            )
        result = client.replay_request_curl(
            path="/carownerservice/oversea/acct/v1/login",
            headers=headers,
            data=body,
        )
        result["request"] = {
            "headers": headers,
            "sign_input": sign_input,
            "body": body,
        }
        print_json(result)
        return 0

    if args.command == "decode-jwt":
        try:
            print_json(decode_jwt_payload(args.token))
        except (ValueError, json.JSONDecodeError) as exc:
            print_json({"error": "jwt_decode_failed", "detail": str(exc)})
            return 4
        return 0

    if args.command == "derive-sign-key":
        print_json(
            {
                "sign_key_hex": derive_sign_key(
                    ikm=args.ikm,
                    salt=args.salt,
                    info=args.info,
                ).hex()
            }
        )
        return 0


    if args.command == "acct-get-replay":
        response = client.replay_request(
            path="/carownerservice/oversea/acct/v1/get",
            headers=build_replay_headers(
                sign="10d29bdc0b30dc9991c856ebc3ee389aebeeb62b88edf755063ad8bb1a46d6b3",
                nonce="1667693",
                timestamp="1776593308181",
                token=args.token,
                user_id=args.user_id,
            ),
        )
        print_json({"status_code": response.status_code, "body": response.text})
        return 0

    if args.command == "device-save-replay":
        response = client.replay_request(
            path="/carownerservice/appDevice/deviceInfo/save",
            headers=build_replay_headers(
                sign="1d91c714e5d84d3d03b6c3f7f2aa16424208c435bb22a354e68bf436aa016c59",
                nonce="4231887",
                timestamp="1776593304835",
                token=args.token,
                user_id=args.user_id,
                content_type="application/x-www-form-urlencoded",
            ),
            data=args.body,
        )
        print_json({"status_code": response.status_code, "body": response.text})
        return 0

    if args.command == "acct-get-generated":
        headers, sign_input = build_sign_mode_headers(
            client,
            mode="legacy",
        )
        headers["userId"] = args.user_id
        headers["token"] = args.token
        response = client.replay_request(
            path="/carownerservice/oversea/acct/v1/get",
            headers=headers,
        )
        print_json(
            {
                "status_code": response.status_code,
                "sign_input": sign_input,
                "headers": headers,
                "body": response.text,
            }
        )
        return 0

    if args.command == "token-refresh-generated":
        headers, sign_input = build_sign_mode_headers(
            client,
            mode="legacy",
        )
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        headers["userId"] = args.user_id
        headers["token"] = args.token
        body = f"refreshToken={args.refresh_token}"
        response = client.replay_request(
            path="/carownerservice/oversea/acct/v1/token/refresh",
            headers=headers,
            data=body,
        )
        print_json(
            {
                "status_code": response.status_code,
                "sign_input": sign_input,
                "headers": headers,
                "body_sent": body,
                "body": response.text,
            }
        )
        return 0

    if args.command == "cert-sync-generated":
        headers, sign_input = build_sign_mode_headers(
            client,
            mode="legacy",
        )
        headers["userId"] = args.user_id
        headers["token"] = args.token
        response = client.replay_request(
            path="/carownerservice/oversea/vehicle/v1/cert/sync",
            headers=headers,
            data="",
        )
        print_json(
            {
                "status_code": response.status_code,
                "sign_input": sign_input,
                "headers": headers,
                "body": response.text,
            }
        )
        return 0

    if args.command == "device-save-generated":
        headers, sign_input = build_sign_mode_headers(client, mode=args.sign_mode)
        headers.update(
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "userId": args.user_id,
                "token": args.token,
            }
        )
        response = client.replay_request(
            path="/carownerservice/appDevice/deviceInfo/save",
            headers=headers,
            data=args.body,
        )
        print_json(
            {
                "status_code": response.status_code,
                "body": response.text,
                "request": {
                    "headers": headers,
                    "sign_input": sign_input,
                    "sign_mode": args.sign_mode,
                    "body": args.body,
                },
            }
        )
        return 0

    if args.command == "sync-generated":
        headers, sign_input = build_sign_mode_headers(client, mode=args.sign_mode)
        headers.update(
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "userId": args.user_id,
                "token": args.token,
            }
        )
        response = client.replay_request(
            path="/carownerservice/oversea/common/v1/sync",
            headers=headers,
            data=args.body,
        )
        print_json(
            {
                "status_code": response.status_code,
                "body": response.text,
                "request": {
                    "headers": headers,
                    "sign_input": sign_input,
                    "sign_mode": args.sign_mode,
                    "body": args.body,
                },
            }
        )
        return 0

    if args.command == "vehicle-list-generated":
        headers, sign_input = build_sign_mode_headers(
            client,
            mode="legacy",
        )
        headers.update(
            {
                "Content-Type": "application/json",
                "userId": args.user_id,
                "token": args.token,
            }
        )
        response = client.replay_request(
            path="/carownerservice/oversea/vehicle/v1/list",
            headers=headers,
            data="",
        )
        print_json(
            {
                "status_code": response.status_code,
                "sign_input": sign_input,
                "headers": headers,
                "body": response.text,
            }
        )
        return 0

    if args.command == "direct-login-vehicle-list":
        credentials = load_credentials(args)
        if not client.client_cert:
            raise SystemExit(
                "direct-login-vehicle-list braucht --cert-file/--key-file mit dem statischen App-Zertifikat."
            )
        static_client = client
        login_headers, login_sign_input = build_login_headers(
            client=static_client,
            username=credentials.username,
            password=credentials.password,
            policy_id="20260204",
            login_method="1",
            is_recover_acct="0",
        )
        login_body = build_login_form_body(
            username=credentials.username,
            password=credentials.password,
            policy_id="20260204",
            login_method="1",
            is_recover_acct="0",
        )
        login_result = static_client.replay_request_curl(
            path="/carownerservice/oversea/acct/v1/login",
            headers=login_headers,
            data=login_body,
        )
        login_json = {}
        try:
            login_json = json.loads(login_result["body"])
        except json.JSONDecodeError:
            pass
        if login_json.get("code") != 0:
            print_json(
                {
                    "login": login_result,
                    "error": "login_failed",
                }
            )
            return 2

        login_data = login_json["data"]
        cert_file, key_file = extract_account_p12_to_pem(
            login_data=login_data,
            provided_password=args.account_p12_password,
        )
        account_client = LeapmotorClient(
            LeapmotorConfig(
                base_url=static_client.config.base_url,
                app_version=static_client.config.app_version,
                device_id=derive_session_device_id(str(login_data["token"])),
                source=static_client.config.source,
                channel=static_client.config.channel,
                accept_language=static_client.config.accept_language,
                device_type=static_client.config.device_type,
                p12_enc_alg=static_client.config.p12_enc_alg,
                verify_tls=static_client.config.verify_tls,
                timeout_seconds=static_client.config.timeout_seconds,
                cert_file=cert_file,
                key_file=key_file,
                derived_sign_ikm=str(login_data["signIkm"]),
                derived_sign_salt=str(login_data["signSalt"]),
                derived_sign_info=str(login_data["signInfo"]),
            )
        )
        list_headers, list_sign_input = build_sign_mode_headers(
            account_client,
            mode="legacy",
        )
        list_headers.update(
            {
                "Content-Type": "application/json",
                "userId": str(login_data["id"]),
                "token": login_data["token"],
            }
        )
        list_response = account_client.replay_request(
            path="/carownerservice/oversea/vehicle/v1/list",
            headers=list_headers,
            data="",
        )
        print_json(
            {
                "login": {
                    "status_code": login_result["status_code"],
                    "request": {
                        "headers": login_headers,
                        "sign_input": login_sign_input,
                        "body": login_body,
                    },
                    "body": login_result["body"],
                },
                "vehicle_list": {
                    "status_code": list_response.status_code,
                    "request": {
                        "headers": list_headers,
                        "sign_input": list_sign_input,
                    },
                    "body": list_response.text,
                },
            }
        )
        return 0

    if args.command == "direct-login-vehicle-status":
        credentials = load_credentials(args)
        if not client.client_cert:
            raise SystemExit(
                "direct-login-vehicle-status braucht --cert-file/--key-file mit dem statischen App-Zertifikat."
            )
        static_client = client
        login_headers, login_sign_input = build_login_headers(
            client=static_client,
            username=credentials.username,
            password=credentials.password,
            policy_id="20260204",
            login_method="1",
            is_recover_acct="0",
        )
        login_body = build_login_form_body(
            username=credentials.username,
            password=credentials.password,
            policy_id="20260204",
            login_method="1",
            is_recover_acct="0",
        )
        login_result = static_client.replay_request_curl(
            path="/carownerservice/oversea/acct/v1/login",
            headers=login_headers,
            data=login_body,
        )
        login_json = {}
        try:
            login_json = json.loads(login_result["body"])
        except json.JSONDecodeError:
            pass
        if login_json.get("code") != 0:
            print_json(
                {
                    "login": login_result,
                    "error": "login_failed",
                }
            )
            return 2

        login_data = login_json["data"]
        cert_file, key_file = extract_account_p12_to_pem(
            login_data=login_data,
            provided_password=args.account_p12_password,
        )
        account_client = LeapmotorClient(
            LeapmotorConfig(
                base_url=static_client.config.base_url,
                app_version=static_client.config.app_version,
                device_id=derive_session_device_id(str(login_data["token"])),
                source=static_client.config.source,
                channel=static_client.config.channel,
                accept_language=static_client.config.accept_language,
                device_type=static_client.config.device_type,
                p12_enc_alg=static_client.config.p12_enc_alg,
                verify_tls=static_client.config.verify_tls,
                timeout_seconds=static_client.config.timeout_seconds,
                cert_file=cert_file,
                key_file=key_file,
                derived_sign_ikm=str(login_data["signIkm"]),
                derived_sign_salt=str(login_data["signSalt"]),
                derived_sign_info=str(login_data["signInfo"]),
            )
        )
        status_headers, status_sign_input = account_client.build_headers(
            vin=args.vin,
            include_device_type=True,
        )
        status_headers.update(
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "userId": str(login_data["id"]),
                "token": login_data["token"],
            }
        )
        status_result = account_client.replay_request_curl(
            path="/carownerservice/oversea/vehicle/v1/status/get/c10",
            headers=status_headers,
            data=f"vin={args.vin}",
        )
        print_json(
            {
                "login": {
                    "status_code": login_result["status_code"],
                    "request": {
                        "headers": login_headers,
                        "sign_input": login_sign_input,
                        "body": login_body,
                    },
                    "body": login_result["body"],
                },
                "vehicle_status": {
                    "status_code": status_result["status_code"],
                    "request": {
                        "headers": status_headers,
                        "sign_input": status_sign_input,
                        "body": f"vin={args.vin}",
                    },
                    "body": status_result["body"],
                },
            }
        )
        return 0

    if args.command == "direct-login-carpicture":
        credentials = load_credentials(args)
        if not client.client_cert:
            raise SystemExit(
                "direct-login-carpicture braucht --cert-file/--key-file mit dem statischen App-Zertifikat."
            )
        static_client = client
        login_headers, login_sign_input = build_login_headers(
            client=static_client,
            username=credentials.username,
            password=credentials.password,
            policy_id="20260204",
            login_method="1",
            is_recover_acct="0",
        )
        login_body = build_login_form_body(
            username=credentials.username,
            password=credentials.password,
            policy_id="20260204",
            login_method="1",
            is_recover_acct="0",
        )
        login_result = static_client.replay_request_curl(
            path="/carownerservice/oversea/acct/v1/login",
            headers=login_headers,
            data=login_body,
        )
        login_json = {}
        try:
            login_json = json.loads(login_result["body"])
        except json.JSONDecodeError:
            pass
        if login_json.get("code") != 0:
            print_json(
                {
                    "login": login_result,
                    "error": "login_failed",
                }
            )
            return 2

        login_data = login_json["data"]
        cert_file, key_file = extract_account_p12_to_pem(
            login_data=login_data,
            provided_password=args.account_p12_password,
        )
        account_client = LeapmotorClient(
            LeapmotorConfig(
                base_url=static_client.config.base_url,
                app_version=static_client.config.app_version,
                device_id=derive_session_device_id(str(login_data["token"])),
                source=static_client.config.source,
                channel=static_client.config.channel,
                accept_language=static_client.config.accept_language,
                device_type=static_client.config.device_type,
                p12_enc_alg=static_client.config.p12_enc_alg,
                verify_tls=static_client.config.verify_tls,
                timeout_seconds=static_client.config.timeout_seconds,
                cert_file=cert_file,
                key_file=key_file,
                derived_sign_ikm=str(login_data["signIkm"]),
                derived_sign_salt=str(login_data["signSalt"]),
                derived_sign_info=str(login_data["signInfo"]),
            )
        )
        body = f"deviceID={account_client.config.device_id}&vin={args.vin}"
        picture_headers, picture_sign_input = account_client.build_headers(
            vin=args.vin,
            extra_infix=account_client.config.device_id + account_client.config.device_type,
            include_device_type=False,
        )
        picture_headers.update(
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "userId": str(login_data["id"]),
                "token": login_data["token"],
            }
        )
        picture_result = account_client.replay_request_curl(
            path="/carownerservice/oversea/vehicle/v1/carpicture/key",
            headers=picture_headers,
            data=body,
        )
        print_json(
            {
                "login": {
                    "status_code": login_result["status_code"],
                    "request": {
                        "headers": login_headers,
                        "sign_input": login_sign_input,
                        "body": login_body,
                    },
                    "body": login_result["body"],
                },
                "carpicture": {
                    "status_code": picture_result["status_code"],
                    "request": {
                        "headers": picture_headers,
                        "sign_input": picture_sign_input,
                        "body": body,
                    },
                    "body": picture_result["body"],
                },
            }
        )
        return 0

    if args.command == "direct-login-vehicle-summary":
        credentials = load_credentials(args)
        if not client.client_cert:
            raise SystemExit(
                "direct-login-vehicle-summary braucht --cert-file/--key-file mit dem statischen App-Zertifikat."
            )
        login_data, login_meta, account_client = login_with_static_cert(
            static_client=client,
            credentials=credentials,
            account_p12_password=args.account_p12_password,
        )

        list_headers, list_sign_input = build_sign_mode_headers(account_client, mode="legacy")
        list_headers.update(
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "userId": str(login_data["id"]),
                "token": login_data["token"],
            }
        )
        list_result = account_client.replay_request_curl(
            path="/carownerservice/oversea/vehicle/v1/list",
            headers=list_headers,
            data="",
        )
        list_json = parse_json_body(list_result["body"])

        status_headers, status_sign_input = account_client.build_headers(
            vin=args.vin,
            include_device_type=True,
        )
        status_headers.update(
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "userId": str(login_data["id"]),
                "token": login_data["token"],
            }
        )
        status_result = account_client.replay_request_curl(
            path="/carownerservice/oversea/vehicle/v1/status/get/c10",
            headers=status_headers,
            data=f"vin={args.vin}",
        )
        status_json = parse_json_body(status_result["body"])

        picture_body = f"deviceID={account_client.config.device_id}&vin={args.vin}"
        picture_headers, picture_sign_input = account_client.build_headers(
            vin=args.vin,
            extra_infix=account_client.config.device_id + account_client.config.device_type,
            include_device_type=False,
        )
        picture_headers.update(
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "userId": str(login_data["id"]),
                "token": login_data["token"],
            }
        )
        picture_result = account_client.replay_request_curl(
            path="/carownerservice/oversea/vehicle/v1/carpicture/key",
            headers=picture_headers,
            data=picture_body,
        )
        picture_json = parse_json_body(picture_result["body"])

        print_json(
            {
                "summary": normalize_vehicle_summary(
                    vin=args.vin,
                    user_id=str(login_data["id"]),
                    list_json=list_json,
                    status_json=status_json,
                    picture_json=picture_json,
                ),
                "requests": {
                    "login": login_meta,
                    "vehicle_list": {
                        "status_code": list_result["status_code"],
                        "request": {
                            "headers": list_headers,
                            "sign_input": list_sign_input,
                            "body": "",
                        },
                        "body": list_result["body"],
                    },
                    "vehicle_status": {
                        "status_code": status_result["status_code"],
                        "request": {
                            "headers": status_headers,
                            "sign_input": status_sign_input,
                            "body": f"vin={args.vin}",
                        },
                        "body": status_result["body"],
                    },
                    "carpicture": {
                        "status_code": picture_result["status_code"],
                        "request": {
                            "headers": picture_headers,
                            "sign_input": picture_sign_input,
                            "body": picture_body,
                        },
                        "body": picture_result["body"],
                    },
                },
            }
        )
        return 0









































































































































































































































































































































































































































































































































































































    if args.command == "carpicture-generated":
        body_vin = ""
        for part in args.body.split("&"):
            if part.startswith("vin="):
                body_vin = part.split("=", 1)[1]
                break
        headers, sign_input = client.build_headers(
            vin=body_vin or None,
            extra_infix=client.config.device_id + client.config.device_type,
            include_device_type=False,
        )
        headers.update(
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "token": args.token,
            }
        )
        response = client.replay_request(
            path="/carownerservice/oversea/vehicle/v1/carpicture/key",
            headers=headers,
            data=args.body,
        )
        print_json(
            {
                "status_code": response.status_code,
                "body": response.text,
                "request": {
                    "headers": headers,
                    "sign_input": sign_input,
                    "body": args.body,
                },
            }
        )
        return 0

    if args.command == "vehicle-status-replay-curl":
        result = client.replay_request_curl(
            path="/carownerservice/oversea/vehicle/v1/status/get/c10",
            headers=build_replay_headers(
                sign=args.sign,
                nonce=args.nonce,
                timestamp=args.timestamp,
                token=args.token,
                user_id=args.user_id,
            ),
            data=f"vin={args.vin}",
        )
        print_json(result)
        return 0

    if args.command == "vehicle-status-generated-curl":
        headers, sign_input = client.build_headers(
            vin=args.vin,
            include_device_type=True,
        )
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["userId"] = args.user_id
        headers["token"] = args.token
        result = client.replay_request_curl(
            path="/carownerservice/oversea/vehicle/v1/status/get/c10",
            headers=headers,
            data=f"vin={args.vin}",
        )
        result["request"] = {
            "headers": headers,
            "sign_input": sign_input,
            "body": f"vin={args.vin}",
        }
        print_json(result)
        return 0

    parser.error(f"Unbekanntes Kommando: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
