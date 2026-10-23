from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "repo-forensics"))

import forensics_core as core  # noqa: E402
import scan_integrity  # noqa: E402
import scan_openclaw_skills  # noqa: E402
import verify_install  # noqa: E402


def test_core_resolve_path_within_root_allows_in_root_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / ".forensicsignore"
    target.write_text("*.tmp\n", encoding="utf-8")

    assert core.resolve_path_within_root(str(repo), str(target)) == str(
        target.resolve()
    )
    assert core.load_ignore_patterns(str(repo)) == ["*.tmp"]


def test_core_resolve_path_within_root_refuses_parent_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside repo root"):
        core.resolve_path_within_root(str(repo), str(repo / ".." / outside.name))


def test_core_load_ignore_patterns_refuses_symlink_outside_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.ignore"
    outside.write_text("*.pem\n", encoding="utf-8")
    (repo / ".forensicsignore").symlink_to(outside)

    assert core.load_ignore_patterns(str(repo)) == []
    captured = capsys.readouterr()
    assert "Could not read .forensicsignore" in captured.out
    assert "outside repo root" in captured.out


def test_scan_openclaw_read_allows_in_root_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    skill = repo / "SKILL.md"
    skill.write_text("---\nname: demo\n---\n", encoding="utf-8")

    assert scan_openclaw_skills._read(str(repo), str(skill)) == "---\nname: demo\n---\n"


def test_scan_openclaw_read_refuses_parent_escape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "secret.md"
    outside.write_text("hidden\n", encoding="utf-8")

    assert (
        scan_openclaw_skills._read(str(repo), str(repo / ".." / outside.name)) is None
    )
    captured = capsys.readouterr()
    assert "Skipping out-of-root file" in captured.err
    assert "outside repo root" in captured.err


def test_scan_openclaw_read_refuses_symlink_outside_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "secret.md"
    outside.write_text("hidden\n", encoding="utf-8")
    skill = repo / "SKILL.md"
    skill.symlink_to(outside)

    assert scan_openclaw_skills._read(str(repo), str(skill)) is None
    captured = capsys.readouterr()
    assert "Skipping out-of-root file" in captured.err
    assert "outside repo root" in captured.err


def test_verify_install_sha256_file_allows_in_root_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "checksums.txt"
    payload = b"repo-forensics\n"
    target.write_bytes(payload)

    assert verify_install.sha256_file(str(target), str(repo)) == hashlib.sha256(
        payload
    ).hexdigest()


def test_verify_install_sha256_file_refuses_parent_escape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "payload.bin"
    outside.write_bytes(b"secret")

    assert verify_install.sha256_file(str(repo / ".." / outside.name), str(repo)) is None
    captured = capsys.readouterr()
    assert "Skipping out-of-root file" in captured.err
    assert "outside repo root" in captured.err


def test_verify_install_sha256_file_refuses_symlink_outside_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "payload.bin"
    outside.write_bytes(b"secret")
    link = repo / "payload.bin"
    link.symlink_to(outside)

    assert verify_install.sha256_file(str(link), str(repo)) is None
    captured = capsys.readouterr()
    assert "Skipping out-of-root file" in captured.err
    assert "outside repo root" in captured.err


def test_scan_integrity_find_critical_files_refuses_symlink_outside_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    commands_dir = repo / ".claude" / "commands"
    commands_dir.mkdir(parents=True)
    outside = tmp_path / "payload.md"
    outside.write_text("secret\n", encoding="utf-8")
    link = commands_dir / "payload.md"
    link.symlink_to(outside)

    critical_files, findings = scan_integrity.find_critical_files(str(repo))

    assert critical_files == {}
    assert len(findings) == 1
    assert findings[0].category == "integrity-containment"
    assert findings[0].file == ".claude/commands/payload.md"

    captured = capsys.readouterr()
    assert "Skipping out-of-root file" in captured.err
    assert "outside repo root" in captured.err


def test_scan_integrity_malformed_settings_json_is_not_reported_out_of_root(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")

    critical_files, findings = scan_integrity.find_critical_files(str(repo))

    # json.JSONDecodeError subclasses ValueError; it must not be mistaken for
    # the out-of-root ValueError, but a scanner must not pass silently either.
    assert [f.category for f in findings] == ["parse-error"]
    assert findings[0].file == ".claude/settings.json"
    assert findings[0].severity == "medium"
    assert "integrity-containment" not in {f.category for f in findings}
    assert ".claude/settings.json" in critical_files


def test_check_hooks_in_settings_reports_malformed_json(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    settings = repo / ".claude" / "settings.json"
    settings.write_text("{not json", encoding="utf-8")

    findings = scan_integrity.check_hooks_in_settings(
        str(repo), str(settings), ".claude/settings.json"
    )

    assert [f.category for f in findings] == ["parse-error"]
    assert findings[0].file == ".claude/settings.json"
    assert findings[0].severity == "medium"
