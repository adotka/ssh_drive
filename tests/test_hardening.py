"""Усиление после ревью: rclone рядом с exe, PowerShell, автозапуск, загрузка WiX."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sshdrive import autostart, paths, pwsh, rclone  # noqa: E402


class TempEnv(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        patcher = mock.patch.dict(
            os.environ,
            {
                "APPDATA": str(self.root / "roaming"),
                "LOCALAPPDATA": str(self.root / "local"),
                "SSHDRIVE_RCLONE": "",
                "PATH": "",
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class PlantedRcloneTests(TempEnv):
    """rclone.exe рядом с программой (например, в «Загрузках») нельзя принимать на веру."""

    def setUp(self) -> None:
        super().setUp()
        self.folder = self.root / "Downloads"
        self.folder.mkdir()
        self.genuine = b"genuine rclone build"
        for patcher in (
            mock.patch.object(rclone, "PINNED_EXE_SHA256", hashlib.sha256(self.genuine).hexdigest()),
            mock.patch.object(paths, "install_dir", return_value=self.folder),
            mock.patch.object(paths, "bundled_file", return_value=None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        rclone._sha256_of.cache_clear()

    def test_foreign_rclone_beside_exe_is_ignored(self) -> None:
        (self.folder / "rclone.exe").write_bytes(b"something downloaded from the internet")
        self.assertIsNone(rclone.find_exe())

    def test_foreign_rclone_does_not_beat_installed_one(self) -> None:
        (self.folder / "rclone.exe").write_bytes(b"planted")
        installed = paths.rclone_exe()
        installed.parent.mkdir(parents=True)
        installed.write_bytes(self.genuine)
        self.assertEqual(rclone.find_exe(), str(installed))

    def test_genuine_rclone_beside_exe_is_used(self) -> None:
        (self.folder / "rclone.exe").write_bytes(self.genuine)
        self.assertEqual(rclone.find_exe(), str(self.folder / "rclone.exe"))

    def test_replacing_the_file_later_is_noticed(self) -> None:
        exe = self.folder / "rclone.exe"
        exe.write_bytes(self.genuine)
        self.assertTrue(rclone.is_pinned_exe(exe))
        exe.write_bytes(b"swapped after the first check")  # другой размер и mtime
        self.assertFalse(rclone.is_pinned_exe(exe))

    def test_explicit_override_still_wins(self) -> None:
        mine = self.root / "my-rclone.exe"
        mine.write_text("x")
        with mock.patch.dict(os.environ, {"SSHDRIVE_RCLONE": str(mine)}):
            self.assertEqual(rclone.find_exe(), str(mine))

    def test_pinned_exe_hash_is_well_formed(self) -> None:
        self.assertRegex(rclone.PINNED_EXE_SHA256, r"^[0-9a-f]{64}$")


class PowerShellQuotingTests(unittest.TestCase):
    def test_all_quote_kinds_are_doubled(self) -> None:
        self.assertEqual(pwsh.quote("O'Brien"), "'O''Brien'")
        for ch in "‘’‚‛":
            self.assertEqual(pwsh.quote(f"a{ch}b"), f"'a{ch}{ch}b'")

    def test_encoded_args_roundtrip(self) -> None:
        import base64

        args = pwsh.encoded_args("Write-Output 'hi'")
        self.assertEqual(args[:3], ["-NoProfile", "-NonInteractive", "-EncodedCommand"])
        self.assertEqual(base64.b64decode(args[3]).decode("utf-16-le"), "Write-Output 'hi'")


class AutostartTests(TempEnv):
    def test_uses_absolute_powershell_and_escapes_paths(self) -> None:
        captured = {}
        appdata = self.root / "roaming’s dir"  # типографская кавычка в пути
        with mock.patch.dict(os.environ, {"APPDATA": str(appdata)}):
            def fake_run(args, **kw):
                captured["args"] = args
                autostart.shortcut_path().write_text("lnk")
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            with mock.patch.object(subprocess, "run", fake_run):
                autostart.enable()

        self.assertEqual(captured["args"][0], paths.powershell_exe())
        self.assertNotEqual(captured["args"][0].lower(), "powershell")
        import base64

        script = base64.b64decode(captured["args"][captured["args"].index("-EncodedCommand") + 1]).decode("utf-16-le")
        self.assertIn("roaming’’s dir", script)  # кавычка удвоена, строка не «вытекает»


class FetchWixTests(TempEnv):
    @staticmethod
    def _module():
        spec = importlib.util.spec_from_file_location("fetch_wix_under_test", ROOT / "tools" / "fetch_wix.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _zip(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("candle.exe", b"c")
            zf.writestr("light.exe", b"l")
        return buf.getvalue()

    def _run(self, module, blob: bytes) -> int:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = blob
        with mock.patch.object(module, "TARGET", self.root / "wix"), \
                mock.patch.object(module.urllib.request, "urlopen", return_value=response):
            return module.main()

    def test_wrong_archive_is_not_extracted(self) -> None:
        module = self._module()
        self.assertEqual(self._run(module, self._zip()), 1)
        self.assertFalse((self.root / "wix").exists())

    def test_pinned_archive_is_extracted(self) -> None:
        module = self._module()
        blob = self._zip()
        with mock.patch.object(module, "SHA256", hashlib.sha256(blob).hexdigest()):
            self.assertEqual(self._run(module, blob), 0)
        self.assertTrue((self.root / "wix" / "light.exe").is_file())

    def test_pinned_hash_looks_sane(self) -> None:
        self.assertRegex(self._module().SHA256, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
