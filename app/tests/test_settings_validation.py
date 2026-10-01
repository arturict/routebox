import os
import tempfile
import unittest
from unittest import mock

_tmp = tempfile.mkdtemp()
os.environ.setdefault("ENV_FILE", os.path.join(_tmp, "settings.env"))
os.environ.setdefault("STATE_FILE", os.path.join(_tmp, "state.json"))
os.environ.setdefault("BACKUP_DIR", os.path.join(_tmp, "backups"))
os.environ.setdefault("CONFIG_PATH", os.path.join(_tmp, "dynamic.yml"))

import app as routebox  # noqa: E402


class SettingsValidationTest(unittest.TestCase):
    def setUp(self):
        self.client = routebox.app.test_client()

    def put(self, **values):
        return self.client.put("/api/settings", json=values)

    def test_rejects_shell_metacharacters_in_vmid(self):
        response = self.put(BACKEND="proxmox", PVE_VMID="101; touch /tmp/x")
        self.assertEqual(response.status_code, 400)
        self.assertIn("PVE_VMID", response.get_json()["error"])

    def test_rejects_option_like_ssh_user_and_host(self):
        self.assertEqual(self.put(SSH_USER="-oProxyCommand=id").status_code, 400)
        self.assertEqual(self.put(SSH_HOST="-oProxyCommand=id").status_code, 400)
        self.assertEqual(self.put(SSH_HOST="host name").status_code, 400)

    def test_rejected_settings_are_not_applied(self):
        before = routebox.PVE_VMID
        self.put(PVE_VMID="1 2")
        self.assertEqual(routebox.PVE_VMID, before)

    def test_accepts_homelab_values(self):
        for key, value in {
            "PVE_VMID": "101",
            "SSH_HOST": "192.168.1.200",
            "SSH_USER": "root",
            "SSH_PORT": "22",
            "SSH_KEY": "/root/.ssh/id_ed25519",
            "REMOTE_CONFIG_PATH": "/data/coolify/proxy/dynamic/npm-import.yaml",
            "COOLIFY_URL": "http://192.168.1.101:8000",
        }.items():
            self.assertIsNone(routebox._check_setting(key, value), key)

    def test_run_remote_quotes_vmid_and_separates_target(self):
        with mock.patch.object(routebox, "BACKEND", "proxmox"), \
                mock.patch.object(routebox, "SSH_HOST", "192.168.1.200"), \
                mock.patch.object(routebox, "SSH_USER", "root"), \
                mock.patch.object(routebox, "PVE_VMID", "101"), \
                mock.patch.object(routebox.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout='{"exitcode":0,"out-data":"ok"}', stderr="")
            self.assertEqual(routebox._run_remote("echo hi"), "ok")
        argv = run.call_args.args[0]
        self.assertEqual(argv[-3:-1], ["--", "root@192.168.1.200"])
        self.assertTrue(argv[-1].startswith("qm guest exec 101 -- bash -lc "))

    def test_run_remote_rechecks_values_from_environment(self):
        with mock.patch.object(routebox, "BACKEND", "proxmox"), \
                mock.patch.object(routebox, "SSH_HOST", "192.168.1.200"), \
                mock.patch.object(routebox, "PVE_VMID", "101;id"), \
                mock.patch.object(routebox.subprocess, "run") as run:
            with self.assertRaises(routebox.BackendError):
                routebox._run_remote("echo hi")
        run.assert_not_called()


class ClientAllowlistTest(unittest.TestCase):
    def request_from(self, networks: str, addr: str) -> int:
        with mock.patch.object(routebox, "ALLOWED_CLIENT_NETWORKS", routebox._parse_networks(networks)):
            client = routebox.app.test_client()
            return client.get("/api/health", environ_overrides={"REMOTE_ADDR": addr}).status_code

    def test_empty_allowlist_allows_everyone(self):
        self.assertEqual(self.request_from("", "203.0.113.9"), 200)

    def test_allows_lan_and_tailnet_blocks_others(self):
        networks = "192.168.1.0/24,100.64.0.0/10,127.0.0.0/8"
        self.assertEqual(self.request_from(networks, "192.168.1.213"), 200)
        self.assertEqual(self.request_from(networks, "100.123.58.113"), 200)
        self.assertEqual(self.request_from(networks, "127.0.0.1"), 200)
        self.assertEqual(self.request_from(networks, "203.0.113.9"), 403)
        self.assertEqual(self.request_from(networks, "172.19.0.1"), 403)


class HostPayloadValidationTest(unittest.TestCase):
    def test_rejects_rule_injection_in_domain(self):
        with self.assertRaises(ValueError):
            routebox._payload_host({"id": "x", "domains": ["a.example.com`) || Host(`b.example.com"], "forward_host": "192.168.1.10", "forward_port": "80"})

    def test_rejects_bad_forward_host(self):
        with self.assertRaises(ValueError):
            routebox._payload_host({"id": "x", "domains": ["a.example.com"], "forward_host": "10.0.0.1/evil", "forward_port": "80"})

    def test_accepts_container_name_and_ip(self):
        for target in ("192.168.1.113", "wry4vm7sotqi8rapq8d2e1u4-182000630297"):
            host = routebox._payload_host({"id": "x", "domains": ["A.example.com"], "forward_host": target, "forward_port": "80"})
            self.assertEqual(host["domains"], ["a.example.com"])


if __name__ == "__main__":
    unittest.main()
