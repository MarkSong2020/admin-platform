#!/usr/bin/env bash
set -euo pipefail

workers="${1:-24}"
rounds="${2:-6}"
image="${MYSQL_PHASE0_IMAGE:-mysql:8.0}"
container="admin-platform-mysql-phase0-$(date +%s)-$$"

cleanup() {
  docker rm -f "${container}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Starting ${image} container: ${container}" >&2
docker run \
  --name "${container}" \
  -e MYSQL_ROOT_PASSWORD=app \
  -e MYSQL_DATABASE=mysql_phase0 \
  -p 127.0.0.1::3306 \
  -d "${image}" >/dev/null

ready_count=0
for _ in $(seq 1 90); do
  if docker exec "${container}" mysql -uroot -papp mysql_phase0 -e "SELECT VERSION();" >/dev/null 2>&1; then
    ready_count=$((ready_count + 1))
  else
    ready_count=0
  fi
  if [[ "${ready_count}" -ge 3 ]]; then
    break
  fi
  sleep 1
done

if [[ "${ready_count}" -lt 3 ]]; then
  echo "MySQL container did not become ready" >&2
  exit 1
fi

host_port="$(docker port "${container}" 3306/tcp | sed 's/.*://')"
if [[ -z "${host_port}" ]]; then
  echo "Failed to resolve mapped MySQL port" >&2
  exit 1
fi

echo "Running phase 0 PoC against 127.0.0.1:${host_port}" >&2
MYSQL_POC_ALLOW_SCHEMA_RESET=1 \
MYSQL_POC_DATABASE_URL="mysql+asyncmy://root:app@127.0.0.1:${host_port}/mysql_phase0" \
uv run --with asyncmy --with cryptography python scripts/mysql_phase0_poc.py \
  --workers "${workers}" \
  --rounds "${rounds}"
