import os
import subprocess
import tempfile

from pathlib import Path
from datetime import datetime
from .core import (
    CONFIG_FILE,
    PROJECT_LINK,
    WORK_DIR,
    check_dependencies,
    info,
    error,
    warn,
    success,
    run,
    save_config,
    load_config,
    ensure_repo,
    ensure_migrated,
    list_projects,
    ensure_project_dir,
    git,
    git_commit_push,
    resolve_project,
    project_dir,
    resolve_pubkeys,
    encrypt_file,
    decrypt_file,
)


def cmd_init(_args):
    check_dependencies()
    info("Setting up vaultsync...")

    cfg = {}
    cfg["repo_url"] = input("Git repo url: ").strip()
    if not cfg["repo_url"]:
        error("Repo URL is required.")

    default_key = str(Path.home() / ".ssh" / "age-key")
    key_input = input(f"Path to age private key [{default_key}]: ").strip()
    cfg["age_key"] = key_input or default_key

    default_pub = cfg["age_key"] + ".pub"
    pub_input = input(f"Path to age public key [{default_pub}]: ").strip()
    pubkey_path = pub_input or default_pub

    key_path = Path(cfg["age_key"]).expanduser()
    pub_path = Path(pubkey_path).expanduser()

    if not key_path.exists():
        should_generate_key = input("age key not found. Generate a new one? [Y/n]: ").strip().lower()
        if should_generate_key != "n":
            key_path.parent.mkdir(parents=True, exist_ok=True)

            result = run(
                ["age-keygen", "-o", str(key_path)],
                capture=True
            )

            pub_line = next(
                (line for line in result.stderr.splitlines() if line.startswith("Public key:")), ""
            )

            raw_pubkey = pub_line.replace("Public key:", "").strip()
            pub_path.write_text(f"{raw_pubkey}\n")

            success(f"age key generated at {key_path}")
            info(f"Public key: {raw_pubkey}")
            print(f"Now run on a already registered device: 'vaultsync recipient add {raw_pubkey}'")
        else:
            warn(f"Key not found at '{key_path}'. Decryption will fail until a valid key is present.")

    cfg["own_pubkey"] = pubkey_path
    cfg["projects"] = {}
    save_config(cfg)

    success(f"Config saved to {CONFIG_FILE}")

    try:
        ensure_repo(cfg)
        success("Repo cloned successfully.")
    except SystemExit:
        info("Could not clone repo - check SSH access to the server.")
        info("Run any command once the server is reachable.")


def cmd_config(_args):
    if not CONFIG_FILE.exists():
        error("No config found. Run 'vaultsync init' first.")

    cfg = load_config()

    info(f"Config ({CONFIG_FILE}):")
    print(f"  repo_url:   {cfg.get('repo_url', '(not set)')}")
    print(f"  age_key:    {cfg.get('age_key', '(not set)')}")
    print(f"  own_pubkey: {cfg.get('own_pubkey', '(not set)')}")

    projects = cfg.get("projects", {})
    if projects:
        print(f"  projects:")
        for proj, proj_cfg in projects.items():
            n = len(proj_cfg.get("age_pubkeys", []))
            print(f"    {proj}: {n} recipient{'s' if n != 1 else ''}")
    else:
        print("  projects: (none)")

    if "age_pubkeys" in cfg:
        print()
        warn("Config uses old format. Run 'vaultsync migrate' to upgrade.")
    print()


def cmd_migrate(_args):
    cfg = load_config()

    if "age_pubkeys" not in cfg:
        info("Config is already in the new format. Nothing to migrate.")
        return

    global_pubkeys = cfg.pop("age_pubkeys")
    own_pubkey = global_pubkeys[0] if global_pubkeys else None

    if own_pubkey:
        cfg["own_pubkey"] = own_pubkey

    cfg.setdefault("projects", {})

    projects = list_projects()
    for proj in projects:
        existing = cfg["projects"].get(proj, {}).get("age_pubkeys", [])
        merged = existing[:]
        for pk in global_pubkeys:
            if pk not in merged:
                merged.append(pk)
        cfg["projects"][proj] = {"age_pubkeys": merged}

    save_config(cfg)
    success("Migration complete.")
    info(f"own_pubkey: {own_pubkey}")
    for proj in projects:
        n = len(cfg["projects"][proj]["age_pubkeys"])
        info(f"{proj}: {n} recipient{'s' if n != 1 else ''}")


def cmd_recipient(args):
    {
        "list": _recipient_list,
        "add":  _recipient_add,
        "rm":   _recipient_remove,
    }[args.recipient_cmd](args)


def _recipient_list(args):
    cfg = load_config()
    ensure_migrated(cfg)
    project = resolve_project(getattr(args, "project", None))

    proj_cfg = cfg.get("projects", {}).get(project, {})
    pubkeys = proj_cfg.get("age_pubkeys", [])

    if not pubkeys:
        info(f"No recipients for project '{project}'.")
        return

    n = len(pubkeys)
    info(f"[{project}] {n} recipient{'s' if n > 1 else ''}:")

    for i, pk in enumerate(pubkeys, 1):
        path = Path(pk).expanduser()
        label = path.read_text().strip() if path.exists() else pk
        print(f"  [{i}] {pk}")
        if path.exists():
            print(f"    -> {label}")
    print()


def _recipient_add(args):
    cfg = load_config()
    ensure_migrated(cfg)
    key = args.key.strip()
    path = Path(key).expanduser()

    if not path.exists() and not key.startswith("age1"):
        error(f"'{key}' is not a valid age1... key or existing .pub path.")

    project = resolve_project(getattr(args, "project", None))

    proj_cfg = cfg.setdefault("projects", {}).setdefault(project, {"age_pubkeys": []})
    pubkeys = proj_cfg.setdefault("age_pubkeys", [])

    if key in pubkeys:
        info(f"Recipient already in project '{project}'.")
        return

    pubkeys.append(key)
    save_config(cfg)
    success(f"Recipient added to '{project}': {key}")
    warn(f"Run 'vaultsync env push --project {project}' to re-encrypt for all recipients.")


def _recipient_remove(args):
    cfg = load_config()
    ensure_migrated(cfg)
    target = args.key.strip()

    if getattr(args, "all_projects", False):
        if target.isdigit():
            error("Cannot use an index with --all-projects. Provide the full key.")

        removed_from = []
        for proj, proj_cfg in cfg.get("projects", {}).items():
            pubkeys = proj_cfg.get("age_pubkeys", [])
            if target in pubkeys:
                pubkeys.remove(target)
                proj_cfg["age_pubkeys"] = pubkeys
                removed_from.append(proj)

        if not removed_from:
            error(f"Recipient '{target}' not found in any project.")

        save_config(cfg)
        success(f"Recipient removed from: {', '.join(removed_from)}")
        warn("Re-encrypt all affected projects with 'vaultsync env push'.")
        return

    project = resolve_project(getattr(args, "project", None))
    proj_cfg = cfg.get("projects", {}).get(project, {})
    pubkeys = proj_cfg.get("age_pubkeys", [])

    removed = None
    if target.isdigit():
        idx = int(target) - 1
        if 0 <= idx < len(pubkeys):
            removed = pubkeys.pop(idx)
        else:
            error(f"Index {target} out of range.")
    elif target in pubkeys:
        pubkeys.remove(target)
        removed = target
    else:
        error(f"Recipient '{target}' not found in project '{project}'.")

    proj_cfg["age_pubkeys"] = pubkeys
    cfg["projects"][project] = proj_cfg
    save_config(cfg)

    success(f"Recipient removed from '{project}': {removed}")
    warn(f"Run 'vaultsync env push --project {project}' to re-encrypt without this recipient.")


def cmd_project(args):
    {
        "list":    _project_list,
        "create":  _project_create,
        "use":     _project_use,
        "current": _project_current,
        "rm":      _project_remove,
    }[args.project_cmd](args)


def _project_list(_args):
    projects = list_projects()
    if not projects:
        info("No projects yet. Run 'vaultsync project create <name>'.")
        return

    current = Path(PROJECT_LINK).read_text().strip() if Path(PROJECT_LINK).exists() else None

    n = len(projects)
    info(f"{n} project{'s' if n > 1 else ''}:")

    for p in projects:
        marker = " - current" if p == current else ""
        print(f"  {p}{marker}")
    print()


def _project_create(args):
    check_dependencies()

    cfg = load_config()
    ensure_migrated(cfg)
    ensure_repo(cfg)

    name = args.name.strip()
    if not name.isidentifier():
        error("Project name must be a valid identifier (letters, numbers, underscores).")

    proj_dir = ensure_project_dir(name)

    gitkeep = proj_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()
        git("add", str(gitkeep.relative_to(WORK_DIR)))
        git_commit_push(f"create project {name}")

    # Auto-add own public key as recipient for this project
    own = cfg.get("own_pubkey")
    if own:
        proj_cfg = cfg.setdefault("projects", {}).setdefault(name, {"age_pubkeys": []})
        pubkeys = proj_cfg.setdefault("age_pubkeys", [])
        if own not in pubkeys:
            pubkeys.append(own)
            save_config(cfg)

    success(f"Project '{name}' created.")
    use = input(f"Set '{name}' as current project in this directory? [Y/n]: ").strip().lower()

    if use != "n":
        Path(PROJECT_LINK).write_text(name)
        success(f"Current project set to '{name}'.")


def _project_remove(args):
    check_dependencies()

    cfg = load_config()
    ensure_migrated(cfg)
    ensure_repo(cfg)

    name = args.name.strip()
    projects = list_projects()
    if name not in projects:
        error(f"Project '{name}' does not exist.")

    confirm = input(f"Delete project '{name}' and all its secrets? This cannot be undone. [y/N]: ").strip().lower()
    if confirm != "y":
        info("Aborted.")
        return

    proj_dir = project_dir(name)
    git("rm", "-r", str(proj_dir.relative_to(WORK_DIR)))
    git_commit_push(f"delete project {name}")

    # Remove from config
    cfg.get("projects", {}).pop(name, None)
    save_config(cfg)

    # Clear .vaultsync-project if it points to this project
    link = Path(PROJECT_LINK)
    if link.exists() and link.read_text().strip() == name:
        link.unlink()
        info("Cleared active project link in current directory.")

    success(f"Project '{name}' deleted.")


def _project_use(args):
    projects = list_projects()
    if args.name not in projects:
        error(f"Project '{args.name}' does not exist.")

    Path(PROJECT_LINK).write_text(args.name)
    success(f"Current project set to '{args.name}'.")


def _project_current(_args):
    link = Path(PROJECT_LINK)

    if link.exists():
        print(f"Current project: {link.read_text().strip()}")
    else:
        print("No project set in this directory. Use 'vaultsync project use <name>'.")


def cmd_env(args):
    {
        "push": _env_push,
        "pull": _env_pull,
        "list": _env_list,
        "diff": _env_diff,
        "log":  _env_log,
    }[args.env_cmd](args)


def _env_slug(env_path: str) -> str:
    """Turn '.env' or '.env.production' into a safe filename slug."""
    name = Path(env_path).name
    slug = name.lstrip(".")
    return slug or "env"


def _slug_to_env(slug: str) -> str:
    """Turn 'env' or 'env.production' back into '.env' or '.env.production'."""
    return f".{slug}"


def _resolve_env_push(env_arg: str | None) -> str:
    """
    Resolve which local .env file to push.
    If --env was given, use it directly.
    If only one .env* file exists in cwd, use it.
    Otherwise prompt the user to pick one.
    """
    if env_arg is not None:
        return env_arg

    candidates = sorted(Path(".").glob(".env*"))
    candidates = [f for f in candidates if f.is_file()]

    if not candidates:
        error("No .env files found in the current directory. Use --env to specify one.")

    if len(candidates) == 1:
        return str(candidates[0])

    print("\nMultiple .env files found:")
    for i, f in enumerate(candidates, 1):
        print(f"  [{i}] {f}")
    choice = input("\nSelect file (name or number): ").strip()

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(candidates):
            return str(candidates[idx])
        error("Invalid selection.")
    elif Path(choice) in candidates or Path(f"./{choice}") in candidates:
        return choice
    else:
        error(f"File '{choice}' not found.")


def _resolve_env_vault(env_arg: str | None, project: str) -> str:
    """
    Resolve which vault .age slug to use for pull/diff.
    If --env was given, use it.
    If only one .age file exists in the project vault, use it.
    Otherwise prompt the user to pick one.
    Returns the local .env destination path (e.g. '.env' or '.env.production').
    """
    if env_arg is not None:
        return env_arg

    proj_dir = project_dir(project)
    age_files = sorted(f for f in proj_dir.iterdir() if f.suffix == ".age")

    if not age_files:
        error(f"No .env files found in project '{project}'. Push one first.")

    if len(age_files) == 1:
        return _slug_to_env(age_files[0].stem)

    print(f"\nMultiple env files in project '{project}':")
    for i, f in enumerate(age_files, 1):
        print(f"  [{i}] {_slug_to_env(f.stem)}")
    choice = input("\nSelect file (name or number): ").strip()

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(age_files):
            return _slug_to_env(age_files[idx].stem)
        error("Invalid selection.")

    # Accept either '.env.foo' or 'env.foo' or the slug directly
    normalized = choice.lstrip(".")
    for f in age_files:
        if f.stem == normalized:
            return _slug_to_env(f.stem)
    error(f"File '{choice}' not found in project '{project}'.")


def _env_push(args):
    check_dependencies()

    cfg = load_config()
    ensure_migrated(cfg)
    ensure_repo(cfg)

    project = resolve_project(args.project)
    ensure_project_dir(project)

    env_file = _resolve_env_push(args.env)
    env_path = Path(env_file)
    if not env_path.exists():
        error(f"File not found: '{env_path}'")

    slug = _env_slug(env_file)
    enc_name = f"{slug}.age"
    enc_path = project_dir(project) / enc_name

    recipients = resolve_pubkeys(cfg, project)
    n = len(recipients)
    info(f"Encrypting '{env_path}' for {n} recipient{'s' if n > 1 else ''}...")
    encrypt_file(cfg, env_path, enc_path, project)

    rel_path = str(enc_path.relative_to(WORK_DIR))
    git("add", rel_path)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    pushed = git_commit_push(f"[{project}] update {enc_name} {ts}")
    if pushed:
        success(f"[{project}] '{env_file}' pushed as '{enc_name}'.")


def _env_pull(args):
    check_dependencies()

    cfg = load_config()
    ensure_repo(cfg)
    project = resolve_project(args.project)

    git("pull")

    env_file = _resolve_env_vault(args.env, project)
    slug = _env_slug(env_file)
    enc_path = project_dir(project) / f"{slug}.age"
    if not enc_path.exists():
        error(
            f"No '{slug}.age' found in project '{project}'.\n"
            f"  Push it first with: vaultsync env push --project {project} --env {env_file}"
        )

    content = decrypt_file(cfg, enc_path)
    dest = Path(env_file)
    dest.write_text(content)
    success(f"[{project}] '{slug}.age' pulled to '{dest}'.")

    link = Path(PROJECT_LINK)
    if not link.exists():
        answer = input(f"Set '{project}' as current project in this directory? [Y/n]: ").strip().lower()
        if answer != "n":
            link.write_text(project)
            success(f"Current project set to '{project}'.")


def _env_list(args):
    check_dependencies()

    cfg = load_config()
    ensure_repo(cfg)
    project = resolve_project(args.project)

    git("pull", "--quiet")

    proj_dir = project_dir(project)
    envs = sorted(f for f in proj_dir.iterdir() if f.suffix == ".age")
    if not envs:
        print(f"No .env files in project '{project}'.")
        return

    print(f"\n[{project}] env files:\n")
    for f in envs:
        print(f"  {f.stem}")
    print()


def _env_diff(args):
    check_dependencies()

    cfg = load_config()
    ensure_repo(cfg)
    project = resolve_project(args.project)

    git("pull", "--quiet")

    env_file = _resolve_env_vault(args.env, project)
    slug = _env_slug(env_file)
    enc_path = project_dir(project) / f"{slug}.age"
    if not enc_path.exists():
        error(f"No '{slug}.age' found in project '{project}'.")

    remote = decrypt_file(cfg, enc_path)

    local_p = Path(env_file)
    if not local_p.exists():
        error(f"No local file at '{local_p}'.")

    local = local_p.read_text()

    if local == remote:
        success("Local file matches remote. No differences.")
        return

    with tempfile.NamedTemporaryFile("w", suffix=f".remote.{slug}", delete=False) as tf:
        tf.write(remote)
        tmp = tf.name

    try:
        subprocess.run(["git", "diff", "--no-index", "--color", tmp, str(local_p)])
    finally:
        os.unlink(tmp)


def _env_log(args):
    check_dependencies()

    cfg = load_config()
    ensure_repo(cfg)
    project = resolve_project(args.project)

    git("pull", "--quiet")
    git(
        "log", "--oneline", "--graph", "--decorate", "--",
        str(project_dir(project).relative_to(WORK_DIR))
    )
