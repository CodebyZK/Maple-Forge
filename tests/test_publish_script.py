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
    assert 'health.get(\'recordCount\') == $expected_count' in script
