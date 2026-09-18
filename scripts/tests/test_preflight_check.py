import preflight_check

# ---- Found during a second, portability-focused bug-hunt pass ahead of a
# real Windows VM deployment: this script (the very first thing run on a
# new machine) had the same two POSIX-only assumptions already fixed once
# in agent5's runner.py, unfixed here.


def test_required_binaries_does_not_include_python3():
    # Nothing in this pipeline invokes a bare "python3" command anymore -
    # every agent uses sys.executable or a resolved venv path - and
    # "python3" isn't guaranteed to be on PATH on Windows (only python/py
    # typically are). This script itself running is proof Python works.
    assert "python3" not in preflight_check._required_binaries()


# ---- GIT_PROVIDER: which host CLI (gh vs glab) is required/checked.

def test_git_cli_is_gh_by_default(monkeypatch):
    monkeypatch.setattr(preflight_check, "GIT_PROVIDER", "github")
    assert preflight_check._git_cli() == "gh"
    assert "gh" in preflight_check._required_binaries()
    assert "glab" not in preflight_check._required_binaries()


def test_git_cli_is_glab_when_provider_is_gitlab(monkeypatch):
    monkeypatch.setattr(preflight_check, "GIT_PROVIDER", "gitlab")
    assert preflight_check._git_cli() == "glab"
    assert "glab" in preflight_check._required_binaries()
    assert "gh" not in preflight_check._required_binaries()


def test_venv_python_finds_posix_layout(tmp_path):
    venv_python = tmp_path / ".venv" / "bin" / "python3"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")

    assert preflight_check._venv_python(tmp_path) == venv_python


def test_venv_python_finds_windows_layout(tmp_path):
    venv_python = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")

    assert preflight_check._venv_python(tmp_path) == venv_python


def test_venv_python_returns_none_without_a_venv(tmp_path):
    assert preflight_check._venv_python(tmp_path) is None
