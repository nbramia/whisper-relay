"""scripts/deploy.sh — pull-and-restart with no-op detection (issue #42).

`git pull` can exit 0 without moving HEAD when a checkout's branch has no
upstream configured — the production incident this issue reports. These tests
run the script against a fully isolated temp git repo (never against this
checkout): it's copied into `<tmp>/scripts/deploy.sh` so the script's own
`ROOT` resolution lands on the temp repo, and every git operation talks to a
local bare "origin" under the same tmp_path. Every invocation passes
`--no-restart` so no `systemctl` call is ever made.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

DEPLOY_SCRIPT = Path(__file__).parent.parent / "scripts" / "deploy.sh"


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _configure_identity(repo: Path) -> None:
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)


def _init_repo_with_remote(tmp_path: Path) -> Path:
    """A bare 'origin' plus a clone tracking it, with one commit pushed."""
    origin = tmp_path / "origin.git"
    _git("init", "--bare", "-b", "main", str(origin), cwd=tmp_path)

    clone_dir = tmp_path / "clone"
    _git("clone", str(origin), str(clone_dir), cwd=tmp_path)
    _configure_identity(clone_dir)
    (clone_dir / "README.md").write_text("hello\n")
    _git("add", "README.md", cwd=clone_dir)
    _git("commit", "-m", "initial commit", cwd=clone_dir)
    _git("push", "origin", "main", cwd=clone_dir)

    return clone_dir


def _install_deploy_script(repo: Path) -> Path:
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    dest = scripts_dir / "deploy.sh"
    shutil.copy(DEPLOY_SCRIPT, dest)
    dest.chmod(0o755)
    return dest


def _run_deploy(repo: Path, *extra_args: str) -> subprocess.CompletedProcess:
    script = _install_deploy_script(repo)
    return subprocess.run(
        [str(script), "--no-restart", *extra_args],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def test_deploy_reports_already_up_to_date_on_noop_pull(tmp_path):
    repo = _init_repo_with_remote(tmp_path)

    result = _run_deploy(repo)

    assert result.returncode == 0, result.stderr
    assert "already up to date" in result.stdout
    assert "deployed update" not in result.stdout


def test_deploy_reports_and_applies_a_real_update(tmp_path):
    repo = _init_repo_with_remote(tmp_path)
    origin = tmp_path / "origin.git"

    # A second clone pushes a commit `repo` hasn't fetched yet.
    other_clone = tmp_path / "other-clone"
    _git("clone", str(origin), str(other_clone), cwd=tmp_path)
    _configure_identity(other_clone)
    (other_clone / "README.md").write_text("hello again\n")
    _git("commit", "-am", "second commit", cwd=other_clone)
    _git("push", "origin", "main", cwd=other_clone)

    before_sha = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()

    result = _run_deploy(repo)

    assert result.returncode == 0, result.stderr
    assert "deployed update to" in result.stdout
    assert "already up to date" not in result.stdout

    after_sha = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    assert after_sha != before_sha
    assert after_sha in result.stdout
    assert before_sha in result.stdout


def test_deploy_errors_when_branch_has_no_upstream(tmp_path):
    repo = _init_repo_with_remote(tmp_path)
    _git("branch", "--unset-upstream", cwd=repo)

    result = _run_deploy(repo)

    assert result.returncode != 0
    assert "no upstream" in result.stderr.lower()


def test_deploy_errors_in_detached_head(tmp_path):
    repo = _init_repo_with_remote(tmp_path)
    sha = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    _git("checkout", sha, cwd=repo)

    result = _run_deploy(repo)

    assert result.returncode != 0
    assert "detached head" in result.stderr.lower()


def test_deploy_never_restarts_with_no_restart_flag_even_on_update(tmp_path):
    """--no-restart must not shell out to systemctl at all — used here so the
    test suite never touches a real service, and asserted so a future edit
    can't quietly reintroduce an unconditional restart."""
    repo = _init_repo_with_remote(tmp_path)
    origin = tmp_path / "origin.git"
    other_clone = tmp_path / "other-clone"
    _git("clone", str(origin), str(other_clone), cwd=tmp_path)
    _configure_identity(other_clone)
    (other_clone / "README.md").write_text("hello again\n")
    _git("commit", "-am", "second commit", cwd=other_clone)
    _git("push", "origin", "main", cwd=other_clone)

    result = _run_deploy(repo)

    assert result.returncode == 0, result.stderr
    assert "restarting" not in result.stdout
    assert "restart" in result.stdout  # the "skipping service restart" line
