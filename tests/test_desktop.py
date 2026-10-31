"""Native policy and ephemeral backend lifecycle checks without opening a UI."""
import json
import tempfile
import socket
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server
import build_desktop
import install_desktop
from desktop_policy import navigation_policy


class DesktopTests(unittest.TestCase):
    def test_asset_manifest_rejects_traversal_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "static").mkdir()
            (root / "static" / "app.js").write_text("ok", encoding="utf-8")
            manifest = root / "assets.txt"
            manifest.write_text("static/app.js\n", encoding="utf-8")
            with patch.object(build_desktop, "ROOT", root), patch.object(build_desktop, "ASSET_MANIFEST", manifest):
                self.assertEqual(build_desktop.read_assets()[0][0], "static/app.js")
                manifest.write_text("../outside.js\n", encoding="utf-8")
                with self.assertRaises(SystemExit):
                    build_desktop.read_assets()
                (root / "linked.js").symlink_to(root / "static" / "app.js")
                manifest.write_text("linked.js\n", encoding="utf-8")
                with self.assertRaises(SystemExit):
                    build_desktop.read_assets()

    def test_installer_refuses_unmarked_existing_application(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.app"
            target = root / "Applications" / install_desktop.APP_NAME
            source_resources = source / "Contents" / "Resources"
            source_resources.mkdir(parents=True)
            with (source / "Contents" / "Info.plist").open("wb") as stream:
                import plistlib
                plistlib.dump({"CFBundleIdentifier": install_desktop.BUNDLE_ID}, stream)
            (source_resources / install_desktop.OWNER_MARKER.name).write_bytes(install_desktop.OWNER_MARKER.read_bytes())
            target.mkdir(parents=True)
            sentinel = target / "keep.txt"
            sentinel.write_text("unrelated app", encoding="utf-8")
            with patch.object(install_desktop, "SOURCE", source), patch.object(install_desktop, "DESTINATION", target):
                with self.assertRaises(SystemExit):
                    install_desktop.main()
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unrelated app")

    def test_notices_include_runtime_and_dependency_licenses(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "THIRD_PARTY_NOTICES.txt"
            build_desktop.write_notices(destination)
            notices = destination.read_text(encoding="utf-8")
        self.assertNotIn("\x00", notices)
        self.assertIn("Python runtime 3.12.14", notices)
        self.assertIn("Third-party license texts", notices)
        self.assertIn("The BSD License (BSD)", notices)

    def test_navigation_boundary(self):
        origin = "http://127.0.0.1:49125/"
        self.assertEqual(navigation_policy(origin, origin, False, False), "allow")
        self.assertEqual(navigation_policy("blob:" + origin + "report", origin, False, True), "download")
        for url in (
            "file:///etc/passwd", "javascript:alert(1)", "data:text/html,hello",
            "http://127.0.0.1:49126/", "http://127.0.0.1.evil.test:49125/",
            "http://user@127.0.0.1:49125/", "blob:https://evil.test/report",
        ):
            self.assertEqual(navigation_policy(url, origin, False, False), "cancel")
        self.assertEqual(navigation_policy("https://example.com", origin, True, False), "external")
        self.assertEqual(navigation_policy("https://example.com", origin, False, False), "cancel")

    def test_make_server_skips_reverse_dns(self):
        with patch("socket.getfqdn", side_effect=AssertionError("Reverse DNS must not delay app startup")):
            backend = server.make_server(port=0)
        try:
            self.assertEqual(backend.server_name, "127.0.0.1")
            self.assertGreater(backend.server_port, 0)
        finally:
            backend.server_close()

    def test_ephemeral_host_origin_token_and_shutdown(self):
        backend = server.make_server(port=0)
        port = backend.server_port
        worker = threading.Thread(target=backend.serve_forever, daemon=True)
        worker.start()
        try:
            with urlopen(f"http://127.0.0.1:{port}/?desktop=1", timeout=3) as response:
                self.assertEqual(response.status, 200)
                html = response.read().decode("utf-8")
            with self.assertRaises(HTTPError) as failure:
                urlopen(Request(f"http://127.0.0.1:{port}/", headers={"Host": "evil.test"}), timeout=3)
            self.assertEqual(failure.exception.code, 403)
            failure.exception.close()
            with self.assertRaises(HTTPError) as failure:
                urlopen(Request(f"http://127.0.0.1:{port}/", headers={"Origin": "http://evil.test"}), timeout=3)
            self.assertEqual(failure.exception.code, 403)
            failure.exception.close()
            with self.assertRaises(HTTPError) as failure:
                urlopen(Request(f"http://127.0.0.1:{port}/api/inspect", data=b"{}", method="POST", headers={"Content-Type": "application/json"}), timeout=3)
            self.assertEqual(failure.exception.code, 403)
            failure.exception.close()
            token = html.split("const TOKEN='", 1)[1].split("'", 1)[0]
            payload = json.dumps({"csv": "date,value\n2025-01-01,1\n2025-01-02,2\n", "timestamp": "date", "value": "value"}).encode()
            request = Request(
                f"http://127.0.0.1:{port}/api/inspect",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json", "X-Forecast-Token": token, "Origin": f"http://127.0.0.1:{port}"},
            )
            with urlopen(request, timeout=5) as response:
                result = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(result["series"][0]["rows"], 2)
        finally:
            backend.shutdown()
            backend.server_close()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(backend.fileno(), -1)
        with socket.socket() as probe:
            self.assertNotEqual(probe.connect_ex(("127.0.0.1", port)), 0)


if __name__ == "__main__":
    unittest.main()
