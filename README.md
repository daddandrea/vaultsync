# vaultsync

A cross-platform CLI for syncing encrypted secrets via a private Git server.

Secrets (`.env` files, git credentials) are encrypted with [age](https://github.com/FiloSottile/age) before being committed to a private git repo. Each team member holds their own age private key and is added as a recipient — meaning any authorized device can decrypt, but the stored files are unreadable without a key.

## Requirements

- Python 3.10+
- [age](https://github.com/FiloSottile/age/releases)
- git

## Installation

```bash
pipx install .
```

To update after pulling changes:

```bash
git pull
pipx reinstall vaultsync
```

---

## Server Setup

The server is any always-on Linux machine hosting a bare git repo over SSH, reachable privately via [Tailscale](https://tailscale.com). Make sure Tailscale is installed and running on both the server and all client machines, and that SSH access from clients to the server is working.

### On the server

Create a bare git repo:

```bash
mkdir -p ~/vaultsync-repo.git
git init --bare ~/vaultsync-repo.git
```

### On each client machine

Authorize your SSH key on the server:

```bash
ssh-copy-id user@server.tail1234.ts.net
```

The repo URL to use during `vaultsync init` will be:

```
user@server.tail1234.ts.net:~/vaultsync-repo.git
```

---

## Quickstart

### First device

```bash
# 1. Initialize — enter repo URL, generate age keypair when prompted
vaultsync init

# 2. Create a project and set it as current
vaultsync project create myproject

# 3. Push your .env
vaultsync env push --project myproject

# 4. Push git credentials for a host
vaultsync credential push --project myproject --host github.com
```

### Adding a second device

```bash
# On the new device — initialize and note the printed public key (age1xxxx...)
vaultsync init
```

Back on the first device:

```bash
# Register the new device as a recipient
vaultsync recipient add age1xxxx...

# Re-encrypt and push so the new device can decrypt
vaultsync env push --project myproject
vaultsync credential push --project myproject --host github.com
```

Back on the new device:

```bash
# Pull everything
vaultsync project use myproject
vaultsync env pull --project myproject
vaultsync credential pull --project myproject
```

---

## Command Reference

### `vaultsync init`
Set up config, generate age keypair, and clone the vault repo.

---

### `vaultsync config`
Show the current global config (repo URL, age key path, recipients).

---

### `vaultsync recipient`

| Command | Description |
|---|---|
| `recipient list` | List all recipients and their keys |
| `recipient add <key>` | Add a recipient by `age1...` key or path to `.pub` file |
| `recipient rm <key\|index>` | Remove a recipient by key or list index |

After adding or removing a recipient, re-run `env push` on all projects to re-encrypt for the updated list.

---

### `vaultsync project`

| Command | Description |
|---|---|
| `project list` | List all projects |
| `project create <name>` | Create a new project |
| `project use <name>` | Set the active project for the current directory |
| `project current` | Show the active project |

Setting an active project with `project use` writes a `.vaultsync-project` file in the current directory, so you can omit `--project` from all subsequent commands.

---

### `vaultsync env`

| Command | Description |
|---|---|
| `env push [--project] [--env]` | Encrypt and push a `.env` file (default: `.env`) |
| `env pull [--project] [--env]` | Pull and decrypt a `.env` file |
| `env list [--project]` | List all `.env` files stored in a project |
| `env diff [--project] [--env]` | Diff local `.env` against the remote version |
| `env log [--project]` | Show git commit history for a project |

---

### `vaultsync credential`

| Command | Description |
|---|---|
| `credential push [--project] [--host]` | Encrypt and push credentials from the local git credential store (default host: `github.com`) |
| `credential pull [--project]` | Decrypt and load credentials into the local git credential store |
| `credential list [--project]` | List stored credentials in a project |

---

## What To Do When a Device Is Lost or Compromised

A lost device holds a private age key that can decrypt every secret it was a recipient of. You need to remove it as a recipient and re-encrypt everything immediately.

### 1. Remove the compromised device's public key

```bash
# List recipients and find the index of the lost device
vaultsync recipient list

# Remove it by index or by key
vaultsync recipient rm 2
```

### 2. Re-encrypt all secrets across all projects

For every project, re-push every `.env` and credential so the new ciphertext no longer includes the lost device as a recipient:

```bash
vaultsync env push --project myproject
vaultsync credential push --project myproject --host github.com
```

Repeat for each project.

### 3. Rotate the secrets themselves

Re-encrypting without the compromised key prevents future access, but if the device was already used to decrypt secrets before being lost, those values are exposed. You should:

- Rotate any leaked API keys, tokens, or passwords
- Regenerate `.env` values where possible
- Revoke the compromised GitHub token and issue a new one

### 4. Remove the device from Tailscale

```bash
# On any authorized machine
tailscale logout   # on the lost device if possible

# Or revoke it from the Tailscale admin console:
# https://login.tailscale.com/admin/machines
```
