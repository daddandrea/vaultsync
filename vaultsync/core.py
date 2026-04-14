import sys
import os
import shutil
import subprocess
import json
from pathlib import Path
from typing import NoReturn

CONFIG_DIR = Path.home() / ".vaultsync"
CONFIG_FILE = CONFIG_DIR / "config.json"
WORK_DIR = CONFIG_DIR / "repo"
PROJECT_LINK = ".vaultsync-project"


def success(msg: str):
    print(f"✓ {msg}")


def warn(msg: str):
    print(f"! {msg}")


def error(msg: str) -> NoReturn:
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(1)


def info(msg: str):
    print(f"  {msg}")


def is_windows() -> bool:
    return sys.platform == "win32"


def get_editor() -> str:
    return (
        os.environ.get("EDITOR")
        or os.environ.get("VISUAL")
        or ("notepad" if is_windows() else "vim")
    )


def check_dependencies():
    missing = [cmd for cmd in ("git", "age") if not shutil.which(cmd)]
    if missing:
        error(
            f"Missing required tools: {', '.join(missing)}\n"
            "  age: https://github.com/FiloSottile/age/releases\n"
            "  git: https://git-scm.com/downloads"
        )


def run(cmd: list[str], cwd=None, capture=False) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            check=True,
            capture_output=capture,
            text=True
        )
    except FileNotFoundError:
        error(f"Command not found: '{cmd[0]}'. Is it installed and on PATH?")
    except subprocess.CalledProcessError as e:
        if capture and e.stderr:
            print(e.stderr.strip(), file=sys.stderr)
        sys.exit(1)


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        error("No config file found. Run 'vaultsync init' first.")

    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except json.JSONDecodeError:
        error(f"Config file is corrupted: {CONFIG_FILE}")


def save_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def ensure_migrated(cfg: dict):
    """Error if config is still in the old global-recipients format."""
    if "age_pubkeys" in cfg:
        error(
            "Your config uses the old format.\n"
            "  Run 'vaultsync migrate' to upgrade to per-project recipients."
        )


def list_projects() -> list[str]:
    if not WORK_DIR.exists():
        return []
    return sorted(
        d.name for d in WORK_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )


def resolve_project(args_project: str | None) -> str:
    """
    Resolve project name from:
      1. --project flag
      2. .vaultsync-project file in cwd
      3. Interactive prompt
    """
    if args_project:
        return args_project

    link = Path(PROJECT_LINK)
    if link.exists():
        return link.read_text().strip()

    projects = list_projects()
    if not projects:
        error("No projects found. Run 'vaultsync project create <name>' first.")

    print("\nAvailable projects:")
    for i, p in enumerate(projects, 1):
        print(f"  [{i}] {p}")
    choice = input("\nSelect project (name or number): ").strip()

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(projects):
            return projects[idx]
        error("Invalid selection")
    elif choice in projects:
        return choice
    else:
        error(f"Project '{choice}' not found.")


def project_dir(project: str) -> Path:
    return WORK_DIR / project


def ensure_project_dir(project: str) -> Path:
    proj_dir = project_dir(project)
    proj_dir.mkdir(parents=True, exist_ok=True)
    return proj_dir


def ensure_repo(cfg: dict):
    if not (WORK_DIR / ".git").exists():
        info("Cloning vaultsync repo for the first time...")
        WORK_DIR.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", cfg["repo_url"], str(WORK_DIR)])


def git(*args, capture=False) -> subprocess.CompletedProcess:
    return run(["git", *args], cwd=WORK_DIR, capture=capture)


def git_commit_push(message: str) -> bool:
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=WORK_DIR
    )
    if diff.returncode == 0:
        info("No changes to push.")
        return False

    git("commit", "-m", message)
    git("push")
    return True


def resolve_pubkeys(cfg: dict, project: str) -> list[str]:
    project_cfg = cfg.get("projects", {}).get(project, {})
    entries = project_cfg.get("age_pubkeys", [])

    pubkeys = []
    for entry in entries:
        path = Path(entry).expanduser()
        if path.exists():
            pubkeys.append(path.read_text().strip())
        elif entry.startswith("age1"):
            pubkeys.append(entry.strip())
        else:
            warn(f"Could not resolve public key: {entry} - skipping.")

    if not pubkeys:
        error(
            f"No recipients found for project '{project}'.\n"
            f"  Run 'vaultsync recipient add <key> --project {project}' to add one."
        )
    return pubkeys


def recipient_args(cfg: dict, project: str) -> list[str]:
    args = []
    for key in resolve_pubkeys(cfg, project):
        args += ["-r", key]
    return args


def encrypt_file(cfg: dict, src: Path, dest: Path, project: str):
    run(
        ["age", *recipient_args(cfg, project), "-o", str(dest), str(src)]
    )


def decrypt_file(cfg: dict, src: Path) -> str:
    result = run(
        ["age", "-d", "-i", str(Path(cfg["age_key"]).expanduser()), str(src)],
        capture=True
    )
    return result.stdout


