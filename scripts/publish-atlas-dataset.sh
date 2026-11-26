#!/usr/bin/env bash
# Publish a Forge release on the Atlas host.  This script runs *on that host*.
# It deliberately never writes to the live release until the incoming pair has
# passed its checks.  Release directories and the `current` symlink must live
# on the same filesystem for the symlink replacement to be atomic.
set -euo pipefail

incoming_dir=${1:?usage: publish-atlas-dataset.sh INCOMING_DIRECTORY}
data_root=${MAPLE_ATLAS_DATA_ROOT:-/srv/maple-atlas/data}
service_name=${MAPLE_ATLAS_SERVICE:-maple-data-api}
minimum_records=${MAPLE_ATLAS_MIN_RECORDS:-1000000}
health_url=${MAPLE_ATLAS_HEALTH_URL:-http://127.0.0.1:8000/health}
health_timeout=${MAPLE_ATLAS_HEALTH_TIMEOUT:-60}
parquet="$incoming_dir/grants.parquet"
manifest="$incoming_dir/grants.manifest.json"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# Each run uploads a full dataset copy into its own incoming directory. Remove
# it once it is published or found to be identical; failed uploads are kept
# for investigation. Only directories inside $data_root/incoming are removed.
cleanup_incoming() {
  local resolved
  resolved=$(realpath -e -- "$incoming_dir")
  [[ "$resolved" == "$(realpath -m -- "$data_root/incoming")"/* ]] \
    || fail "refusing to remove incoming directory outside $data_root/incoming: $resolved"
  rm -rf -- "$resolved"
}
[[ -f "$parquet" && -f "$manifest" ]] || fail "incoming parquet and manifest are required"
[[ "$minimum_records" =~ ^[1-9][0-9]*$ ]] || fail "MAPLE_ATLAS_MIN_RECORDS must be a positive integer"

# Do not trust CI artifact names.  Verify the pair and extract only values used
# for publication.  Python is already required by the Atlas data API host.
# expected_records is what the Data API reports as recordCount: the number of
# agreements (latest amendments) for Forge schema 2.0.0 and later, otherwise
# the accepted row count.
read -r expected_sha expected_records < <(python3 - "$manifest" "$minimum_records" <<'PY'
import hashlib
import json
import re
import sys

manifest_path, minimum = sys.argv[1], int(sys.argv[2])
with open(manifest_path, encoding="utf-8") as source:
    manifest = json.load(source)
try:
    source_meta = manifest["source"]
    artifact = manifest["artifacts"]["parquet"]
    count = manifest["counts"]["accepted"]
    digest = artifact["sha256"]
except (KeyError, TypeError) as error:
    raise SystemExit(f"manifest missing required release field: {error}")
if not isinstance(count, int) or count < minimum:
    raise SystemExit(f"accepted count {count!r} is below minimum {minimum}")
if artifact.get("row_count") != count:
    raise SystemExit("manifest parquet row count does not match accepted count")
if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
    raise SystemExit("manifest parquet checksum is invalid")
if not source_meta.get("source_url") or not source_meta.get("retrieved_at"):
    raise SystemExit("manifest source lineage is incomplete")
sha = hashlib.sha256()
# Stream the file: the dataset can be larger than the memory available.
with open(manifest_path.replace(".manifest.json", ".parquet"), "rb") as parquet:
    for block in iter(lambda: parquet.read(4 * 1024 * 1024), b""):
        sha.update(block)
if sha.hexdigest() != digest:
    raise SystemExit("incoming parquet checksum does not match manifest")
agreements = manifest["counts"].get("agreements")
if agreements is not None and (not isinstance(agreements, int) or agreements < 1):
    raise SystemExit(f"agreement count {agreements!r} is invalid")
print(digest, agreements if agreements is not None else count)
PY
) || fail "incoming dataset validation failed"

releases="$data_root/releases"
current="$data_root/current"
mkdir -p "$releases"

# A repeated scheduled run for identical input is intentionally a no-op.
if [[ -f "$current/grants.manifest.json" ]] && \
  python3 - "$current/grants.manifest.json" "$expected_sha" <<'PY'
import json, sys
try:
    actual = json.load(open(sys.argv[1], encoding="utf-8"))["artifacts"]["parquet"]["sha256"]
except (OSError, ValueError, KeyError, TypeError):
    raise SystemExit(1)
raise SystemExit(0 if actual == sys.argv[2] else 1)
PY
then
  printf 'Atlas already serves Forge dataset %s; no publication needed.\n' "$expected_sha"
  cleanup_incoming
  exit 0
fi

release="${expected_sha:0:16}"
release_dir="$releases/$release"
reuse_release=false
if [[ -e "$release_dir" ]]; then
  # A previous attempt that rolled back leaves its release behind. Reuse it
  # only if it holds exactly this dataset.
  if [[ "$(sha256sum "$release_dir/grants.parquet" 2>/dev/null | cut -d' ' -f1)" == "$expected_sha" ]] \
    && cmp -s "$manifest" "$release_dir/grants.manifest.json"; then
    reuse_release=true
  else
    fail "release directory already exists with different content: $release_dir"
  fi
fi

staging="$releases/.${release}.staged-$$"
previous_target=""
rollback() {
  if [[ -n "$previous_target" ]]; then
    ln -sfn "$previous_target" "$data_root/.current.rollback"
    mv -Tf "$data_root/.current.rollback" "$current"
    sudo -n systemctl restart "$service_name" || true
  fi
}

if [[ "$reuse_release" == false ]]; then
  mkdir "$staging"
  trap 'rm -rf "$staging"' EXIT
  install -m 0640 "$parquet" "$staging/grants.parquet"
  install -m 0640 "$manifest" "$staging/grants.manifest.json"
  mv "$staging" "$release_dir"
  trap - EXIT
fi

if [[ -L "$current" ]]; then
  previous_target=$(readlink "$current")
fi
ln -s "releases/$release" "$data_root/.current.next"
mv -Tf "$data_root/.current.next" "$current"

# The service reads the symlink when it starts.  Its Environment must point to
# $data_root/current/{grants.parquet,grants.manifest.json}; see deployment docs.
if ! sudo -n systemctl restart "$service_name"; then
  rollback
  fail "could not restart $service_name; restored the previous release"
fi
# The API reads the dataset during startup, so it is not listening the moment
# systemctl returns. Wait up to $health_timeout seconds for a matching health.
healthy() {
  curl --fail --silent --max-time 10 "$health_url" \
    | python3 -c "import json,sys; health=json.load(sys.stdin); sys.exit(0 if health.get('status') == 'ok' and health.get('recordCount') == $expected_records else 1)" \
    2>/dev/null
}
health_ok=false
for _ in $(seq 1 "$health_timeout"); do
  if healthy; then
    health_ok=true
    break
  fi
  sleep 1
done
if [[ "$health_ok" != true ]]; then
  rollback
  fail "health check failed; restored the previous release"
fi

cleanup_incoming
printf 'Published Atlas Forge dataset %s (%s records).\n' "$expected_sha" "$expected_records"
