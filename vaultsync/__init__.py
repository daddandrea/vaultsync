import argparse

from .commands import (
    cmd_init,
    cmd_config,
    cmd_migrate,
    cmd_recipient,
    cmd_project,
    cmd_env,
)


def main():
    parser = argparse.ArgumentParser(
        prog="vaultsync", description="CLI secrets manager via git + tailscale"
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    # -- Top level
    sub.add_parser(name="init", help="Set up config, keys, and clone repo")
    sub.add_parser(name="config", help="Show current global config")
    sub.add_parser(name="migrate", help="Migrate config to per-project recipients format")

    # -- Recipient
    rec_parser = sub.add_parser(
        name="recipient", help="Manage age recipients (who can decrypt)"
    )
    rec_sub = rec_parser.add_subparsers(dest="recipient_cmd", metavar="subcommand")
    rec_sub.required = True

    list_rec = rec_sub.add_parser(name="list", help="List recipients for a project")
    list_rec.add_argument("--project", "-p", help="Project name")

    add_rec = rec_sub.add_parser(
        name="add", help="Add a recipient (age1... key or .pub path)"
    )
    add_rec.add_argument("key")
    add_rec.add_argument("--project", "-p", help="Project name")

    rm_rec = rec_sub.add_parser(name="rm", help="Remove a recipient by key or by index")
    rm_rec.add_argument("key")
    rm_rec.add_argument("--project", "-p", help="Project name")
    rm_rec.add_argument(
        "--all-projects", action="store_true",
        help="Remove this recipient from every project"
    )

    # -- Project
    proj_parser = sub.add_parser(name="project", help="Manage projects")
    proj_sub = proj_parser.add_subparsers(dest="project_cmd", metavar="subcommand")
    proj_sub.required = True

    proj_sub.add_parser(name="list", help="List all projects")

    create_proj = proj_sub.add_parser(name="create", help="Create a new project")
    create_proj.add_argument("name")

    use_proj = proj_sub.add_parser(
        name="use", help="Set default project for current directory"
    )
    use_proj.add_argument("name")

    proj_sub.add_parser(name="current", help="Show the current project")

    rm_proj = proj_sub.add_parser(name="rm", help="Delete a project and all its secrets")
    rm_proj.add_argument("name")

    # -- Env
    env_parser = sub.add_parser("env", help="Manage .env files")
    env_sub = env_parser.add_subparsers(dest="env_cmd", metavar="subcommand")
    env_sub.required = True

    push_env = env_sub.add_parser("push", help="Encrypt and push a .env file")
    push_env.add_argument("--project", "-p", help="Project name")
    push_env.add_argument(
        "--env", "-e", default=".env", help="Path to .env file (default: .env)"
    )

    pull_env = env_sub.add_parser("pull", help="Pull and decrypt a .env file")
    pull_env.add_argument("--project", "-p", help="Project name")
    pull_env.add_argument(
        "--env", "-e", default=".env", help="Destination path (default: .env)"
    )

    list_env = env_sub.add_parser("list", help="List .env files in a project")
    list_env.add_argument("--project", "-p", help="Project name")

    diff_env = env_sub.add_parser("diff", help="Diff local .env against remote")
    diff_env.add_argument("--project", "-p", help="Project name")
    diff_env.add_argument("--env", "-e", default=".env")

    log_env = env_sub.add_parser("log", help="Show commit history for a project")
    log_env.add_argument("--project", "-p", help="Project name")

    # -- Parse and dispatch
    args = parser.parse_args()

    commands = {
        "init":      cmd_init,
        "config":    cmd_config,
        "migrate":   cmd_migrate,
        "recipient": cmd_recipient,
        "project":   cmd_project,
        "env":       cmd_env,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
