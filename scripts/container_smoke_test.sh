#!/usr/bin/env sh
set -eu

test "$(id -u)" != "0"
command -v curl >/dev/null
command -v openssl >/dev/null

test ! -e /app/custom_components/leapmotor/app_cert.pem
test ! -e /app/custom_components/leapmotor/app_key.pem

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

openssl req \
  -x509 \
  -newkey rsa:2048 \
  -nodes \
  -subj /CN=container-smoke-test \
  -keyout "$tmp_dir/source-key.pem" \
  -out "$tmp_dir/source-cert.pem" \
  >/dev/null 2>&1

openssl pkcs12 \
  -export \
  -legacy \
  -in "$tmp_dir/source-cert.pem" \
  -inkey "$tmp_dir/source-key.pem" \
  -out "$tmp_dir/account.p12" \
  -passout pass:test \
  >/dev/null 2>&1

openssl pkcs12 \
  -legacy \
  -in "$tmp_dir/account.p12" \
  -clcerts \
  -nokeys \
  -out "$tmp_dir/extracted-cert.pem" \
  -passin pass:test

openssl pkcs12 \
  -legacy \
  -in "$tmp_dir/account.p12" \
  -nocerts \
  -nodes \
  -out "$tmp_dir/extracted-key.pem" \
  -passin pass:test

grep -q "BEGIN CERTIFICATE" "$tmp_dir/extracted-cert.pem"
grep -q "BEGIN PRIVATE KEY" "$tmp_dir/extracted-key.pem"

echo "container runtime smoke test passed"

# The non-root runtime must be able to persist per-vehicle sign memory.
test -w /app/state
python -c 'from leapmotor_to_abrp import save_state, load_state, state_path; from pathlib import Path; p = state_path("/app/state", "SMOKE"); save_state(p, {"lat_sign": -1}); assert load_state(p, "test")["lat_sign"] == -1; p.unlink()'
python leapmotor_to_abrp.py --help >/dev/null
