#!/usr/bin/env python3
"""Check or update all AppImages in ~/Desktop and ~/Applications."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request


def find_nixos_root():
    """Return the NixOS checkout when running as its packaged helper."""
    override = os.environ.get("APPIMAGE_UPDATE_NIXOS_ROOT")
    if override:
        root = Path(override).expanduser().resolve()
        if not (root / "prepare-source.py").is_file():
            raise ValueError(f"APPIMAGE_UPDATE_NIXOS_ROOT is not a NixOS checkout: {root}")
        return root
    root = Path(__file__).resolve().parents[2]
    if (root / "prepare-source.py").is_file() and (root / "pkgs/artcraft/update.py").is_file():
        return root
    return None


ROOT = find_nixos_root()
artcraft = None
supported = {}
if ROOT:
    spec = importlib.util.spec_from_file_location("artcraft", ROOT / "pkgs/artcraft/update.py")
    artcraft = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(artcraft)
    supported = json.loads((ROOT / "pkgs/artcraft/sources.json").read_text())

REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
VERSION = re.compile(r"\d+(?:\.\d+){1,3}")
ARCH_PATTERNS = {
    "x86_64": re.compile(r"(?:x86[_-]64|amd64|x64)", re.IGNORECASE),
    "aarch64": re.compile(r"(?:aarch64|arm64)", re.IGNORECASE),
    "armv7l": re.compile(r"(?:armv7l?|armhf)", re.IGNORECASE),
    "armv6l": re.compile(r"(?:armv6l?|armhf)", re.IGNORECASE),
    "i686": re.compile(r"(?:i[3-6]86)", re.IGNORECASE),
}
KNOWN_ARCH = re.compile(
    r"(?:x86[_-]64|amd64|x64|aarch64|arm64|armv[67]l?|armhf|i[3-6]86)",
    re.IGNORECASE,
)
_token = None
_token_loaded = False


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def source_path(path):
    return str(path.expanduser().absolute())


def existing_image(path):
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".appimage":
        raise ValueError(f"not a regular AppImage file: {path}")
    return path


def discover(paths):
    images = set()
    for path in paths:
        path = path.expanduser().absolute()
        if path.is_symlink():
            raise ValueError(f"symlinks are not supported: {path}")
        if path.is_dir():
            images.update(
                entry for entry in path.iterdir()
                if entry.suffix.lower() == ".appimage"
                and entry.is_file() and not entry.is_symlink()
            )
        elif path.is_file() and path.suffix.lower() == ".appimage":
            images.add(path)
        else:
            raise ValueError(f"not an AppImage or directory: {path}")
    return sorted(images)


def default_directories():
    return [Path.home() / "Desktop", Path.home() / "Applications"]


def normalize_repo(value):
    if not isinstance(value, str):
        raise ValueError("repository must be OWNER/REPO or a GitHub URL")
    value = value.strip().rstrip("/")
    if value.startswith("git@github.com:"):
        value = value.split(":", 1)[1]
    elif value.startswith(("https://", "http://")):
        parsed = urllib.parse.urlparse(value)
        if parsed.hostname not in ("github.com", "www.github.com"):
            raise ValueError("only github.com repositories are supported")
        value = parsed.path.strip("/")
    elif value.startswith("github.com/"):
        value = value.split("/", 1)[1]
    if value.endswith(".git"):
        value = value[:-4]
    parts = value.split("/")
    if len(parts) >= 2:
        value = "/".join(parts[:2])
    if not REPO.fullmatch(value):
        raise ValueError("repository must be OWNER/REPO or a GitHub URL")
    return value


def pattern_for(name):
    """Match later releases of an asset, allowing the version number to change."""
    parts = []
    end = 0
    for match in VERSION.finditer(name):
        parts.extend((re.escape(name[end:match.start()]), ".*"))
        end = match.end()
    parts.append(re.escape(name[end:]))
    return r"\A" + "".join(parts) + r"\Z"


def local_matches(pattern):
    matcher = re.compile(pattern)
    matches = set()
    for directory in default_directories():
        if directory.is_dir():
            matches.update(
                path for path in directory.iterdir()
                if path.suffix.lower() == ".appimage"
                and path.is_file() and not path.is_symlink()
                and matcher.search(path.name)
            )
    return sorted(matches)


def architecture(name):
    machine = name.strip().lower()
    machine = {
        "amd64": "x86_64",
        "x86-64": "x86_64",
        "arm64": "aarch64",
        "armv7": "armv7l",
        "armv6": "armv6l",
        "i386": "i686",
        "i486": "i686",
        "i586": "i686",
    }.get(machine, machine)
    pattern = ARCH_PATTERNS.get(machine)
    if pattern is None and machine:
        pattern = re.compile(
            rf"(?<![A-Za-z0-9]){re.escape(machine)}(?![A-Za-z0-9])", re.IGNORECASE,
        )
    return machine, pattern


def current_arch():
    return architecture(platform.machine())



def manifest_file():
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "appimage-update/sources.json"


def load_manifest():
    path = manifest_file()
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"not a regular manifest file: {path}")
    data = json.loads(path.read_text())
    if data.get("version") != 1 or not isinstance(data.get("sources"), list):
        raise ValueError(f"unsupported manifest format: {path}")
    sources = {}
    for item in data["sources"]:
        if not isinstance(item, dict):
            raise ValueError(f"invalid manifest entry: {path}")
        if not isinstance(item.get("path"), str) or not item["path"]:
            raise ValueError(f"invalid path in manifest: {path}")
        source = source_path(Path(item["path"]))
        repo = item.get("repo")
        if not isinstance(repo, str) or not REPO.fullmatch(repo):
            raise ValueError(f"invalid repository in manifest: {path}")
        entry = {"path": str(source), "repo": repo}
        if item.get("asset") is not None:
            if not isinstance(item["asset"], str):
                raise ValueError(f"invalid asset pattern in manifest: {path}")
            entry["asset"] = item["asset"]
        if item.get("version") is not None:
            if not isinstance(item["version"], str):
                raise ValueError(f"invalid version in manifest: {path}")
            entry["version"] = item["version"]
        sources[str(source)] = entry
    return sources


def save_manifest(sources):
    path = manifest_file()
    parent = path.parent
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if parent.is_symlink():
        raise ValueError(f"manifest directory is a symlink: {parent}")
    parent.chmod(0o700)
    data = {"version": 1, "sources": sorted(sources.values(), key=lambda entry: entry["path"])}
    descriptor, temporary = tempfile.mkstemp(prefix=".sources-", dir=parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(data, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def github_token():
    global _token, _token_loaded
    if _token_loaded:
        return _token
    _token_loaded = True
    _token = os.environ.get("GITHUB_TOKEN") or None
    if not _token:
        try:
            result = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                _token = result.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            pass
    return _token


def github_release(repo):
    repo = normalize_repo(repo)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "useful-cli-tools-appimage-update",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest", headers=headers,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    if not isinstance(release, dict):
        raise ValueError(f"invalid release data for {repo}")
    return release


def asset_digest(asset):
    digest = asset.get("digest", "")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        return None
    digest = digest.split(":", 1)[1]
    return digest if DIGEST.fullmatch(digest) else None


def select_asset(release, pattern=None, arch=None):
    assets = [
        asset for asset in release.get("assets", [])
        if isinstance(asset, dict) and isinstance(asset.get("name"), str)
    ]
    if pattern:
        try:
            matcher = re.compile(pattern)
        except re.error as error:
            raise ValueError(f"invalid --asset regex: {error}")
        candidates = [asset for asset in assets if matcher.search(asset["name"])]
    else:
        candidates = [asset for asset in assets if asset["name"].lower().endswith(".appimage")]
        machine, arch_pattern = architecture(arch) if arch else current_arch()
        preferred = [
            asset for asset in candidates
            if arch_pattern and arch_pattern.search(asset["name"])
        ]
        if arch_pattern and len(preferred) == 1:
            candidates = preferred
        elif arch_pattern and not preferred and any(KNOWN_ARCH.search(asset["name"]) for asset in candidates):
            names = ", ".join(asset["name"] for asset in candidates)
            raise ValueError(
                f"release has no AppImage for this architecture ({machine}): {names}; "
                "use --asset REGEX or --arch ARCH to choose one"
            )
    if not candidates:
        raise ValueError("release has no matching AppImage; use --asset REGEX")
    if len(candidates) > 1:
        names = ", ".join(asset["name"] for asset in candidates)
        raise ValueError(f"release has several matching assets ({names}); use --asset REGEX")
    asset = candidates[0]
    name = asset["name"]
    if not name or Path(name).name != name or name in (".", ".."):
        raise ValueError(f"unsafe asset name: {name!r}")
    url = asset.get("browser_download_url", "")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError(f"unexpected release URL: {url}")
    return asset


def download_asset(url, destination, expected=None):
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise ValueError(f"not a regular file: {destination}")
    digest = hashlib.sha256()
    descriptor, temporary = tempfile.mkstemp(prefix=".appimage-", dir=destination.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(url, timeout=60) as response:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if expected and digest.hexdigest() != expected:
            raise ValueError("download does not match the published SHA256 digest")
        os.chmod(temporary, 0o755)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def update_tracked(entry, apply=False, prune=False):
    image = Path(entry["path"])
    if image.is_symlink() or not image.is_file():
        raise ValueError(f"not a regular AppImage file: {image}")
    release = github_release(entry["repo"])
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError(f"release has no version tag: {entry['repo']}")
    tag = tag.strip()
    asset = select_asset(release, entry.get("asset"))
    expected = asset_digest(asset)
    target = image.parent / asset["name"]
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError(f"not a regular file: {target}")

    # A digest is authoritative. Without one, remember the last tag we installed.
    current = bool(expected) and sha256(image) == expected
    if not expected:
        current = entry.get("version") == tag
    print(f"  latest {tag}; {'current' if current else 'update available'}", flush=True)
    if current:
        if entry.get("version") != tag:
            entry["version"] = tag
            return True
        return False
    if not apply:
        print("  Use --update to download it.", flush=True)
        return False

    old = image.stat()
    if target != image and target.exists():
        if not expected or sha256(target) != expected:
            raise ValueError(f"refusing to overwrite existing file: {target}")
    else:
        print(f"  Downloading {asset['name']}...", flush=True)
        download_asset(asset["browser_download_url"], target, expected)

    entry["path"] = str(target)
    entry["version"] = tag
    print(f"  Updated: {target}", flush=True)
    if prune and target != image:
        try:
            now = image.lstat()
            unchanged = (
                now.st_ino, now.st_size, now.st_mtime_ns, now.st_ctime_ns,
            ) == (old.st_ino, old.st_size, old.st_mtime_ns, old.st_ctime_ns)
            if unchanged:
                image.unlink()
                print(f"  Removed previous copy: {image.name}", flush=True)
            else:
                print(f"  Kept changed previous file: {image}", flush=True)
        except FileNotFoundError:
            pass
    return True


def add_source(path, repo, asset_pattern, apply, prune, sources, arch=None):
    repo = normalize_repo(repo)
    image = existing_image(path) if path is not None else None
    release = github_release(repo)
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError(f"release has no version tag: {repo}")
    tag = tag.strip()
    asset = select_asset(release, asset_pattern, arch)
    pattern = asset_pattern or pattern_for(asset["name"])
    expected = asset_digest(asset)
    current = False
    if image is None:
        candidates = local_matches(pattern)
        if len(candidates) == 1:
            image = candidates[0]
            print(f"Found local AppImage: {image}", flush=True)
        elif len(candidates) > 1:
            names = ", ".join(str(candidate) for candidate in candidates)
            raise ValueError(f"several local AppImages match ({names}); pass one explicitly")
        elif apply:
            directory = Path.home() / "Applications"
            directory.mkdir(parents=True, exist_ok=True)
            image = directory / asset["name"]
            if image.is_symlink() or (image.exists() and not image.is_file()):
                raise ValueError(f"not a regular file: {image}")
            if image.exists():
                if not expected or sha256(image) != expected:
                    raise ValueError(f"refusing to overwrite existing file: {image}")
            else:
                print(f"Downloading {asset['name']}...", flush=True)
                download_asset(asset["browser_download_url"], image, expected)
            current = True
        else:
            raise ValueError(
                "no local AppImage matches this release; pass its path or use --update "
                f"to download it to {Path.home() / 'Applications'}"
            )
    if not current:
        current = bool(expected) and sha256(image) == expected
    canonical = release.get("full_name")
    entry = {
        "path": str(image),
        "repo": canonical if isinstance(canonical, str) and REPO.fullmatch(canonical) else repo,
        "asset": pattern,
        "version": tag if current else None,
    }
    sources[str(image)] = entry
    save_manifest(sources)
    print(f"Tracking {image.name} from {entry['repo']}; latest release {tag}.", flush=True)
    if current:
        print("  Local file matches the latest release.", flush=True)
    else:
        print("  Local file is not verified as current; run --update to download it.", flush=True)
    if apply and not current and update_tracked(entry, apply=True, prune=prune):
        save_manifest(sources)


def remove_source(path, sources):
    key = source_path(path)
    if key not in sources:
        raise ValueError(f"not tracked: {key}")
    del sources[key]
    save_manifest(sources)
    print(f"Stopped tracking {key}; the file was not deleted.", flush=True)


def generic_tool():
    override = os.environ.get("APPIMAGE_UPDATE_TOOL")
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise ValueError(f"APPIMAGE_UPDATE_TOOL is not a file: {path}")
        return str(path)

    for command in ("appimageupdatetool", "AppImageUpdate"):
        path = shutil.which(command)
        if path:
            return path

    if ROOT:
        source = subprocess.check_output(
            ["python3", str(ROOT / "prepare-source.py")], text=True,
        ).strip()
        package = subprocess.check_output([
            "nix", "build", "--no-update-lock-file", "--no-link", "--print-out-paths",
            f"{source}#appimageupdate",
        ], text=True).strip()
        return str(Path(package) / "bin/appimageupdatetool")

    raise ValueError(
        "AppImageUpdate is not installed; install appimageupdatetool, set "
        "APPIMAGE_UPDATE_TOOL, or track the app with --add OWNER/REPO"
    )


def run(images, apply=False, prune=False):
    tracked = load_manifest()
    manifest_changed = False
    handled = set()
    tool = None
    failures = 0
    for image in images:
        app = None
        if artcraft:
            app = next((app for app in supported if image in artcraft.local_images(image.parent, app)), None)
        key = (image.parent, app) if app else image
        if key in handled:
            continue
        handled.add(key)
        print(f"\n{'Updating' if apply else 'Checking'} {image.name}", flush=True)
        try:
            if app:
                artcraft.update_images(argparse.Namespace(
                    directory=image.parent, app=[app], version=None,
                    apply=apply, prune=prune,
                ), [app])
            elif str(image) in tracked:
                manifest_changed |= update_tracked(tracked[str(image)], apply=apply, prune=prune)
            else:
                if tool is None:
                    tool = generic_tool()
                flags = (["--remove-old"] if prune else []) if apply else ["--check-for-update"]
                result = subprocess.run([tool, *flags, str(image)], cwd=image.parent)
                if not apply and result.returncode == 1:
                    print("  Update available.")
                elif result.returncode != 0:
                    raise ValueError(
                        f"AppImageUpdate exited {result.returncode}. This app may lack embedded "
                        "update information; track its GitHub release with "
                        f"--add OWNER/REPO [--asset REGEX] {image}"
                    )
                elif not apply:
                    print("  Already current.")
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            failures += 1
            print(f"  FAILED: {image.name}: {error}", file=sys.stderr, flush=True)
    if manifest_changed:
        save_manifest(tracked)
    print(f"\n{'Update' if apply else 'Check'} finished: {len(handled)} app(s), {failures} failure(s).")
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(
        prog="appimage-update",
        usage="%(prog)s [options] [path ...]",
        description="Check or update AppImages.",
        formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=34, width=100),
        epilog="Paths default to ~/Desktop and ~/Applications. Add by repo: --add OWNER/REPO or GitHub URL.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("-c", "--check", action="store_true", help="check only (default)")
    mode.add_argument("-u", "--update", action="store_true",
                      help="update existing AppImage files, not install new apps")
    parser.add_argument("-p", "--prune", "--remove-old", action="store_true",
                        help="remove old copies (requires --update)")
    manage = parser.add_mutually_exclusive_group()
    manage.add_argument("-a", "--add", metavar="REPO",
                        help="track a GitHub repo or URL; path optional")
    manage.add_argument("-r", "--remove", action="store_true",
                        help="stop tracking an AppImage (keeps the file)")
    parser.add_argument("--asset", metavar="REGEX",
                        help="select the matching release asset for --add")
    parser.add_argument("--arch", metavar="ARCH",
                        help="select release asset for this architecture (default: host)")
    parser.add_argument("paths", nargs="*", type=Path, metavar="PATH",
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.asset and not args.add:
        parser.error("--asset requires --add")
    if args.arch and not args.add:
        parser.error("--arch requires --add")
    if args.prune and not args.update:
        parser.error("--prune requires --update")
    if args.add and len(args.paths) > 1:
        parser.error("--add accepts at most one AppImage path")
    if args.remove and len(args.paths) != 1:
        parser.error("--remove requires exactly one AppImage path")
    if args.remove and (args.check or args.update or args.prune):
        parser.error("--remove cannot be combined with check/update")
    if args.remove:
        remove_source(args.paths[0], load_manifest())
        return 0
    if args.add:
        add_source(
            args.paths[0] if args.paths else None,
            args.add, args.asset, args.update, args.prune, load_manifest(), args.arch,
        )
        return 0
    paths = args.paths or [
        path for path in default_directories() if path.is_dir()
    ]
    images = discover(paths)
    if not images:
        print("No AppImages found in the selected directories (default: ~/Desktop and ~/Applications).")
        return 0
    print(f"Found {len(images)} AppImage file(s).", flush=True)
    return run(images, apply=args.update, prune=args.prune)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        raise SystemExit(f"AppImage update failed: {error}")
