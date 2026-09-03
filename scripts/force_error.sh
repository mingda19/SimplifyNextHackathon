#!/usr/bin/env bash
# Trigger one deterministic Inventory Service domain error.
# Usage: bash scripts/force_error.sh <OUT_OF_STOCK|MOQ_NOT_MET|LEAD_TIME_EXCEEDED|LOT_EXPIRED|RATE_LIMIT>

set -euo pipefail

base_url="${INVENTORY_URL:-http://localhost:8000}"
scenario="$(printf '%s' "${1:-}" | tr '[:lower:]' '[:upper:]')"
headers_file="$(mktemp)"
body_file="$(mktemp)"
trap 'rm -f "$headers_file" "$body_file"' EXIT

usage() {
  echo "Usage: $0 <OUT_OF_STOCK|MOQ_NOT_MET|LEAD_TIME_EXCEEDED|LOT_EXPIRED|RATE_LIMIT>" >&2
  exit 2
}

request() {
  local url="$1"
  local payload="$2"
  local extra_header="${3:-}"
  local args=(
    -sS
    -D "$headers_file"
    -o "$body_file"
    -w '%{http_code}'
    -X POST
    -H 'Content-Type: application/json'
  )
  if [[ -n "$extra_header" ]]; then
    args+=(-H "$extra_header")
  fi
  curl "${args[@]}" "$url" -d "$payload"
}

assert_error() {
  local actual_status="$1"
  local expected_status="$2"
  local expected_code="$3"

  cat "$body_file"
  echo
  if [[ "$actual_status" != "$expected_status" ]]; then
    echo "Expected HTTP $expected_status, received $actual_status." >&2
    exit 1
  fi
  if ! grep -Eq "\"code\"[[:space:]]*:[[:space:]]*\"${expected_code}\"" "$body_file"; then
    echo "Expected domain code $expected_code." >&2
    exit 1
  fi
}

case "$scenario" in
  OUT_OF_STOCK|409)
    status_code="$(request \
      "$base_url/vendor/VENDOR-COMMUNITY/quote" \
      '{"sku":"MILK-UHT-1L","qty":100}')"
    assert_error "$status_code" 409 OUT_OF_STOCK
    ;;
  MOQ_NOT_MET|MOQ|400)
    status_code="$(request \
      "$base_url/vendor/VENDOR-HARVEST/quote" \
      '{"sku":"RICE-5KG","qty":200}')"
    assert_error "$status_code" 400 MOQ_NOT_MET
    ;;
  LEAD_TIME_EXCEEDED|LEAD_TIME|422)
    status_code="$(request \
      "$base_url/vendor/VENDOR-SLOW/quote" \
      '{"sku":"RICE-5KG","qty":250}')"
    assert_error "$status_code" 422 LEAD_TIME_EXCEEDED
    ;;
  LOT_EXPIRED|410)
    status_code="$(request \
      "$base_url/inventory/BEANS-CANNED-400G/allocate" \
      '{"lot_id":"LOT-BEANS-CANNED-400G-EXPIRED","qty":1}')"
    assert_error "$status_code" 410 LOT_EXPIRED
    ;;
  RATE_LIMIT|RATE_LIMITED|429)
    rate_key="force-error-$$-$(date +%s)"
    rate_header="X-Demo-Rate-Limit: $rate_key"
    status_code="$(request \
      "$base_url/vendor/VENDOR-RAPID/quote" \
      '{"sku":"RICE-5KG","qty":50}' \
      "$rate_header")"
    assert_error "$status_code" 429 RATE_LIMITED

    retry_after="$(tr -d '\r' < "$headers_file" | sed -n 's/^[Rr]etry-[Aa]fter:[[:space:]]*//p' | tail -n 1)"
    if [[ ! "$retry_after" =~ ^[1-9][0-9]*$ ]]; then
      echo "Missing or invalid Retry-After header." >&2
      exit 1
    fi

    sleep "$retry_after"
    retry_status="$(request \
      "$base_url/vendor/VENDOR-RAPID/quote" \
      '{"sku":"RICE-5KG","qty":50}' \
      "$rate_header")"
    if [[ "$retry_status" != "200" ]]; then
      cat "$body_file"
      echo
      echo "Expected the delayed retry to succeed; received HTTP $retry_status." >&2
      exit 1
    fi
    echo "Retry succeeded after ${retry_after}s."
    ;;
  *)
    usage
    ;;
esac
