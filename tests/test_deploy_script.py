"""scripts/deploy.sh — pull-and-restart with no-op detection (issue #42) and
multi-instance, user-unit restart support (issue #47).

`git pull` can exit 0 without moving HEAD when a checkout's branch has no
upstream configured — the production incident issue #42 reports. These tests
run the script against a fully isolated temp git repo (never against this
checkout): it's copied into `<tmp>/scripts/deploy.sh` so the script's own
`ROOT` resolution lands on the temp repo, and every git operation talks to a
local bare "origin" under the same tmp_path. Most invocations pass
`--no-restart` so no `systemctl`/`sudo` call is ever made; the restart-path
tests below use a fake `systemctl` and `sudo` on `$PATH` instead — the real
production units are never touched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

DEPLOY_SCRIPT = Path(__file__).parent.parent / "scripts" / "deploy.sh"

# GIT_DIR/GIT_WORK_TREE (and friends) in the ambient test-runner environment
# could redirect a git command onto some other repo instead of the isolated
# tmp_path one — strip them so every subprocess in this file only ever sees
# the repo it was pointed at via `cwd`.
_GIT_REDIRECT_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_CEILING_DIRECTORIES")


def _sanitized_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_REDIRECT_VARS}
    env.update(extra)
    return env


def _install_poison_bin(tmp_path: Path) -> Path:
    """`systemctl`/`sudo` that fail loudly if invoked — for tests that never
    expect a restart at all (e.g. --no-restart), so a regression that reaches
    the restart code fails the test instead of silently invoking whatever
    systemctl/sudo happens to be on the real PATH."""
    bin_dir = tmp_path / "poison-bin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("systemctl", "sudo"):
        script = bin_dir / name
        script.write_text(
            f"#!/usr/bin/env bash\necho 'POISON: {name} must not be invoked here' >&2\nexit 99\n"
        )
        script.chmod(0o755)
    return bin_dir


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=_sanitized_env()
    )


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
    """Runs with a poison systemctl/sudo on PATH (see _install_poison_bin) so a
    regression that reaches the restart code fails loudly instead of quietly
    invoking whatever systemctl/sudo happens to be on the real PATH — every
    caller of this helper passes --no-restart or otherwise expects zero
    restarts."""
    script = _install_deploy_script(repo)
    poison_bin = _install_poison_bin(repo.parent)
    env = _sanitized_env(PATH=f"{poison_bin}:{os.environ['PATH']}")
    return subprocess.run(
        [str(script), "--no-restart", *extra_args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )


def _push_second_commit(tmp_path: Path) -> None:
    """Push a commit `repo` (from _init_repo_with_remote) hasn't fetched yet."""
    origin = tmp_path / "origin.git"
    other_clone = tmp_path / "other-clone"
    _git("clone", str(origin), str(other_clone), cwd=tmp_path)
    _configure_identity(other_clone)
    (other_clone / "README.md").write_text("hello again\n")
    _git("commit", "-am", "second commit", cwd=other_clone)
    _git("push", "origin", "main", cwd=other_clone)


def _install_fake_systemctl(tmp_path: Path, user_units: tuple[str, ...] = ()) -> tuple[Path, Path]:
    """A fake `systemctl` (and `sudo`, which just execs its argument directly —
    real `sudo` resets PATH via secure_path, which would bypass this fake and
    reach the real systemctl) on a directory meant to be prepended to PATH.

    Every invocation is appended to the returned log file. `systemctl --user
    cat NAME` (the auto-detect probe) succeeds only for names in `user_units`,
    standing in for whether a unit is visible to the user's systemd instance.
    """
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir(exist_ok=True)
    log_file = tmp_path / "systemctl.log"
    log_file.write_text("")

    units_list = " ".join(user_units)
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        f"""#!/usr/bin/env bash
echo "systemctl $*" >> "{log_file}"
if [[ "$1" == "--user" && "$2" == "cat" ]]; then
  for unit in {units_list}; do
    [[ "$unit" == "$3" ]] && exit 0
  done
  exit 1
fi
exit 0
"""
    )
    systemctl.chmod(0o755)

    sudo = bin_dir / "sudo"
    sudo.write_text(
        f"""#!/usr/bin/env bash
echo "sudo $*" >> "{log_file}"
exec "$@"
"""
    )
    sudo.chmod(0o755)

    return bin_dir, log_file


def _run_deploy_with_restart(
    repo: Path, bin_dir: Path, *extra_args: str
) -> subprocess.CompletedProcess:
    script = _install_deploy_script(repo)
    env = _sanitized_env(PATH=f"{bin_dir}:{os.environ['PATH']}")
    return subprocess.run(
        [str(script), *extra_args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
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


# --- issue #47: user-unit restart, multiple services, --service validation,
# and honoring the configured remote --------------------------------------


def test_deploy_service_flag_without_argument_is_a_usage_error(tmp_path):
    repo = _init_repo_with_remote(tmp_path)

    result = _run_deploy(repo, "--service")

    assert result.returncode == 2
    assert "requires" in result.stderr.lower()


def test_deploy_service_flag_followed_by_another_flag_is_a_usage_error(tmp_path):
    """`--service --user` must not silently take "--user" as a literal unit
    name (which would also leave --user's own effect never applied)."""
    repo = _init_repo_with_remote(tmp_path)

    result = _run_deploy(repo, "--service", "--user")

    assert result.returncode == 2
    assert "requires" in result.stderr.lower()


def test_deploy_auto_detects_user_unit_and_skips_sudo(tmp_path):
    repo = _init_repo_with_remote(tmp_path)
    _push_second_commit(tmp_path)
    bin_dir, log_file = _install_fake_systemctl(tmp_path, user_units=("whisper-relay",))

    result = _run_deploy_with_restart(repo, bin_dir, "--service", "whisper-relay")

    assert result.returncode == 0, result.stderr
    log = log_file.read_text()
    assert "systemctl --user restart whisper-relay" in log
    assert "sudo" not in log


def test_deploy_auto_detects_system_unit_and_uses_sudo(tmp_path):
    repo = _init_repo_with_remote(tmp_path)
    _push_second_commit(tmp_path)
    # No units registered as user units, so "whisper-relay" falls back to system scope.
    bin_dir, log_file = _install_fake_systemctl(tmp_path, user_units=())

    result = _run_deploy_with_restart(repo, bin_dir, "--service", "whisper-relay")

    assert result.returncode == 0, result.stderr
    log = log_file.read_text()
    assert "sudo systemctl restart whisper-relay" in log
    # N2: the fallback could equally mean "no user session bus reachable" as
    # "this really is a system unit" — say so and name the escape hatch,
    # rather than choosing system scope silently.
    assert "--user" in result.stderr


def test_deploy_explicit_user_flag_skips_auto_detection(tmp_path):
    """--user forces systemctl --user even for a unit the detection probe
    can't see — an operator who knows better shouldn't need the probe to agree."""
    repo = _init_repo_with_remote(tmp_path)
    _push_second_commit(tmp_path)
    bin_dir, log_file = _install_fake_systemctl(tmp_path, user_units=())

    result = _run_deploy_with_restart(repo, bin_dir, "--service", "whisper-relay", "--user")

    assert result.returncode == 0, result.stderr
    log = log_file.read_text()
    assert "systemctl --user restart whisper-relay" in log
    assert "sudo" not in log
    # --user must not even run the detection probe.
    assert "--user cat" not in log


def test_deploy_restarts_multiple_services_after_update(tmp_path):
    """Both production instances run from one checkout — a pull must restart
    every configured unit, not just the first (#47)."""
    repo = _init_repo_with_remote(tmp_path)
    _push_second_commit(tmp_path)
    bin_dir, log_file = _install_fake_systemctl(
        tmp_path, user_units=("whisper-relay", "whisper-relay-taylor")
    )

    result = _run_deploy_with_restart(
        repo, bin_dir, "--service", "whisper-relay", "--service", "whisper-relay-taylor"
    )

    assert result.returncode == 0, result.stderr
    log = log_file.read_text()
    assert "systemctl --user restart whisper-relay" in log
    assert "systemctl --user restart whisper-relay-taylor" in log


def test_deploy_restarts_no_services_after_noop_pull(tmp_path):
    repo = _init_repo_with_remote(tmp_path)
    bin_dir, log_file = _install_fake_systemctl(
        tmp_path, user_units=("whisper-relay", "whisper-relay-taylor")
    )

    result = _run_deploy_with_restart(
        repo, bin_dir, "--service", "whisper-relay", "--service", "whisper-relay-taylor"
    )

    assert result.returncode == 0, result.stderr
    assert "already up to date" in result.stdout
    log = log_file.read_text()
    assert "restart" not in log


def test_deploy_service_env_var_supports_multiple_space_separated_units(tmp_path):
    repo = _init_repo_with_remote(tmp_path)
    _push_second_commit(tmp_path)
    bin_dir, log_file = _install_fake_systemctl(
        tmp_path, user_units=("whisper-relay", "whisper-relay-taylor")
    )
    script = _install_deploy_script(repo)
    env = _sanitized_env(
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        DEPLOY_SYSTEMD_SERVICE="whisper-relay whisper-relay-taylor",
    )

    result = subprocess.run([str(script)], cwd=repo, capture_output=True, text=True, env=env)

    assert result.returncode == 0, result.stderr
    log = log_file.read_text()
    assert "systemctl --user restart whisper-relay" in log
    assert "systemctl --user restart whisper-relay-taylor" in log


def test_deploy_reads_deploy_systemd_service_from_dotenv_file(tmp_path):
    """N1: .env.example documents DEPLOY_SYSTEMD_SERVICE as a .env setting,
    but deploy.sh never actually read .env — an operator following the docs
    got only the single default unit restarted, silently missing the second
    instance (the exact multi-instance gap #47 exists to close). Deliberately
    no DEPLOY_SYSTEMD_SERVICE in the process environment: only the checkout's
    own .env file supplies it here, the same way a real deploy would see it."""
    repo = _init_repo_with_remote(tmp_path)
    _push_second_commit(tmp_path)
    (repo / ".env").write_text('DEPLOY_SYSTEMD_SERVICE="whisper-relay whisper-relay-taylor"\n')
    bin_dir, log_file = _install_fake_systemctl(
        tmp_path, user_units=("whisper-relay", "whisper-relay-taylor")
    )
    script = _install_deploy_script(repo)
    env = _sanitized_env(PATH=f"{bin_dir}:{os.environ['PATH']}")
    env.pop("DEPLOY_SYSTEMD_SERVICE", None)
    assert "DEPLOY_SYSTEMD_SERVICE" not in env

    result = subprocess.run([str(script)], cwd=repo, capture_output=True, text=True, env=env)

    assert result.returncode == 0, result.stderr
    log = log_file.read_text()
    assert "systemctl --user restart whisper-relay" in log
    assert "systemctl --user restart whisper-relay-taylor" in log


def test_deploy_explicit_service_flag_still_wins_over_dotenv_file(tmp_path):
    """--service on the command line must override DEPLOY_SYSTEMD_SERVICE
    from .env, not merge with or lose to it."""
    repo = _init_repo_with_remote(tmp_path)
    _push_second_commit(tmp_path)
    (repo / ".env").write_text('DEPLOY_SYSTEMD_SERVICE="whisper-relay whisper-relay-taylor"\n')
    bin_dir, log_file = _install_fake_systemctl(tmp_path, user_units=("only-this-one",))
    script = _install_deploy_script(repo)
    env = _sanitized_env(PATH=f"{bin_dir}:{os.environ['PATH']}")
    env.pop("DEPLOY_SYSTEMD_SERVICE", None)

    result = subprocess.run(
        [str(script), "--service", "only-this-one"],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    log = log_file.read_text()
    assert "systemctl --user restart only-this-one" in log
    assert "whisper-relay-taylor" not in log
    assert "restart whisper-relay\n" not in log and "restart whisper-relay " not in log


def test_deploy_fetches_from_the_branchs_configured_remote(tmp_path):
    """git fetch must honor the branch's actual configured remote, not a
    hardcoded 'origin' (#47) — proven here by a remote deliberately not
    named 'origin'."""
    upstream = tmp_path / "upstream.git"
    _git("init", "--bare", "-b", "main", str(upstream), cwd=tmp_path)

    repo = tmp_path / "clone"
    _git("clone", str(upstream), str(repo), cwd=tmp_path)
    _git("remote", "rename", "origin", "upstream", cwd=repo)
    _configure_identity(repo)
    (repo / "README.md").write_text("hello\n")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "initial commit", cwd=repo)
    _git("push", "upstream", "main", cwd=repo)
    _git("branch", "--set-upstream-to=upstream/main", "main", cwd=repo)

    other_clone = tmp_path / "other-clone"
    _git("clone", str(upstream), str(other_clone), cwd=tmp_path)
    _configure_identity(other_clone)
    (other_clone / "README.md").write_text("hello again\n")
    _git("commit", "-am", "second commit", cwd=other_clone)
    _git("push", "origin", "main", cwd=other_clone)  # other_clone's own remote is still "origin"

    result = _run_deploy(repo)

    assert result.returncode == 0, result.stderr
    assert "deployed update to" in result.stdout
