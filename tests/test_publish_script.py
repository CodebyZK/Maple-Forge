from pathlib import Path


def test_atlas_publish_script_uses_release_symlink_and_rollback() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "publish-atlas-dataset.sh"
    ).read_text(encoding="utf-8")

    assert 'expected_sha' in script
    assert 'incoming parquet checksum does not match manifest' in script
    assert 'count < minimum' in script
    assert 'mv -Tf "$data_root/.current.next" "$current"' in script
    assert 'rollback' in script
    assert 'systemctl restart "$service_name"' in script
    assert 'health.get(\'recordCount\') == $expected_records' in script


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish-atlas-dataset.sh"


def test_publish_script_streams_checksum_and_cleans_up_incoming() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert ".read()).hexdigest()" not in script
    assert "sha.update(block)" in script
    assert script.count("cleanup_incoming\n") == 2
    assert '"$(realpath -m -- "$data_root/incoming")"/*' in script


def test_publish_script_health_check_uses_agreement_count() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'manifest["counts"].get("agreements")' in script
    assert "$expected_count" not in script


def test_publish_script_waits_for_health_and_reuses_matching_release() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'health_timeout=${MAPLE_ATLAS_HEALTH_TIMEOUT:-60}' in script
    assert 'for _ in $(seq 1 "$health_timeout"); do' in script
    assert "reuse_release=true" in script
    assert 'cmp -s "$manifest" "$release_dir/grants.manifest.json"' in script
    assert "release directory already exists with different content" in script
