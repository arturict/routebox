import base64
import copy
import datetime as dt
import errno
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import yaml
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static")

ENV_FILE = Path(os.environ.get("ENV_FILE", "/data/settings.env"))
SETTINGS_KEYS = [
    "APP_NAME",
    "BACKEND",
    "CONFIG_PATH",
    "REMOTE_CONFIG_PATH",
    "STATE_FILE",
    "BACKUP_DIR",
    "SSH_HOST",
    "SSH_USER",
    "SSH_PORT",
    "SSH_KEY",
    "SSH_STRICT_HOST_KEY_CHECKING",
    "PVE_VMID",
    "ENTRYPOINT_HTTP",
    "ENTRYPOINT_HTTPS",
    "CERT_RESOLVER",
    "REDIRECT_MIDDLEWARE",
    "ALLOW_PRIVATE_TARGETS",
    "COOLIFY_URL",
    "COOLIFY_API_TOKEN",
]


def _parse_env_file(path: Path) -> dict[str, str]:
    values = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


FILE_ENV = _parse_env_file(ENV_FILE)


def _cfg(key: str, default: str = "") -> str:
    return os.environ.get(key, FILE_ENV.get(key, default))


def _env_bool(value: str, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


APP_NAME = _cfg("APP_NAME", "RouteBox")
BACKEND = _cfg("BACKEND", "local").lower()
CONFIG_PATH = _cfg("CONFIG_PATH", "/config/dynamic.yml")
STATE_FILE = Path(_cfg("STATE_FILE", "/data/state.json"))
BACKUP_DIR = Path(_cfg("BACKUP_DIR", "/data/backups"))

SSH_HOST = _cfg("SSH_HOST", "")
SSH_USER = _cfg("SSH_USER", "root")
SSH_PORT = _cfg("SSH_PORT", "22")
SSH_KEY = _cfg("SSH_KEY", "/ssh/id_ed25519")
SSH_STRICT_HOST_KEY_CHECKING = _cfg("SSH_STRICT_HOST_KEY_CHECKING", "no").lower()

PVE_VMID = _cfg("PVE_VMID", "")
REMOTE_CONFIG_PATH = _cfg("REMOTE_CONFIG_PATH", CONFIG_PATH)

DEFAULT_ENTRYPOINT_HTTP = _cfg("ENTRYPOINT_HTTP", "http")
DEFAULT_ENTRYPOINT_HTTPS = _cfg("ENTRYPOINT_HTTPS", "https")
DEFAULT_CERT_RESOLVER = _cfg("CERT_RESOLVER", "letsencrypt")
REDIRECT_MIDDLEWARE = _cfg("REDIRECT_MIDDLEWARE", "redirect-to-https")
ALLOW_PRIVATE_TARGETS = _env_bool(_cfg("ALLOW_PRIVATE_TARGETS", "true"), True)
COOLIFY_URL = _cfg("COOLIFY_URL", "")
COOLIFY_API_TOKEN = _cfg("COOLIFY_API_TOKEN", "")


def _runtime_settings(include_secrets: bool = False) -> dict:
    return {
        "APP_NAME": APP_NAME,
        "BACKEND": BACKEND,
        "CONFIG_PATH": CONFIG_PATH,
        "REMOTE_CONFIG_PATH": REMOTE_CONFIG_PATH,
        "STATE_FILE": str(STATE_FILE),
        "BACKUP_DIR": str(BACKUP_DIR),
        "SSH_HOST": SSH_HOST,
        "SSH_USER": SSH_USER,
        "SSH_PORT": SSH_PORT,
        "SSH_KEY": SSH_KEY,
        "SSH_STRICT_HOST_KEY_CHECKING": SSH_STRICT_HOST_KEY_CHECKING,
        "PVE_VMID": PVE_VMID,
        "ENTRYPOINT_HTTP": DEFAULT_ENTRYPOINT_HTTP,
        "ENTRYPOINT_HTTPS": DEFAULT_ENTRYPOINT_HTTPS,
        "CERT_RESOLVER": DEFAULT_CERT_RESOLVER,
        "REDIRECT_MIDDLEWARE": REDIRECT_MIDDLEWARE,
        "ALLOW_PRIVATE_TARGETS": "true" if ALLOW_PRIVATE_TARGETS else "false",
        "COOLIFY_URL": COOLIFY_URL,
        "COOLIFY_API_TOKEN": COOLIFY_API_TOKEN if include_secrets else "",
        "COOLIFY_API_TOKEN_SET": bool(COOLIFY_API_TOKEN),
        "ENV_FILE": str(ENV_FILE),
    }


def _write_env_file(values: dict[str, str]):
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# RouteBox runtime settings", "# Environment variables from Docker/Compose override this file on container restart."]
    for key in SETTINGS_KEYS:
        if key in values and values[key] not in (None, ""):
            escaped = str(values[key]).replace('"', '\\"')
            lines.append(f'{key}="{escaped}"')
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _apply_runtime_settings(values: dict[str, str]):
    global FILE_ENV, APP_NAME, BACKEND, CONFIG_PATH, STATE_FILE, BACKUP_DIR
    global SSH_HOST, SSH_USER, SSH_PORT, SSH_KEY, SSH_STRICT_HOST_KEY_CHECKING
    global PVE_VMID, REMOTE_CONFIG_PATH, DEFAULT_ENTRYPOINT_HTTP, DEFAULT_ENTRYPOINT_HTTPS
    global DEFAULT_CERT_RESOLVER, REDIRECT_MIDDLEWARE, ALLOW_PRIVATE_TARGETS
    global COOLIFY_URL, COOLIFY_API_TOKEN

    current = _runtime_settings(include_secrets=True)
    for key in SETTINGS_KEYS:
        if key not in values:
            continue
        value = str(values.get(key) or "")
        if key == "COOLIFY_API_TOKEN" and not value:
            value = current.get("COOLIFY_API_TOKEN", "")
        current[key] = value
        os.environ[key] = value

    _write_env_file({key: current.get(key, "") for key in SETTINGS_KEYS})
    FILE_ENV = _parse_env_file(ENV_FILE)

    APP_NAME = current.get("APP_NAME") or "RouteBox"
    BACKEND = (current.get("BACKEND") or "local").lower()
    CONFIG_PATH = current.get("CONFIG_PATH") or "/config/dynamic.yml"
    STATE_FILE = Path(current.get("STATE_FILE") or "/data/state.json")
    BACKUP_DIR = Path(current.get("BACKUP_DIR") or "/data/backups")
    SSH_HOST = current.get("SSH_HOST") or ""
    SSH_USER = current.get("SSH_USER") or "root"
    SSH_PORT = current.get("SSH_PORT") or "22"
    SSH_KEY = current.get("SSH_KEY") or "/ssh/id_ed25519"
    SSH_STRICT_HOST_KEY_CHECKING = (current.get("SSH_STRICT_HOST_KEY_CHECKING") or "no").lower()
    PVE_VMID = current.get("PVE_VMID") or ""
    REMOTE_CONFIG_PATH = current.get("REMOTE_CONFIG_PATH") or CONFIG_PATH
    DEFAULT_ENTRYPOINT_HTTP = current.get("ENTRYPOINT_HTTP") or "http"
    DEFAULT_ENTRYPOINT_HTTPS = current.get("ENTRYPOINT_HTTPS") or "https"
    DEFAULT_CERT_RESOLVER = current.get("CERT_RESOLVER") or "letsencrypt"
    REDIRECT_MIDDLEWARE = current.get("REDIRECT_MIDDLEWARE") or "redirect-to-https"
    ALLOW_PRIVATE_TARGETS = _env_bool(current.get("ALLOW_PRIVATE_TARGETS", "true"), True)
    COOLIFY_URL = current.get("COOLIFY_URL") or ""
    COOLIFY_API_TOKEN = current.get("COOLIFY_API_TOKEN") or ""


class BackendError(RuntimeError):
    pass


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _ssh_base() -> list[str]:
    opts = [
        "ssh",
        "-p", str(SSH_PORT),
        "-i", SSH_KEY,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=8",
    ]
    if SSH_STRICT_HOST_KEY_CHECKING in {"no", "false", "0"}:
        opts.extend(["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"])
    return opts


def _run_remote(command: str, timeout: int = 30) -> str:
    if not SSH_HOST:
        raise BackendError("SSH_HOST is required for ssh/proxmox backends")

    if BACKEND == "proxmox":
        if not PVE_VMID:
            raise BackendError("PVE_VMID is required for BACKEND=proxmox")
        remote_cmd = f"qm guest exec {PVE_VMID} -- bash -lc {_shell_quote(command)}"
    else:
        remote_cmd = command

    result = subprocess.run(
        [*_ssh_base(), f"{SSH_USER}@{SSH_HOST}", remote_cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise BackendError(result.stderr.strip() or result.stdout.strip() or "remote command failed")

    if BACKEND != "proxmox":
        return result.stdout

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BackendError(f"invalid qm guest exec response: {exc}") from exc
    if payload.get("exitcode", 1) != 0:
        raise BackendError(payload.get("err-data") or payload.get("out-data") or "guest command failed")
    return payload.get("out-data", "")


def _read_text() -> str:
    if BACKEND == "local":
        path = Path(CONFIG_PATH)
        return path.read_text() if path.exists() else ""
    return _run_remote(f"cat {_shell_quote(REMOTE_CONFIG_PATH)} 2>/dev/null || true")


def _write_text(content: str):
    if BACKEND == "local":
        path = Path(CONFIG_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            os.replace(tmp_path, path)
        except OSError as exc:
            # Replacing a file bind-mounted into the container can fail with
            # EBUSY. Keep the write working for the common Docker Compose
            # `host-file:/config/dynamic.yml` setup by falling back to an
            # in-place truncate/write after the temp file has been fully written.
            if exc.errno != errno.EBUSY:
                Path(tmp_path).unlink(missing_ok=True)
                raise
            path.write_text(content, encoding="utf-8")
            Path(tmp_path).unlink(missing_ok=True)
        return

    encoded = base64.b64encode(content.encode()).decode()
    command = (
        f"mkdir -p {_shell_quote(str(Path(REMOTE_CONFIG_PATH).parent))} && "
        f"tmp=$(mktemp) && printf %s {_shell_quote(encoded)} | base64 -d > $tmp && "
        f"mv $tmp {_shell_quote(REMOTE_CONFIG_PATH)}"
    )
    _run_remote(command)


def _backup_current():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    target = BACKUP_DIR / f"dynamic-{stamp}.yml"
    current = _read_text()
    target.write_text(current, encoding="utf-8")
    backups = sorted(BACKUP_DIR.glob("dynamic-*.yml"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[30:]:
        old.unlink(missing_ok=True)
    return str(target)


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _empty_config() -> dict:
    return {"http": {"routers": {}, "services": {}}}


def load_config() -> dict:
    raw = _read_text()
    data = yaml.safe_load(raw) if raw.strip() else _empty_config()
    if not isinstance(data, dict):
        data = _empty_config()
    data.setdefault("http", {})
    data["http"].setdefault("routers", {})
    data["http"].setdefault("services", {})
    return data


def save_config(data: dict):
    _backup_current()
    _write_text(yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True))


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower()).strip("-")
    return re.sub(r"-+", "-", slug) or "proxy-host"


def _domains(rule: str) -> list[str]:
    return re.findall(r"Host\(`([^`]+)`\)", rule or "")


def _service_url(service: dict) -> str:
    servers = service.get("loadBalancer", {}).get("servers", [])
    if not servers:
        return ""
    return servers[0].get("url", "") or ""


def _parse_url(url: str) -> tuple[str, str, str]:
    parsed = urlparse(url if "://" in url else f"http://{url}")
    scheme = parsed.scheme or "http"
    host = parsed.hostname or ""
    port = str(parsed.port or (443 if scheme == "https" else 80))
    return scheme, host, port


def parse_proxy_hosts(data: dict) -> list[dict]:
    routers = data.get("http", {}).get("routers", {}) or {}
    services = data.get("http", {}).get("services", {}) or {}
    hosts = {}
    for router_name, router_cfg in routers.items():
        service_name = router_cfg.get("service")
        if not service_name or service_name not in services:
            continue
        domains = _domains(router_cfg.get("rule", ""))
        if not domains:
            continue
        scheme, forward_host, forward_port = _parse_url(_service_url(services[service_name]))
        existing = hosts.get(service_name, {})
        hosts[service_name] = {
            "id": service_name,
            "domains": sorted(set([*existing.get("domains", []), *domains])),
            "scheme": scheme,
            "forward_host": forward_host,
            "forward_port": forward_port,
            "enabled": True,
            "source_online": None,
            "dest_online": None,
        }
    return list(hosts.values())


def build_config_from_hosts(hosts: list[dict], disabled_ids: set[str]) -> dict:
    routers = {}
    services = {}
    for host in hosts:
        service_id = _slug(host["id"])
        if service_id in disabled_ids:
            continue
        domains = [d.strip().lower() for d in host.get("domains", []) if d.strip()]
        if not domains:
            continue
        rule = " || ".join(f"Host(`{domain}`)" for domain in domains)
        routers[f"{service_id}-http"] = {
            "entryPoints": [DEFAULT_ENTRYPOINT_HTTP],
            "middlewares": [REDIRECT_MIDDLEWARE],
            "service": service_id,
            "rule": rule,
        }
        routers[f"{service_id}-https"] = {
            "entryPoints": [DEFAULT_ENTRYPOINT_HTTPS],
            "service": service_id,
            "rule": rule,
            "tls": {"certresolver": DEFAULT_CERT_RESOLVER},
        }
        url = f"{host.get('scheme', 'http')}://{host['forward_host']}:{host['forward_port']}"
        services[service_id] = {"loadBalancer": {"servers": [{"url": url}]}}
    return {"http": {"routers": routers, "services": services}}


def _all_hosts() -> list[dict]:
    state = _load_state()
    disabled = set(state.get("disabled", []))
    merged = {}
    for host in state.get("all_hosts", []):
        if isinstance(host, dict) and host.get("id"):
            merged[host["id"]] = {**host, "enabled": host["id"] not in disabled}
    for host in parse_proxy_hosts(load_config()):
        merged[host["id"]] = {**host, "enabled": host["id"] not in disabled}
    return sorted(merged.values(), key=lambda h: h["id"])


def _save_hosts(hosts: list[dict], disabled: set[str]):
    normalized = []
    for host in hosts:
        normalized.append({
            "id": _slug(host["id"]),
            "domains": [d.strip().lower() for d in host.get("domains", []) if d.strip()],
            "scheme": host.get("scheme", "http"),
            "forward_host": host.get("forward_host", "").strip(),
            "forward_port": str(host.get("forward_port", "")).strip(),
        })
    _save_state({"disabled": sorted(disabled), "all_hosts": normalized})
    save_config(build_config_from_hosts(normalized, disabled))


def _validate_target(host: str, port: str):
    if not host or not port:
        raise ValueError("Target host and port are required")
    try:
        port_int = int(port)
    except ValueError as exc:
        raise ValueError("Port must be numeric") from exc
    if port_int < 1 or port_int > 65535:
        raise ValueError("Port must be between 1 and 65535")
    if not ALLOW_PRIVATE_TARGETS:
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(host))
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                raise ValueError("Private targets are disabled by ALLOW_PRIVATE_TARGETS=false")
        except socket.gaierror as exc:
            raise ValueError("Target host does not resolve") from exc


def _payload_host(body: dict, existing_id: str | None = None) -> dict:
    service_id = _slug(existing_id or body.get("id") or "")
    domains = body.get("domains") or []
    if isinstance(domains, str):
        domains = [d.strip() for d in domains.split(",")]
    domains = [d.strip().lower() for d in domains if d.strip()]
    scheme = body.get("scheme", "http")
    if scheme not in {"http", "https"}:
        raise ValueError("Scheme must be http or https")
    forward_host = body.get("forward_host", "").strip()
    forward_port = str(body.get("forward_port", "")).strip()
    if not service_id:
        raise ValueError("Service id is required")
    if not domains:
        raise ValueError("At least one domain is required")
    _validate_target(forward_host, forward_port)
    return {
        "id": service_id,
        "domains": domains,
        "scheme": scheme,
        "forward_host": forward_host,
        "forward_port": forward_port,
        "enabled": True,
    }


def _tcp_ok(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _http_status(url: str, timeout: float = 5.0) -> dict:
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "RouteBox/1.0"})
        response = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        return {"online": response.status < 500, "status": response.status, "error": ""}
    except urllib.error.HTTPError as exc:
        return {"online": exc.code < 500, "status": exc.code, "error": ""}
    except Exception as exc:
        return {"online": False, "status": None, "error": str(exc)}


def _source_check(domain: str) -> dict:
    for scheme in ("https", "http"):
        result = _http_status(f"{scheme}://{domain}")
        if result["online"]:
            result["scheme"] = scheme
            return result
    result["scheme"] = "https/http"
    return result


def _target_check(host: dict) -> dict:
    port = int(host["forward_port"])
    tcp_online = _tcp_ok(host["forward_host"], port)
    url = f"{host.get('scheme', 'http')}://{host['forward_host']}:{host['forward_port']}"
    http = _http_status(url, timeout=4.0) if tcp_online else {"online": False, "status": None, "error": "tcp connection failed"}
    return {"online": bool(tcp_online), "tcp": bool(tcp_online), "http_status": http.get("status"), "error": http.get("error", "")}


def _checked_host(host: dict) -> dict:
    if not host.get("enabled", True):
        return {**host, "source_online": None, "dest_online": None, "source_check": None, "target_check": None}
    target = _target_check(host)
    source = _source_check(host["domains"][0]) if host.get("domains") else {"online": False, "status": None, "error": "no domains"}
    return {
        **host,
        "source_online": source["online"],
        "dest_online": target["online"],
        "source_check": source,
        "target_check": target,
    }


def _masked_settings() -> dict:
    values = _runtime_settings(include_secrets=False)
    return values


def _coolify_headers() -> dict:
    headers = {"Accept": "application/json"}
    if COOLIFY_API_TOKEN:
        headers["Authorization"] = f"Bearer {COOLIFY_API_TOKEN}"
    return headers


def _coolify_api(path: str) -> dict:
    if not COOLIFY_URL or not COOLIFY_API_TOKEN:
        raise BackendError("COOLIFY_URL and COOLIFY_API_TOKEN are required")
    base = COOLIFY_URL.rstrip("/")
    req = urllib.request.Request(f"{base}{path}", headers=_coolify_headers())
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raise BackendError(f"Coolify API returned {exc.code}") from exc
    except Exception as exc:
        raise BackendError(f"Coolify API check failed: {exc}") from exc


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/meta")
def meta():
    return jsonify({
        "app": APP_NAME,
        "backend": BACKEND,
        "config_path": CONFIG_PATH if BACKEND == "local" else REMOTE_CONFIG_PATH,
        "defaults": {
            "entrypoint_http": DEFAULT_ENTRYPOINT_HTTP,
            "entrypoint_https": DEFAULT_ENTRYPOINT_HTTPS,
            "cert_resolver": DEFAULT_CERT_RESOLVER,
        },
        "coolify": {
            "url": COOLIFY_URL,
            "token_set": bool(COOLIFY_API_TOKEN),
        },
    })


@app.route("/api/hosts", methods=["GET"])
def list_hosts():
    checked = request.args.get("status", "true").lower() not in {"0", "false", "no"}
    hosts = _all_hosts()
    if checked:
        hosts = [_checked_host(host) for host in hosts]
    return jsonify(hosts)


@app.route("/api/hosts", methods=["POST"])
def create_host():
    try:
        host = _payload_host(request.json or {})
        hosts = _all_hosts()
        if any(h["id"] == host["id"] for h in hosts):
            return jsonify({"error": f"Host '{host['id']}' already exists"}), 409
        state = _load_state()
        disabled = set(state.get("disabled", []))
        hosts.append(host)
        _save_hosts(hosts, disabled)
        return jsonify({"status": "ok", "host": host}), 201
    except (ValueError, BackendError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/hosts/<service_id>", methods=["PUT"])
def update_host(service_id):
    try:
        replacement = _payload_host(request.json or {}, existing_id=service_id)
        hosts = _all_hosts()
        for idx, host in enumerate(hosts):
            if host["id"] == service_id:
                hosts[idx] = replacement
                break
        else:
            return jsonify({"error": "Host not found"}), 404
        state = _load_state()
        _save_hosts(hosts, set(state.get("disabled", [])))
        return jsonify({"status": "ok", "host": replacement})
    except (ValueError, BackendError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/hosts/<service_id>", methods=["DELETE"])
def delete_host(service_id):
    hosts = [h for h in _all_hosts() if h["id"] != service_id]
    state = _load_state()
    disabled = set(state.get("disabled", []))
    disabled.discard(service_id)
    try:
        _save_hosts(hosts, disabled)
        return jsonify({"status": "ok"})
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/hosts/<service_id>/toggle", methods=["POST"])
def toggle_host(service_id):
    hosts = _all_hosts()
    if not any(h["id"] == service_id for h in hosts):
        return jsonify({"error": "Host not found"}), 404
    state = _load_state()
    disabled = set(state.get("disabled", []))
    if service_id in disabled:
        disabled.remove(service_id)
        enabled = True
    else:
        disabled.add(service_id)
        enabled = False
    try:
        _save_hosts(hosts, disabled)
        return jsonify({"status": "ok", "enabled": enabled})
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/status", methods=["GET"])
def status_all():
    hosts = _all_hosts()
    results: list[dict] = []
    lock = threading.Lock()

    def check(host):
        with lock:
            results.append(_checked_host(host))

    threads = [threading.Thread(target=check, args=(host,), daemon=True) for host in hosts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=8)
    return jsonify(sorted(results, key=lambda h: h["id"]))


@app.route("/api/settings", methods=["GET"])
def settings_get():
    return jsonify(_masked_settings())


@app.route("/api/settings", methods=["PUT"])
def settings_put():
    try:
        body = request.json or {}
        sanitized = {key: str(body.get(key, "")) for key in SETTINGS_KEYS if key in body}
        backend = sanitized.get("BACKEND", BACKEND).lower()
        if backend not in {"local", "ssh", "proxmox"}:
            return jsonify({"error": "BACKEND must be local, ssh, or proxmox"}), 400
        sanitized["BACKEND"] = backend
        _apply_runtime_settings(sanitized)
        _read_text()
        return jsonify({"status": "ok", "settings": _masked_settings()})
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/settings/test", methods=["POST"])
def settings_test():
    try:
        if request.json:
            sanitized = {key: str(request.json.get(key, "")) for key in SETTINGS_KEYS if key in request.json}
            _apply_runtime_settings(sanitized)
        raw = _read_text()
        coolify = None
        if COOLIFY_URL and COOLIFY_API_TOKEN:
            try:
                coolify = _coolify_api("/api/v1/version")
            except BackendError as exc:
                coolify = {"error": str(exc)}
        return jsonify({"status": "ok", "bytes": len(raw.encode()), "backend": BACKEND, "coolify": coolify})
    except BackendError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400


@app.route("/api/raw", methods=["GET"])
def raw():
    try:
        return _read_text(), 200, {"Content-Type": "text/plain; charset=utf-8"}
    except BackendError as exc:
        return str(exc), 500


@app.route("/api/backups", methods=["GET"])
def backups():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(BACKUP_DIR.glob("dynamic-*.yml"), key=lambda p: p.stat().st_mtime, reverse=True):
        items.append({"name": path.name, "size": path.stat().st_size, "created": dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat()})
    return jsonify(items)


@app.route("/api/health", methods=["GET"])
def health():
    try:
        _read_text()
        return jsonify({"status": "healthy", "backend": BACKEND, "app": APP_NAME})
    except Exception as exc:
        return jsonify({"status": "unhealthy", "backend": BACKEND, "error": str(exc)}), 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "81")))
