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
    list_projects,
    ensure_project_dir,
    git,
    git_commit_push,
    resolve_project,
    project_dir,
    resolve_pubkeys,
    encrypt_file,
    decrypt_file
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

    cfg["age_pubkeys"] = [pubkey_path]
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
    for k, v in cfg.items():
        if k == "age_pubkeys":
            print(f"  {k}:")
            for pk in v:
                print(f"    - {pk}")
        else:
            print(f"  {k}: {v}")
    print()


def cmd_recipient(args):
    {
        "list": _recipient_list,
        "add": _recipient_add,
        "rm": _recipient_remove,
    }[args.recipient_cmd](args)

def _recipient_list(_args):
    cfg = load_config()
    pubkeys = cfg.get("age_pubkeys", [])

    if not pubkeys:
        info("No recipients configured.")
        return

    n_of_pubkeys = len(pubkeys)
    info(f"{n_of_pubkeys} recipient{'s' if n_of_pubkeys > 1 else ''}:")

    for i, pk in enumerate(pubkeys, 1):
        path = Path(pk).expanduser()
        label = path.read_text().strip() if path.exists() else pk

        print(f"  [{i}] {pk}")

        if path.exists():
            print(f"    -> {label}")
    print()

def _recipient_add(args):
    cfg = load_config()
    key = args.key.strip()
    path = Path(key).expanduser()

    if not path.exists() and not key.startswith("age1"):
        error(f"'{key}' is not a valid age1... key or existing .pub path.")

    pubkeys = cfg.get("age_pubkeys", [])
    if key in pubkeys:
        info("Recipient already in config.")
        return

    pubkeys.append(key)
    cfg["age_pubkeys"] = pubkeys

    save_config(cfg)
    success(f"Recipient added: {key}")
    warn("Run 'vaultsync env push' to re-encrypt for all recipients.")

def _recipient_remove(args):
    cfg = load_config()
    pubkeys = cfg.get("age_pubkeys", [])
    target = args.key.strip()

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
        error(f"Recipient '{target}' not found.")

    cfg["age_pubkeys"] = pubkeys

    save_config(cfg)

    success(f"Recipient removed: {removed}")
    warn("Run 'vaultsync env push' to re-encrypt without this recipient.")


def cmd_project(args):
    {
        "list":    _project_list,
        "create":  _project_create,
        "use":     _project_use,
        "current": _project_current,
    }[args.project_cmd](args)

def _project_list(_args):
    projects = list_projects()
    if not projects:
        info("No projects yet. Run 'vaultsync project create <name>'.")
        return

    current = Path(PROJECT_LINK).read_text().strip() if Path(PROJECT_LINK).exists() else None

    n_of_projects = len(projects)
    info(f"{n_of_projects} project{'s' if n_of_projects > 1 else ''}:")

    for p in projects:
        marker = " - current" if p == current else ""
        print(f"  {p}{marker}")
    print()

def _project_create(args):
    check_dependencies()

    cfg = load_config()
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

    success(f"Project '{name}' created.")
    use = input(f"Set '{name}' as current project in this directory? [Y/n]: ").strip().lower()

    if use != "n":
        Path(PROJECT_LINK).write_text(name)
        success(f"Current project set to '{name}'.")

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
    name = Path(env_path).name          # e.g. .env.production
    slug = name.lstrip(".")             # env.production
    return slug or "env"

def _env_push(args):
    check_dependencies()

    cfg = load_config()
    ensure_repo(cfg)

    project = resolve_project(args.project)
    ensure_project_dir(project)

    env_path = Path(args.env)
    if not env_path.exists():
        error(f"File not found: '{env_path}'")

    slug = _env_slug(args.env)

    enc_name = f"{slug}.age"
    enc_path = project_dir(project) / enc_name

    recipients = resolve_pubkeys(cfg)

    n_of_recipients = len(recipients)
    info(f"Encrypting '{env_path}' for {n_of_recipients} recipient{'s' if n_of_recipients > 1 else ''}...")
    encrypt_file(cfg, env_path, enc_path)

    rel_path = str(enc_path.relative_to(WORK_DIR))
    git("add", rel_path)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    pushed = git_commit_push(f"[{project}] update {enc_name} {ts}")
    if pushed:
        success(f"[{project}] '{args.env}' pushed as '{enc_name}'.")

def _env_pull(args):
    check_dependencies()

    cfg = load_config()
    ensure_repo(cfg)
    project = resolve_project(args.project)

    git("pull")

    slug = _env_slug(args.env)
    enc_path = project_dir(project) / f"{slug}.age"
    if not enc_path.exists():
        error(
            f"No '{slug}.age' found in project '{project}'.\n"
            f"  Push it first with: vaultsync env push --project {project} --env {args.env}"
        )

    content = decrypt_file(cfg, enc_path)

    dest = Path(args.env)
    dest.write_text(content)
    success(f"[{project}] '{slug}.age' pulled to '{dest}'.")

def _env_list(args):
    check_dependencies()

    cfg = load_config()
    ensure_repo(cfg)
    project = resolve_project(args.project)

    git("pull", "--quiet")

    proj_dir = project_dir(project)
    envs = sorted(f for f in proj_dir.iterdir() if f.suffix == ".age" and "credential" not in f.name)
    if not envs:
        print(f"No .env files in project '{project}'.")
        return

    print(f"\n[{project}] env files:\n")
    for f in envs:
        print(f"  {f.stem}")   # e.g. "env", "env.production"
    print()

def _env_diff(args):
    check_dependencies()

    cfg = load_config()
    ensure_repo(cfg)
    project = resolve_project(args.project)

    git("pull", "--quiet")

    slug = _env_slug(args.env)
    enc_path = project_dir(project) / f"{slug}.age"
    if not enc_path.exists():
        error(f"No '{slug}.age' found in project '{project}'.")

    remote = decrypt_file(cfg, enc_path)

    local_p = Path(args.env)
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
        "log", "--oneline", "--graph", "--decorate", "--", str(project_dir(project).relative_to(WORK_DIR))
    )


def cmd_credential(args):
    {
        "push": _credential_push,
        "pull": _credential_pull,
        "list": _credential_list,
    }[args.credential_cmd](args)

def _credential_filename(host: str) -> str:
    return f"credential-{host}.age"

def _credential_push(args):
    check_dependencies()

    cfg = load_config()
    ensure_repo(cfg)
    project = resolve_project(args.project)

    ensure_project_dir(project)

    host = args.host

    info(f"Reading credential for '{host}' from git credential store...")
    try:
        result = subprocess.run(
            ["git", "credential", "fill"],
            input=f"protocol=https\nhost={host}\n\n",
            capture_output=True,
            text=True,
            check=True,
        )
        cred_text = result.stdout.strip()
        if not cred_text:
            error(f"No credential returned for '{host}'.")
    except subprocess.CalledProcessError:
        error(
            f"No credential found for '{host}'.\n"
            f"  Make sure you've authenticated with Git at least once."
        )

    with tempfile.NamedTemporaryFile("w", suffix=".cred", delete=False) as tf:
        tf.write(cred_text)
        tmp = tf.name

    enc_name = _credential_filename(host)
    enc_path = project_dir(project) / enc_name

    try:
        recipients = resolve_pubkeys(cfg)

        n_of_recipients = len(recipients)

        info(f"Encrypting credential for {n_of_recipients} recipient{'s' if n_of_recipients > 1 else ''}...")
        encrypt_file(cfg, Path(tmp), enc_path)
    finally:
        os.unlink(tmp)

    rel = str(enc_path.relative_to(WORK_DIR))
    git("add", rel)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    pushed = git_commit_push(f"[{project}] update credential {host} {ts}")
    if pushed:
        success(f"[{project}] Credential for '{host}' pushed.")

def _credential_pull(args):
    check_dependencies()

    cfg = load_config()
    ensure_repo(cfg)
    project = resolve_project(args.project)

    git("pull")

    proj_dir = project_dir(project)
    cred_files = sorted(f for f in proj_dir.iterdir() if f.name.startswith("credential-"))
    if not cred_files:
        error(f"No credentials found in project '{project}'.")

    if len(cred_files) == 1:
        enc_path = cred_files[0]
    else:
        print(f"\nCredentials in '{project}':\n")
        for i, f in enumerate(cred_files, 1):
            host = f.stem.removeprefix("credential-")
            print(f"  [{i}] {host}")

        choice = input("\nSelect credential: ").strip()
        idx = int(choice) - 1 if choice.isdigit() else -1
        if not (0 <= idx < len(cred_files)):
            error("Invalid selection.")

        enc_path = cred_files[idx]

    cred_text = decrypt_file(cfg, enc_path)

    info("Loading credential into git credential store...")
    try:
        subprocess.run(
            ["git", "credential", "approve"],
            input=cred_text + "\n",
            text=True,
            check=True,
        )
        host = enc_path.stem.removeprefix("credential-")
        success(f"Credential for '{host}' loaded into git credential store.")

    except subprocess.CalledProcessError:
        error("Failed to load credential into git credential store.")

def _credential_list(args):
    check_dependencies()

    cfg = load_config()
    ensure_repo(cfg)

    project = resolve_project(args.project)
    git("pull", "--quiet")

    proj_dir = project_dir(project)
    creds = sorted(f for f in proj_dir.iterdir() if f.name.startswith("credential-"))
    if not creds:
        print(f"No credentials in project '{project}'.")
        return

    print(f"\n[{project}] credentials:\n")
    for f in creds:
        host = f.stem.removeprefix("credential-")
        print(f"  {host}")
    print()
