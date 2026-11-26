# Bokklubben

A website for our book club, in Swedish. One container, SQLite persistence, passwordless email login.

## Features

- Members are created by an admin (name + email). Login is passwordless: a 6-digit code is emailed to the member's address (via your SMTP server, e.g. postfix on the same host).
- A spinning wheel (with each member's profile picture on its segment) picks who gets to choose the next 3 book candidates.
- The club votes on the candidates. The chooser's vote counts 1.5 points, everyone else's 1 point. A member who hasn't read a book loses voting power until they mark that they have read one.
- After the vote, the club picks a meeting date. When the meeting has come, each member marks whether they read the book; those who didn't lose voting power until they read a book in the club.
- The wheel only contains members who haven't chosen yet in the current cycle. When the pool is empty it resets and everyone is a candidate again. New members become wheel candidates after the next reset (but do have voting power from the start).
- Admins can retroactively fix mistakes: edit members, wheel pool, round state, chooser, candidates, votes, winner, meeting date and read marks.
- Profile pictures are uploaded by each member and stored in the persistent data volume.

## Run with Podman (quadlet) on Ubuntu

The image is published to GHCR by the GitHub Actions workflow in `.github/workflows/container.yml` on every push to `main` (and can be triggered manually via *Run workflow*).

1. Create the data directory **before** enabling the service (rootless podman does not create bind-mount sources itself; without it the service fails with `statfs /srv/bokklubben/data: no such file or directory`), then install the quadlet:

   ```bash
   sudo mkdir -p /srv/bokklubben/data
   sudo cp deploy/bokklubben.container ~/.config/containers/systemd/bokklubben.container
   ```

2. Edit `~/.config/containers/systemd/bokklubben.container` and set at least `SMTP_FROM` (and `SMTP_HOST`/`SMTP_PORT` if your postfix is not reachable as `host.containers.internal:25`). Optional: `SECRET_KEY`, `SMTP_USERNAME`/`SMTP_PASSWORD`, `SMTP_STARTTLS`.

3. Start it:

   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now bokklubben.container
   ```

   The site is then available on `http://localhost:8080` (change `PublishPort` if you like).

Data (SQLite database, uploaded avatars, secret key) lives in `/srv/bokklubben/data` and survives container recreation.

### Troubleshooting `podman pull ghcr.io/bananmellan/bokklubben:latest`

- The image only pulls anonymously if the **package** (not just the repo) is public: open https://github.com/bananmellan/bokklubben/pkgs/container/bokklubben → *Package settings* → *Change visibility* → **Public**. A private package makes ghcr return `401 unauthorized` for the anonymous token.
- If you ever ran `podman login ghcr.io` on the server (e.g. with an expired token), podman sends those stale credentials and ghcr rejects them with `invalid username/password: unauthorized` — even for public images. Fix: `podman logout ghcr.io` (add `sudo` if you pull with `sudo`; root and your user have separate auth files), then pull again.
- To pull with authentication instead (required when the repo/package is private): create a classic PAT at GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) with scope **`read:packages`**. With 2FA enabled the account password is never accepted — the PAT *is* the password. Then, on the server:
  ```bash
  podman login ghcr.io -u bananmellan --password-stdin < /path/to/tokenfile
  podman pull ghcr.io/bananmellan/bokklubben:latest
  ```
  Keep the token in a `chmod 600` file or env var; never commit it. Note that podman stores credentials per user: for a rootless quadlet (`systemctl --user`) log in as your user; for a root quadlet, use `sudo podman login ...`, or set `Environment=REGISTRY_AUTH_FILE=/path/to/auth.json` in the `.container` file to share one auth file.

## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `DATA_DIR` | `/data` in the container | Where the SQLite DB, uploads and secret key live (mount a volume here) |
| `SECRET_KEY` | generated and stored in `DATA_DIR` | Flask session signing key |
| `SMTP_HOST` | `localhost` | SMTP server for login codes |
| `SMTP_PORT` | `25` | SMTP port |
| `SMTP_FROM` | `bokklubben@localhost` | Sender address |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | unset | Optional SMTP auth |
| `SMTP_STARTTLS` | `false` | Use STARTTLS |
| `SMTP_TIMEOUT` | `10` | SMTP timeout (s) |
| `DEV_MODE` | `false` | If `true`, login codes are shown on the verify page instead of emailed (for local testing) |
| `MAX_AVATAR_BYTES` | `2097152` | Max profile picture size |

## Local development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
DEV_MODE=true DATA_DIR=./data python run.py   # http://127.0.0.1:8000
```

## Build the container image locally

```bash
podman build -t ghcr.io/bananmellan/bokklubben:latest -f Containerfile .
podman push ghcr.io/bananmellan/bokklubben:latest
```
