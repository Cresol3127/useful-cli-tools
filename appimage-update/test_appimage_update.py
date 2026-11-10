"""Offline checks: python3 -B -m unittest discover -s pkgs/appimages -v."""

import contextlib
import hashlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import appimage_update as update


class BatchUpdateTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.directory = Path(work.name)
        self.manifest = self.directory / "config/appimage-update/sources.json"
        manifest = patch.object(update, "manifest_file", return_value=self.manifest)
        manifest.start()
        self.addCleanup(manifest.stop)
        for stream in (contextlib.redirect_stdout, contextlib.redirect_stderr):
            self.enterContext(stream(io.StringIO()))

    def image(self, name):
        path = self.directory / name
        path.write_bytes(b"test")
        return path

    def release(self, body, tag="v2.0.0", name="Example-2.0.0.AppImage"):
        digest = hashlib.sha256(body).hexdigest()
        return {
            "tag_name": tag,
            "full_name": "owner/repo",
            "assets": [{
                "name": name,
                "browser_download_url": f"https://github.com/owner/repo/releases/download/{tag}/{name}",
                "digest": f"sha256:{digest}",
            }],
        }

    def test_discovery_deduplicates_paths_and_skips_unrelated_files(self):
        image = self.image("Example.AppImage")
        self.image("notes.txt")
        (self.directory / "linked.AppImage").symlink_to(image)
        self.assertEqual(update.discover([self.directory, image]), [image])

    def test_untracked_apps_use_shared_appimageupdate_tool(self):
        images = [self.image("first.AppImage"), self.image("second.AppImage")]
        with patch.object(update, "generic_tool", return_value="updater") as tool, \
             patch.object(update.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)) as run:
            self.assertEqual(update.run(images), 0)
        tool.assert_called_once()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0], ["updater", "--check-for-update", str(images[1])])

    def test_check_prints_one_summary_and_hides_backend_output(self):
        image = self.image("first.AppImage")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), \
             patch.object(update, "generic_tool", return_value="updater"), \
             patch.object(update.subprocess, "run", return_value=subprocess.CompletedProcess(
                 [], 1, stdout="Fetching release metadata\\n", stderr="zsync chatter\\n",
             )) as run:
            self.assertEqual(update.run([image]), 0)
        self.assertEqual(stdout.getvalue().splitlines(), [
            "first.AppImage: Update available",
            "",
            "Check finished: 1 file(s), 1 update(s) available, 0 failure(s).",
        ])
        self.assertTrue(run.call_args.kwargs["capture_output"])

    def test_check_failure_preserves_backend_diagnostics(self):
        image = self.image("broken.AppImage")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), \
             patch.object(update, "generic_tool", return_value="updater"), \
             patch.object(update.subprocess, "run", return_value=subprocess.CompletedProcess(
                 [], 2, stdout="backend output", stderr="TLS certificate error",
             )):
            self.assertEqual(update.run([image]), 1)
        self.assertIn("AppImageUpdate exited 2", stderr.getvalue())
        self.assertIn("TLS certificate error", stderr.getvalue())

    def test_download_shows_progress_and_verifies_digest(self):
        image = self.directory / "download.AppImage"
        body = b"download payload"

        class Response(io.BytesIO):
            headers = {"Content-Length": str(len(body))}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), \
             patch.object(update.urllib.request, "urlopen", return_value=Response(body)):
            update.download_asset("https://github.com/owner/repo/release/download", image,
                                  hashlib.sha256(body).hexdigest())
        self.assertEqual(image.read_bytes(), body)
        self.assertIn("100%", stderr.getvalue())
        self.assertIn("download.AppImage", stderr.getvalue())

    def test_interactive_check_reuses_one_status_line(self):
        images = [self.image("first.AppImage"), self.image("second.AppImage")]

        class Terminal(io.StringIO):
            def isatty(self):
                return True

        terminal = Terminal()
        with contextlib.redirect_stdout(terminal), \
             patch.object(update, "generic_tool", return_value="updater"), \
             patch.object(update.subprocess, "run", side_effect=[
                 subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 1),
             ]):
            self.assertEqual(update.run(images), 0)
        text = terminal.getvalue()
        self.assertIn("\r\033[Kfirst.AppImage: Up to date", text)
        self.assertIn("\r\033[Ksecond.AppImage: Update available", text)
        self.assertNotIn("\nfirst.AppImage:", text)
        self.assertIn("Check finished: 2 file(s), 1 update(s) available", text)

    def test_failures_do_not_stop_remaining_apps(self):
        images = [self.image("broken.AppImage"), self.image("working.AppImage")]
        with patch.object(update, "generic_tool", return_value="updater"), \
             patch.object(update.subprocess, "run", side_effect=[
                 subprocess.CompletedProcess([], 2), subprocess.CompletedProcess([], 0),
             ]) as run:
            self.assertEqual(update.run(images, apply=True, prune=True), 1)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0], ["updater", "--remove-old", str(images[1])])

    def test_default_checks_both_home_directories(self):
        desktop = self.directory / "Desktop"
        applications = self.directory / "Applications"
        desktop.mkdir()
        applications.mkdir()
        first = desktop / "first.AppImage"
        second = applications / "second.AppImage"
        first.touch()
        second.touch()
        with patch.object(update.Path, "home", return_value=self.directory), \
             patch("sys.argv", ["update.py"]), patch.object(update, "run", return_value=0) as run:
            self.assertEqual(update.main(), 0)
        run.assert_called_once_with(sorted([first, second]), apply=False, prune=False)

    def test_add_verifies_current_digest_and_persists_source(self):
        image = self.image("Example.AppImage")
        body = b"current release"
        image.write_bytes(body)
        with patch.object(update, "github_release", return_value=self.release(body)):
            update.add_source(image, "owner/repo", None, False, False, update.load_manifest())
        entry = update.load_manifest()[str(image)]
        self.assertEqual(entry["repo"], "owner/repo")
        self.assertEqual(entry["version"], "v2.0.0")
        self.assertEqual(self.manifest.stat().st_mode & 0o777, 0o600)

    def test_add_old_file_is_unverified_until_update(self):
        image = self.image("Example.AppImage")
        with patch.object(update, "github_release", return_value=self.release(b"new release")):
            update.add_source(image, "owner/repo", None, False, False, update.load_manifest())
        entry = update.load_manifest()[str(image)]
        self.assertIsNone(entry.get("version"))

    def test_remove_stops_tracking_without_deleting_file(self):
        image = self.image("Example.AppImage")
        update.save_manifest({
            str(image): {"path": str(image), "repo": "owner/repo", "version": "v1.0.0"},
        })
        update.remove_source(image, update.load_manifest())
        self.assertEqual(update.load_manifest(), {})
        self.assertTrue(image.exists())

    def test_install_integrations_creates_desktop_entry_and_explicit_command(self):
        image = self.image("Loaf-v0.3.0-x86_64.AppImage")
        desktop_dir = self.directory / "data/applications"
        command_dir = self.directory / "bin"
        entry = {
            "path": str(image),
            "repo": "owner/loaf",
            "asset": r"Loaf-v.*-x86_64\.AppImage",
            "desktop": True,
            "desktop_name": "Loaf",
            "desktop_id": "loaf.desktop",
            "icon": "system-file-manager",
            "mime_types": ["inode/directory"],
            "commands": ["loaf"],
        }

        with patch.object(update, "desktop_directory", return_value=desktop_dir), \
             patch.object(update, "command_directory", return_value=command_dir):
            update.install_integrations(entry)

        desktop = (desktop_dir / "loaf.desktop").read_text()
        command = command_dir / "loaf"
        wrapper = command.read_text()
        self.assertIn("Name=Loaf", desktop)
        self.assertIn('Exec="' + str(command) + '" %U', desktop)
        self.assertIn("MimeType=inode/directory;", desktop)
        self.assertIn("X-AppImage-Update-Source=", desktop)
        self.assertIn(str(image), wrapper)
        self.assertTrue(command.stat().st_mode & 0o111)
        self.assertEqual(update.default_desktop_name(image.name), "Loaf")

    def test_update_refreshes_command_wrapper_for_new_versioned_filename(self):
        old = self.image("Loaf-v1.0.0-x86_64.AppImage")
        old.write_bytes(b"old release")
        body = b"new release"
        entry = {
            "path": str(old),
            "repo": "owner/loaf",
            "asset": update.pattern_for(old.name),
            "version": "v1.0.0",
            "desktop": True,
            "desktop_name": "Loaf",
            "desktop_id": "loaf.desktop",
            "icon": "system-file-manager",
            "mime_types": ["inode/directory"],
            "commands": ["loaf"],
        }
        desktop_dir = self.directory / "data/applications"
        command_dir = self.directory / "bin"
        release = self.release(body, tag="v2.0.0", name="Loaf-v2.0.0-x86_64.AppImage")

        def download(url, destination, expected=None):
            destination.write_bytes(body)

        with patch.object(update, "desktop_directory", return_value=desktop_dir), \
             patch.object(update, "command_directory", return_value=command_dir):
            update.install_integrations(entry)
            with patch.object(update, "github_release", return_value=release), \
                 patch.object(update, "download_asset", side_effect=download):
                self.assertTrue(update.update_tracked(entry, apply=True))

        target = self.directory / "Loaf-v2.0.0-x86_64.AppImage"
        self.assertEqual(entry["path"], str(target))
        self.assertIn(str(target), (command_dir / "loaf").read_text())
        self.assertNotIn(str(old), (command_dir / "loaf").read_text())
        self.assertIn('Exec="' + str(command_dir / "loaf") + '" %U',
                      (desktop_dir / "loaf.desktop").read_text())

    def test_update_repairs_missing_integrations_for_current_release(self):
        image = self.image("Example-2.0.0.AppImage")
        body = b"current release"
        image.write_bytes(body)
        entry = {
            "path": str(image),
            "repo": "owner/repo",
            "version": "v2.0.0",
            "desktop": True,
            "desktop_name": "Example",
            "desktop_id": "example.desktop",
            "commands": ["example"],
        }
        desktop_dir = self.directory / "data/applications"
        command_dir = self.directory / "bin"
        with patch.object(update, "desktop_directory", return_value=desktop_dir), \
             patch.object(update, "command_directory", return_value=command_dir), \
             patch.object(update, "github_release", return_value=self.release(body)):
            self.assertFalse(update.update_tracked(entry, apply=True))
        self.assertTrue((command_dir / "example").is_file())
        self.assertTrue((desktop_dir / "example.desktop").is_file())

    def test_integrations_refuse_to_overwrite_unmanaged_command(self):
        image = self.image("Example.AppImage")
        command_dir = self.directory / "bin"
        command_dir.mkdir()
        command = command_dir / "example"
        command.write_text("user-owned command\n")
        entry = {"path": str(image), "repo": "owner/repo", "commands": ["example"]}
        with patch.object(update, "command_directory", return_value=command_dir), \
             self.assertRaisesRegex(ValueError, "refusing to overwrite unmanaged"):
            update.install_integrations(entry)
        self.assertEqual(command.read_text(), "user-owned command\n")

    def test_cli_passes_desktop_and_command_options_to_tracking(self):
        image = self.image("Example.AppImage")
        argv = [
            "appimage-update", "--add", "owner/repo", "--desktop",
            "--name", "Example", "--desktop-id", "example.desktop",
            "--icon", "example-icon", "--mime-type", "inode/directory",
            "--command", "example", str(image),
        ]
        with patch("sys.argv", argv), patch.object(update, "load_manifest", return_value={}), \
             patch.object(update, "add_source") as add:
            self.assertEqual(update.main(), 0)
        self.assertEqual(add.call_args.args[:2], (image, "owner/repo"))
        self.assertEqual(add.call_args.kwargs["desktop"], True)
        self.assertEqual(add.call_args.kwargs["desktop_name"], "Example")
        self.assertEqual(add.call_args.kwargs["desktop_id"], "example.desktop")
        self.assertEqual(add.call_args.kwargs["icon"], "example-icon")
        self.assertEqual(add.call_args.kwargs["mime_types"], ["inode/directory"])
        self.assertEqual(add.call_args.kwargs["commands"], ["example"])

    def test_tracked_update_renames_and_prunes_old_copy(self):
        old = self.image("Example-1.0.0.AppImage")
        old.write_bytes(b"old release")
        body = b"new release"
        release = self.release(body, name="Example-2.0.0.AppImage")
        entry = {"path": str(old), "repo": "owner/repo", "version": None}

        def download(url, destination, expected=None):
            destination.write_bytes(body)

        with patch.object(update, "github_release", return_value=release), \
             patch.object(update, "download_asset", side_effect=download):
            self.assertTrue(update.update_tracked(entry, apply=True, prune=True))
        target = self.directory / "Example-2.0.0.AppImage"
        self.assertEqual(target.read_bytes(), body)
        self.assertFalse(old.exists())
        self.assertEqual(entry["path"], str(target))
        self.assertEqual(entry["version"], "v2.0.0")

    def test_tracked_check_does_not_download(self):
        image = self.image("Example.AppImage")
        entry = {"path": str(image), "repo": "owner/repo", "version": None}
        with patch.object(update, "github_release", return_value=self.release(b"new")), \
             patch.object(update, "download_asset") as download:
            self.assertFalse(update.update_tracked(entry, apply=False))
        download.assert_not_called()

    def test_tracked_failure_preserves_current_file(self):
        image = self.image("Example.AppImage")
        image.write_bytes(b"old")
        entry = {"path": str(image), "repo": "owner/repo", "version": None}
        with patch.object(update, "github_release", return_value=self.release(b"new")), \
             patch.object(update, "download_asset", side_effect=ValueError("bad download")):
            with self.assertRaisesRegex(ValueError, "bad download"):
                update.update_tracked(entry, apply=True)
        self.assertEqual(image.read_bytes(), b"old")

    def test_manifest_entries_survive_a_missing_file(self):
        missing = self.directory / "missing.AppImage"
        update.save_manifest({
            str(missing): {"path": str(missing), "repo": "owner/repo", "version": "v1"},
        })
        self.assertIn(str(missing), update.load_manifest())

    def test_multiple_matching_assets_require_a_pattern(self):
        release = self.release(b"a", name="First.AppImage")
        release["assets"].append({
            "name": "Second.AppImage",
            "browser_download_url": "https://github.com/owner/repo/releases/download/v2/Second.AppImage",
            "digest": "sha256:" + "0" * 64,
        })
        with self.assertRaisesRegex(ValueError, "several matching assets"):
            update.select_asset(release)
        self.assertEqual(update.select_asset(release, r"Second")["name"], "Second.AppImage")

    def test_github_url_and_assets_are_normalized(self):
        self.assertEqual(update.normalize_repo("https://github.com/owner/repo"), "owner/repo")
        self.assertEqual(update.normalize_repo("https://github.com/owner/repo/releases"), "owner/repo")
        self.assertEqual(update.normalize_repo("git@github.com:owner/repo.git"), "owner/repo")
        release = self.release(b"x86", name="App-2.0.0-x86_64.AppImage")
        release["assets"].append({
            "name": "App-2.0.0-aarch64.AppImage",
            "browser_download_url": "https://github.com/owner/repo/releases/download/v2/App-2.0.0-aarch64.AppImage",
            "digest": "sha256:" + "0" * 64,
        })
        with patch.object(update.platform, "machine", return_value="x86_64"):
            self.assertEqual(update.select_asset(release)["name"], "App-2.0.0-x86_64.AppImage")
            self.assertEqual(
                update.select_asset(release, arch="aarch64")["name"],
                "App-2.0.0-aarch64.AppImage",
            )
        self.assertEqual(update.architecture("amd64")[0], "x86_64")
        with patch.object(update.platform, "machine", return_value="aarch64"):
            self.assertEqual(update.select_asset(release)["name"], "App-2.0.0-aarch64.AppImage")
        with patch.object(update.platform, "machine", return_value="riscv64"):
            release["assets"].append({
                "name": "App-2.0.0-riscv64.AppImage",
                "browser_download_url": "https://github.com/owner/repo/releases/download/v2/App-2.0.0-riscv64.AppImage",
                "digest": "sha256:" + "0" * 64,
            })
            self.assertEqual(update.select_asset(release)["name"], "App-2.0.0-riscv64.AppImage")

    def test_release_with_only_another_architecture_is_rejected(self):
        release = self.release(b"arm", name="App-2.0.0-aarch64.AppImage")
        with patch.object(update.platform, "machine", return_value="x86_64"), \
             self.assertRaisesRegex(ValueError, "no AppImage for this architecture"):
            update.select_asset(release)

    def test_versioned_asset_pattern_matches_future_versions(self):
        pattern = update.pattern_for("App-2.0.0-x86_64.AppImage")
        self.assertRegex("App-1.2.3-x86_64.AppImage", pattern)
        self.assertNotRegex("App-1.2.3-aarch64.AppImage", pattern)

    def test_add_url_without_path_finds_local_appimage(self):
        applications = self.directory / "Applications"
        applications.mkdir()
        local = applications / "Example-1.0.0.AppImage"
        local.write_bytes(b"old")
        with patch.object(update.Path, "home", return_value=self.directory), \
             patch.object(update, "github_release", return_value=self.release(b"new")):
            update.add_source(None, "https://github.com/owner/repo", None, False, False, {})
        entry = update.load_manifest()[str(local)]
        self.assertEqual(entry["repo"], "owner/repo")
        self.assertIsNone(entry.get("version"))

    def test_add_url_without_path_can_download_when_updating(self):
        body = b"new release"

        def download(url, destination, expected=None):
            destination.write_bytes(body)

        with patch.object(update.Path, "home", return_value=self.directory), \
             patch.object(update, "github_release", return_value=self.release(body)), \
             patch.object(update, "download_asset", side_effect=download):
            update.add_source(None, "https://github.com/owner/repo", None, True, False, {})
        target = self.directory / "Applications/Example-2.0.0.AppImage"
        entry = update.load_manifest()[str(target)]
        self.assertEqual(entry["version"], "v2.0.0")
        self.assertEqual(target.read_bytes(), body)


if __name__ == "__main__":
    unittest.main()
