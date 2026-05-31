# RouteBox

Minimal route manager for people who use **Coolify's Traefik reverse proxy** but also run services outside Coolify: on other VMs, LXCs, bare-metal boxes, NAS hosts, or normal Docker Compose stacks.

Coolify already owns Traefik, Let's Encrypt, ports 80/443 and the public entrypoints. This app edits a Traefik **dynamic config YAML** so you can add routes like:

```text
https://jellyfin.example.com  ->  http://192.168.1.115:8096
https://status.example.com    ->  http://192.168.1.113:3002
https://photos.example.com    ->  http://192.168.1.113:2283
```

without hand-editing `npm-import.yaml`.

## Features

- Cubic **Proxy Hosts** UI: domain(s), target host, target port, HTTP/HTTPS target scheme.
- Creates Traefik HTTP redirect router + HTTPS router + service automatically.
- Enable/disable routes without losing them.
- Live checks for public HTTPS source and internal TCP destination.
- Raw YAML viewer.
- Settings tab for YAML backend, Proxmox/SSH connection, Coolify URL/API token, and Traefik defaults.
- Settings can also be provided through Docker environment variables or `/data/settings.env`.
- Automatic timestamped backups before every write.
- Three deployment backends:
  - `local`: mount the dynamic YAML directly into the container.
  - `ssh`: edit a remote host file over SSH.
  - `proxmox`: SSH into a Proxmox node and edit a Coolify VM file via `qm guest exec`.

## When To Use This

Use this if:

- Coolify is already your public reverse proxy.
- You want to expose services not deployed by Coolify.
- A user/admin does not want to manually edit Traefik dynamic YAML.
- You want something similar to Nginx Proxy Manager, but without replacing Coolify's Traefik.

Do **not** use this to replace Coolify or Traefik. It only manages one dynamic config file.

## Quick Start: Same Host As Coolify

If this container runs on the Coolify host, mount the dynamic file directly:

```yaml
services:
  proxy-manager:
    image: ghcr.io/arturict/routebox:latest
    restart: unless-stopped
    ports:
      - "81:81"
    environment:
      BACKEND: local
      CONFIG_PATH: /config/npm-import.yaml
      ENTRYPOINT_HTTP: http
      ENTRYPOINT_HTTPS: https
      CERT_RESOLVER: letsencrypt
      REDIRECT_MIDDLEWARE: redirect-to-https
    volumes:
      - ./data:/data
      - /data/coolify/proxy/dynamic/npm-import.yaml:/config/npm-import.yaml
```

Open:

```text
http://<server-ip>:81
```

## Quick Start: Different VM, SSH Into Coolify Host

If the GUI runs on another VM, but can SSH into the Coolify VM/host:

```yaml
services:
  proxy-manager:
    image: ghcr.io/arturict/routebox:latest
    restart: unless-stopped
    ports:
      - "81:81"
    environment:
      BACKEND: ssh
      SSH_HOST: 192.168.1.101
      SSH_USER: root
      SSH_KEY: /ssh/id_ed25519
      REMOTE_CONFIG_PATH: /data/coolify/proxy/dynamic/npm-import.yaml
    volumes:
      - ./data:/data
      - ~/.ssh/id_ed25519:/ssh/id_ed25519:ro
```

## Quick Start: Proxmox Host → Coolify VM

If Coolify is inside a VM and you prefer going through Proxmox guest agent:

```yaml
services:
  proxy-manager:
    image: ghcr.io/arturict/routebox:latest
    restart: unless-stopped
    ports:
      - "81:81"
    environment:
      BACKEND: proxmox
      SSH_HOST: 192.168.1.200       # Proxmox node
      SSH_USER: root
      SSH_KEY: /ssh/id_ed25519
      PVE_VMID: "101"              # Coolify VMID
      REMOTE_CONFIG_PATH: /data/coolify/proxy/dynamic/npm-import.yaml
    volumes:
      - ./data:/data
      - ~/.ssh/id_ed25519:/ssh/id_ed25519:ro
```

Requirements for `BACKEND=proxmox`:

- SSH from the RouteBox container host to the Proxmox node.
- QEMU guest agent running inside the Coolify VM.
- Permission on the Proxmox node to run `qm guest exec <vmid> ...`.

## Coolify / Traefik Setup

This app assumes Coolify's Traefik dynamic provider loads a file like:

```text
/data/coolify/proxy/dynamic/npm-import.yaml
```

The generated YAML uses these defaults:

```yaml
http:
  routers:
    jellyfin-http:
      entryPoints: [http]
      middlewares: [redirect-to-https]
      service: jellyfin
      rule: Host(`jellyfin.example.com`)
    jellyfin-https:
      entryPoints: [https]
      service: jellyfin
      rule: Host(`jellyfin.example.com`)
      tls:
        certresolver: letsencrypt
  services:
    jellyfin:
      loadBalancer:
        servers:
          - url: http://192.168.1.115:8096
```

If your Coolify/Traefik uses different names, override:

| Variable | Default | Meaning |
|----------|---------|---------|
| `ENTRYPOINT_HTTP` | `http` | Traefik HTTP entrypoint |
| `ENTRYPOINT_HTTPS` | `https` | Traefik HTTPS entrypoint |
| `CERT_RESOLVER` | `letsencrypt` | Traefik cert resolver name |
| `REDIRECT_MIDDLEWARE` | `redirect-to-https` | Middleware for HTTP→HTTPS |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `81` | Web UI port inside container |
| `BACKEND` | `local` | `local`, `ssh`, or `proxmox` |
| `CONFIG_PATH` | `/config/dynamic.yml` | Local config path for `BACKEND=local` |
| `REMOTE_CONFIG_PATH` | same as `CONFIG_PATH` | Remote config path for `ssh`/`proxmox` |
| `STATE_FILE` | `/data/state.json` | Stores disabled routes and metadata |
| `BACKUP_DIR` | `/data/backups` | Stores config backups before writes |
| `ENV_FILE` | `/data/settings.env` | Optional env-style settings file written by the Settings tab |
| `SSH_HOST` | empty | SSH target for `ssh`/`proxmox` |
| `SSH_USER` | `root` | SSH username |
| `SSH_PORT` | `22` | SSH port |
| `SSH_KEY` | `/ssh/id_ed25519` | SSH private key inside container |
| `PVE_VMID` | empty | Coolify VM ID for `BACKEND=proxmox` |
| `ALLOW_PRIVATE_TARGETS` | `true` | Set `false` to block private/LAN targets |
| `COOLIFY_URL` | empty | Optional Coolify API base URL for Settings connection test |
| `COOLIFY_API_TOKEN` | empty | Optional Coolify API token. Leave blank in UI to keep the current token |

## Name And Icon Direction

The product name is **RouteBox**: short, neutral, and focused on routing rather
than AI or proxy jargon.

Icon direction: a minimal modern mark built from a flat cube/box outline with one
lime route segment entering and one small orange square exit node. It should have
no letters, no robot/AI motif, sharp geometric proportions, 4-6px corner radius,
and strong contrast so it works as a favicon, app sidebar mark, and GitHub avatar.

## Safety Notes

- Every write creates a backup under `/data/backups`.
- The app rewrites only the managed dynamic file, not Coolify's database.
- Keep this UI LAN-only or protect it behind auth/VPN. It can edit public routing.
- Mount a dedicated SSH key with the minimum permissions you can tolerate.

## Development

```bash
docker compose up --build
```

Then open `http://localhost:81`.

## License

MIT
