#!/usr/bin/env bash
# Smoke-test every keyless data source. Usage: ./scripts/check_sources.sh
pass=0; fail=0
chk(){
  local name="$1" url="$2"
  local code
  code=$(curl -sS -m 25 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null) || code=000
  if [ "$code" = "200" ]; then printf '  \033[32mOK  \033[0m %-34s %s\n' "$name" "$code"; pass=$((pass+1))
  else printf '  \033[31mFAIL\033[0m %-34s %s\n' "$name" "$code"; fail=$((fail+1)); fi
}
echo "Keyless data sources:"
chk "data.gov.sg 24h forecast"  "https://api-open.data.gov.sg/v2/real-time/api/twenty-four-hr-forecast"
chk "data.gov.sg rainfall"      "https://api-open.data.gov.sg/v2/real-time/api/rainfall"
chk "data.gov.sg catalog"       "https://api-production.data.gov.sg/v2/public/api/datasets?page=1"
chk "data.gov.sg datastore"     "https://data.gov.sg/api/action/datastore_search?resource_id=d_20e2fa37d1c8c19357a3f888487ab9f4&limit=1"
chk "data.gov.sg CSV download"  "https://api-open.data.gov.sg/v1/public/api/datasets/d_20e2fa37d1c8c19357a3f888487ab9f4/poll-download"
chk "Open-Meteo forecast"       "https://api.open-meteo.com/v1/forecast?latitude=1.35&longitude=103.82&hourly=temperature_2m&forecast_days=1"
chk "Open-Meteo marine"         "https://marine-api.open-meteo.com/v1/marine?latitude=1.26&longitude=103.8&hourly=wave_height&forecast_days=1"
chk "UN Comtrade preview"       "https://comtradeapi.un.org/public/v1/preview/C/A/HS?reporterCode=702&period=2023&cmdCode=TOTAL&flowCode=M"
chk "World Bank"                "https://api.worldbank.org/v2/country/SGP/indicator/NY.GDP.MKTP.CD?format=json&per_page=1"
chk "HDX / OCHA"                "https://data.humdata.org/api/3/action/package_search?q=food+security&rows=1"
echo "Known-unverified (expected to vary):"
chk "GDELT"                     "https://api.gdeltproject.org/api/v2/doc/doc?query=supply+chain&mode=artlist&maxrecords=1&format=json"
echo; echo "passed=$pass failed=$fail"
