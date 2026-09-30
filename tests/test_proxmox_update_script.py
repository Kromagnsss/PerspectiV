from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_installer_exposes_update_command_after_customize() -> None:
    installer = (ROOT / "proxmox/install/perspectiv-install.sh").read_text(encoding="utf-8")
    customize_position = installer.index("\ncustomize\n")
    update_link_position = installer.index("ln -sfn /usr/local/sbin/perspectiv-update /usr/bin/update")
    assert "perspectiv-update.sh /usr/local/sbin/perspectiv-update" in installer
    assert update_link_position > customize_position


def test_updater_has_backup_healthcheck_and_rollback_guards() -> None:
    updater = (ROOT / "proxmox/scripts/perspectiv-update.sh").read_text(encoding="utf-8")
    required_fragments = [
        "flock -n 9",
        "releases/latest",
        "sha256sum",
        "pg_dump --format=custom",
        ".venv/bin/alembic upgrade head",
        "rollback()",
        "pg_restore --clean --if-exists",
        'curl -fsS --retry 15 --retry-delay 2 "${HEALTH_URL}"',
        "ln -sfn /usr/local/sbin/perspectiv-update /usr/bin/update",
    ]
    for fragment in required_fragments:
        assert fragment in updater


def test_community_update_function_bootstraps_standalone_updater() -> None:
    container_script = (ROOT / "proxmox/ct/perspectiv.sh").read_text(encoding="utf-8")
    assert "function update_script()" in container_script
    assert "proxmox/scripts/perspectiv-update.sh" in container_script
    assert '"${updater}" "$@"' in container_script
