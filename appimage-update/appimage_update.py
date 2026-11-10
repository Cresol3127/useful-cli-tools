#!/usr/bin/env python3
"""Check or update all AppImages in ~/Desktop and ~/Applications."""

import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request


REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
VERSION = re.compile(r"\d+(?:\.\d+){1,3}")
COMMAND_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\Z")
DESKTOP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.desktop\Z")
MIME_TYPE = re.compile(r"[A-Za-z0-9.+_-]+/[A-Za-z0-9.+_-]+\Z")
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


def desktop_directory():
    override = os.environ.get("APPIMAGE_UPDATE_DESKTOP_DIR")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")).expanduser()
    return base / "applications"


def command_directory():
    return Path(os.environ.get("APPIMAGE_UPDATE_BIN_DIR", Path.home() / ".local/bin")).expanduser()


def validate_command(name):
    if not isinstance(name, str) or not COMMAND_NAME.fullmatch(name) or name in (".", ".."):
        raise ValueError(f"invalid command name: {name!r}")
    return name


def validate_desktop_id(name):
    if not isinstance(name, str) or not DESKTOP_ID.fullmatch(name) or name in ("..desktop",):
        raise ValueError(f"invalid desktop entry ID: {name!r}")
    return name


def validate_mime_type(value):
    if not isinstance(value, str) or not MIME_TYPE.fullmatch(value):
        raise ValueError(f"invalid MIME type: {value!r}")
    return value


def default_desktop_name(filename):
    stem = Path(filename).stem
    match = VERSION.search(stem)
    if match:
        stem = stem[:match.start()]
        stem = re.sub(r"[-_.]v?$", "", stem, flags=re.IGNORECASE)
    else:
        stem = re.sub(
            r"(?:[-_.](?:linux[-_.]?)?(?:x86[_-]64|amd64|x64|aarch64|arm64|armv[67]l?|armhf|i[3-6]86))+$",
            "",
            stem,
            flags=re.IGNORECASE,
        )
    stem = re.sub(r"[-_]+", " ", stem).strip()
    return stem or Path(filename).stem


def desktop_id_for(name):
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip().lower()).strip(".-")
    if not slug or slug in (".", ".."):
        raise ValueError("desktop name cannot be converted to a safe desktop ID")
    return validate_desktop_id(f"{slug}.desktop")


def integration_source_id(entry):
    identity = f"{entry['repo']}\0{entry.get('asset', '')}"
    return hashlib.sha256(identity.encode()).hexdigest()[:16]


def desktop_value(value):
    if not isinstance(value, str) or any(char in value for char in "\0\r\n"):
        raise ValueError("desktop entry values cannot contain newlines or NUL")
    return value.replace("\\", "\\\\").replace("\t", "\\t")


def desktop_exec_arg(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") + '"'


def write_managed_file(path, content, mode, marker):
    if path.is_symlink():
        raise ValueError(f"refusing to replace a symlink: {path}")
    if path.exists():
        if not path.is_file():
            raise ValueError(f"not a regular file: {path}")
        try:
            old = path.read_text(errors="replace")
        except OSError as error:
            raise ValueError(f"cannot read existing integration {path}: {error}") from error
        if marker not in old:
            raise ValueError(f"refusing to overwrite unmanaged file: {path}")

    path.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def install_integrations(entry):
    commands = [validate_command(command) for command in entry.get("commands", [])]
    if not commands and not entry.get("desktop"):
        return

    image = Path(entry["path"])
    if image.is_symlink() or not image.is_file():
        raise ValueError(f"not a regular AppImage file: {image}")
    source_id = integration_source_id(entry)

    command_paths = {}
    for command in commands:
        marker = f"# appimage-update-source: {source_id}"
        path = command_directory() / command
        content = (
            "#!/usr/bin/env sh\n"
            f"{marker}\n"
            f"exec {shlex.quote(str(image))} \"$@\"\n"
        )
        write_managed_file(path, content, 0o755, marker)
        command_paths[command] = path
        print(f"Command wrapper: {path}", flush=True)

    if not entry.get("desktop"):
        return

    name = desktop_value(entry.get("desktop_name") or default_desktop_name(image.name))
    desktop_id = validate_desktop_id(entry.get("desktop_id") or desktop_id_for(name))
    icon = desktop_value(entry.get("icon") or "application-x-executable")
    mime_types = [validate_mime_type(value) for value in entry.get("mime_types", [])]
    launcher = command_paths[commands[0]] if commands else image
    marker = f"X-AppImage-Update-Source={source_id}"
    lines = [
        "[Desktop Entry]",
        "Version=1.0",
        "Type=Application",
        f"Name={name}",
        f"Exec={desktop_exec_arg(str(launcher))} %U",
        f"Icon={icon}",
        "Terminal=false",
        "StartupNotify=true",
        marker,
    ]
    if mime_types:
        lines.append(f"MimeType={';'.join(mime_types)};")
    lines.append("")
    path = desktop_directory() / desktop_id
    write_managed_file(path, "\n".join(lines), 0o644, marker)
    print(f"Desktop entry: {path}", flush=True)


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
        desktop = item.get("desktop", False)
        if not isinstance(desktop, bool):
            raise ValueError(f"invalid desktop integration flag in manifest: {path}")
        if desktop:
            entry["desktop"] = True
        if item.get("desktop_name") is not None:
            entry["desktop_name"] = desktop_value(item["desktop_name"])
        if item.get("desktop_id") is not None:
            entry["desktop_id"] = validate_desktop_id(item["desktop_id"])
        if item.get("icon") is not None:
            entry["icon"] = desktop_value(item["icon"])
        commands = item.get("commands", [])
        if not isinstance(commands, list):
            raise ValueError(f"invalid commands in manifest: {path}")
        if commands:
            validated = [validate_command(command) for command in commands]
            if len(set(validated)) != len(validated):
                raise ValueError(f"duplicate commands in manifest: {path}")
            entry["commands"] = validated
        mime_types = item.get("mime_types", [])
        if not isinstance(mime_types, list):
            raise ValueError(f"invalid MIME types in manifest: {path}")
        if mime_types:
            validated = [validate_mime_type(value) for value in mime_types]
            if len(set(validated)) != len(validated):
                raise ValueError(f"duplicate MIME types in manifest: {path}")
            entry["mime_types"] = validated
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
            headers = getattr(response, "headers", None)
            content_length = headers.get("Content-Length") if headers else None
            try:
                total = int(content_length) if content_length else 0
            except (TypeError, ValueError):
                total = 0
            downloaded = 0
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
                downloaded += len(chunk)
                if total:
                    width = 24
                    filled = min(width, int(width * downloaded / total))
                    progress = f"[{('=' * filled).ljust(width)}] {min(100, downloaded * 100 // total):3d}%"
                    progress += f" ({downloaded / 1024**2:.1f}/{total / 1024**2:.1f} MiB)"
                else:
                    progress = f"{downloaded / 1024**2:.1f} MiB"
                print(f"\rDownloading {destination.name}: {progress}", end="", file=sys.stderr, flush=True)
            if downloaded:
                print(file=sys.stderr, flush=True)
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
            if apply:
                install_integrations(entry)
            return True
        if apply:
            install_integrations(entry)
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
    install_integrations(entry)
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


def add_source(
    path, repo, asset_pattern, apply, prune, sources, arch=None,
    desktop=False, desktop_name=None, desktop_id=None, icon=None,
    commands=None, mime_types=None,
):
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
    previous = sources.get(str(image), {})
    entry = {
        "path": str(image),
        "repo": canonical if isinstance(canonical, str) and REPO.fullmatch(canonical) else repo,
        "asset": pattern,
        "version": tag if current else None,
    }
    if desktop or previous.get("desktop"):
        entry["desktop"] = True
        entry["desktop_name"] = desktop_value(
            desktop_name or previous.get("desktop_name") or default_desktop_name(asset["name"])
        )
        entry["desktop_id"] = validate_desktop_id(
            desktop_id or previous.get("desktop_id") or desktop_id_for(entry["desktop_name"])
        )
        icon_value = icon if icon is not None else previous.get("icon")
        if icon_value:
            entry["icon"] = desktop_value(icon_value)
    commands = list(dict.fromkeys([
        *previous.get("commands", []),
        *(commands or []),
    ]))
    if commands:
        entry["commands"] = [validate_command(command) for command in commands]
    mime_types = list(dict.fromkeys([
        *previous.get("mime_types", []),
        *(mime_types or []),
    ]))
    if mime_types:
        entry["mime_types"] = [validate_mime_type(value) for value in mime_types]
    sources[str(image)] = entry
    save_manifest(sources)
    print(f"Tracking {image.name} from {entry['repo']}; latest release {tag}.", flush=True)
    if current:
        print("  Local file matches the latest release.", flush=True)
    else:
        print("  Local file is not verified as current; run --update to download it.", flush=True)
    if apply and not current and update_tracked(entry, apply=True, prune=prune):
        save_manifest(sources)
    install_integrations(entry)


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
    updates_available = 0
    interactive_check = not apply and sys.stdout.isatty()
    for image in images:
        if image in handled:
            continue
        handled.add(image)
        output = io.StringIO()
        errors = io.StringIO()
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                if str(image) in tracked:
                    manifest_changed |= update_tracked(tracked[str(image)], apply=apply, prune=prune)
                else:
                    if tool is None:
                        tool = generic_tool()
                    flags = (["--remove-old"] if prune else []) if apply else ["--check-for-update"]
                    result = subprocess.run(
                        [tool, *flags, str(image)], cwd=image.parent,
                        capture_output=not apply, text=not apply,
                    )
                    if not apply and result.returncode == 1:
                        output.write("Update available.\n")
                    elif result.returncode != 0:
                        detail = "\n".join(filter(None, (
                            getattr(result, "stdout", ""), getattr(result, "stderr", ""),
                        ))).strip()
                        raise ValueError(
                            f"AppImageUpdate exited {result.returncode}. This app may lack embedded "
                            "update information; track its GitHub release with "
                            f"--add OWNER/REPO [--asset REGEX] {image}"
                            + (f"\n{detail}" if detail else "")
                        )
                    elif not apply:
                        output.write("Already current.\n")
            if apply:
                print(f"Updating {image.name}")
                if output.getvalue().strip():
                    print(output.getvalue().rstrip())
                if errors.getvalue().strip():
                    print(errors.getvalue().rstrip(), file=sys.stderr)
            else:
                detail = output.getvalue()
                match = re.search(r"latest ([^;]+); (current|update available)", detail)
                if match:
                    state = "Up to date" if match.group(2) == "current" else "Update available"
                    state += f" (latest {match.group(1)})"
                elif "Update available." in detail:
                    state = "Update available"
                else:
                    state = "Up to date"
                updates_available += state.startswith("Update available")
                status = f"{image.name}: {state}"
                if interactive_check:
                    print(f"\r\033[K{status}", end="", flush=True)
                else:
                    print(status)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            failures += 1
            detail = "\n".join(part.strip() for part in (output.getvalue(), errors.getvalue()) if part.strip())
            if interactive_check:
                print(f"\r\033[K{image.name}: FAILED", flush=True)
            print(f"{image.name}: FAILED: {error}" + (f"\n{detail}" if detail else ""), file=sys.stderr, flush=True)
    if manifest_changed:
        save_manifest(tracked)
    if apply:
        print(f"Update finished: {len(handled)} app(s), {failures} failure(s).")
    else:
        if interactive_check:
            print()
        print()
        print(f"Check finished: {len(images)} file(s), {updates_available} update(s) available, {failures} failure(s).")
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(
        prog="appimage-update",
        usage="%(prog)s [options] [path ...]",
        description="Check or update AppImages.",
        formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=34, width=100),
        epilog=("Paths default to ~/Desktop and ~/Applications. Add by repo: --add OWNER/REPO or "
                "GitHub URL. --desktop and --command configure launch integrations for tracked apps."),
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
    parser.add_argument("--desktop", action="store_true",
                        help="create a desktop entry for the tracked AppImage")
    parser.add_argument("--name", "--desktop-name", dest="desktop_name", metavar="NAME",
                        help="display name for --desktop (default: inferred from asset name)")
    parser.add_argument("--desktop-id", metavar="ID.desktop",
                        help="desktop entry filename (default: derived from its name)")
    parser.add_argument("--icon", metavar="ICON",
                        help="icon theme name for --desktop (default: application-x-executable)")
    parser.add_argument("--mime-type", action="append", default=[], metavar="MIME",
                        help="MIME type handled by --desktop; may be repeated")
    parser.add_argument("--command", action="append", default=[], metavar="NAME",
                        help="create a ~/.local/bin wrapper; may be repeated (tracked apps only)")
    parser.add_argument("paths", nargs="*", type=Path, metavar="PATH",
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.asset and not args.add:
        parser.error("--asset requires --add")
    if args.arch and not args.add:
        parser.error("--arch requires --add")
    if (args.desktop or args.desktop_name or args.desktop_id or args.icon or args.mime_type or args.command) and not args.add:
        parser.error("desktop and command options require --add")
    if (args.desktop_name or args.desktop_id or args.icon or args.mime_type) and not args.desktop:
        parser.error("--name, --desktop-id, --icon, and --mime-type require --desktop")
    if args.prune and not args.update:
        parser.error("--prune requires --update")
    if args.add and len(args.paths) > 1:
        parser.error("--add accepts at most one AppImage path")
    if args.remove and len(args.paths) != 1:
        parser.error("--remove requires exactly one AppImage path")
    if args.remove and (args.check or args.update or args.prune or args.desktop or args.command):
        parser.error("--remove cannot be combined with check/update")
    if args.remove:
        remove_source(args.paths[0], load_manifest())
        return 0
    if args.add:
        add_source(
            args.paths[0] if args.paths else None,
            args.add, args.asset, args.update, args.prune, load_manifest(), args.arch,
            desktop=args.desktop,
            desktop_name=args.desktop_name,
            desktop_id=args.desktop_id,
            icon=args.icon,
            commands=args.command,
            mime_types=args.mime_type,
        )
        return 0
    paths = args.paths or [
        path for path in default_directories() if path.is_dir()
    ]
    images = discover(paths)
    if not images:
        print("No AppImages found in the selected directories (default: ~/Desktop and ~/Applications).")
        return 0
    return run(images, apply=args.update, prune=args.prune)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        raise SystemExit(f"AppImage update failed: {error}")
