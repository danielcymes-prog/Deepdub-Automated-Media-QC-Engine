"""Static invariants of the Windows deployment scripts (ADR-032).

PowerShell cannot execute in Linux CI, so these tests enforce the contract
textually: the script inventory the deployment doc promises, the security
regressions that already happened once (a service silently defaulting to
LocalSystem), and the orderings that protect data (backup before checkout
move). Real verification is the documented first install on the RDP host.
"""

import re
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts" / "windows"

RUNNABLE = ("install.ps1", "upgrade.ps1", "rollback.ps1", "status.ps1", "uninstall.ps1")


def read(name: str) -> str:
    return (SCRIPTS_DIR / name).read_text(encoding="utf-8")


class TestInventory:
    def test_documented_suite_exists(self) -> None:
        for name in (*RUNNABLE, "common.ps1"):
            assert (SCRIPTS_DIR / name).is_file(), f"missing {name}"

    def test_superseded_partial_installer_is_gone(self) -> None:
        assert not (SCRIPTS_DIR / "install-service.ps1").exists()

    @pytest.mark.parametrize("name", RUNNABLE)
    def test_scripts_fail_fast_and_share_helpers(self, name: str) -> None:
        text = read(name)
        assert "$ErrorActionPreference = 'Stop'" in text
        assert "common.ps1" in text


class TestServiceIdentity:
    """The predecessor script never set ObjectName, so NSSM's default —
    LocalSystem, the one identity the deployment spec forbids — silently
    applied. The installer must always assign an explicit identity."""

    def test_installer_sets_an_explicit_service_identity(self) -> None:
        text = read("install.ps1")
        assert re.search(r"NT SERVICE\\\$ServiceName", text)
        assert "ObjectName" in text and "obj=" in text

    def test_localsystem_never_assigned(self) -> None:
        for name in RUNNABLE:
            assert not re.search(r"(ObjectName|obj=)\s+\S*LocalSystem", read(name)), name

    def test_no_password_on_a_command_line(self) -> None:
        # Passwords reach NSSM only via Get-Credential prompt, never a param
        # default; params must not invite plaintext secrets.
        text = read("install.ps1")
        assert "Get-Credential" in text
        assert not re.search(r"\[string\]\$\w*[Pp]assword", text)


class TestUpgradeSafety:
    def test_database_backup_precedes_checkout_move(self) -> None:
        text = read("upgrade.ps1")
        assert text.index("Backup-Database") < text.index("reset --hard")

    def test_stop_precedes_backup(self) -> None:
        # A WAL-mode SQLite copied while the service writes is not a backup.
        text = read("upgrade.ps1")
        assert text.index("Stop-QcService") < text.index("Backup-Database")

    def test_untracked_files_survive(self) -> None:
        # reset --hard (tracked only), never clean -f: editor-created preset
        # drafts live untracked in the checkout until committed back.
        text = read("upgrade.ps1") + read("rollback.ps1")
        assert "git clean" not in text
        assert "reset --hard" in text

    def test_failed_upgrade_rolls_back_with_the_backup(self) -> None:
        text = read("upgrade.ps1")
        assert "rollback.ps1" in text
        assert "-DatabaseBackup" in text


class TestDataStewardship:
    def test_uninstall_keeps_evidence_by_default(self) -> None:
        text = read("uninstall.ps1")
        assert "-PurgeData" in text or "$PurgeData" in text
        assert "switch]$PurgeData" in text

    def test_runtime_sync_is_frozen_no_dev(self) -> None:
        assert "uv sync --frozen --no-dev" in read("common.ps1")

    def test_playwright_browsers_path_is_shared(self) -> None:
        # Playwright's per-user default location is invisible to the service
        # account; both the install step and the service env must pin it.
        text = read("install.ps1")
        assert text.count("PLAYWRIGHT_BROWSERS_PATH") >= 2
