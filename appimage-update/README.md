# appimage-update

Check or update all AppImages in `~/Desktop` and `~/Applications` with one
command.

`appimage-update` handles two kinds of AppImages:

1. Apps tracked by a GitHub release in its manifest — useful for portable apps
   that have no embedded update information.
2. Apps with embedded AppImageUpdate information — via `appimageupdatetool`.

## Requirements

- Python 3.11+ (`hashlib.file_digest`)
- Linux
- `appimageupdatetool` for generic AppImages without a tracked GitHub source
- Optional: authenticated `gh` (or `GITHUB_TOKEN`) for GitHub API rate limits

There are no third-party Python packages.

## Install

```sh
mkdir -p ~/.local/bin
ln -sf "$PWD/appimage_update.py" ~/.local/bin/appimage-update
chmod +x appimage_update.py
```

Install the optional AppImageUpdate CLI from
[AppImageUpdate](https://github.com/AppImageCommunity/AppImageUpdate/releases),
or point the script at an existing binary:

```sh
export APPIMAGE_UPDATE_TOOL=/path/to/appimageupdatetool
```

## Usage

Check everything (the default):

```sh
appimage-update
appimage-update --check
```

Update everything, removing old renamed versions only when they are unchanged:

```sh
appimage-update --update
appimage-update --update --prune
```

Check or update selected paths:

```sh
appimage-update ~/Applications/Some.AppImage
appimage-update --update ~/Downloads
```

Track a GitHub release when an AppImage has no embedded update information:

```sh
appimage-update --add owner/repo
appimage-update --add https://github.com/owner/repo
appimage-update --add owner/repo ~/Applications/Some.AppImage
```

If a release has several assets for the host architecture, choose one:

```sh
appimage-update --add owner/repo --asset '.*x86_64\.AppImage'
appimage-update --add owner/repo --arch aarch64
```

`--add` without a path looks for one matching local file, or downloads the
latest release to `~/Applications` when combined with `--update`.

Stop tracking an app (the file is kept):

```sh
appimage-update --remove ~/Applications/Some.AppImage
```

### Options

```text
-c, --check            Check only (default)
-u, --update           Update existing AppImages
-p, --prune            Remove old copies (requires --update)
-a, --add REPO         Track a GitHub repo or URL; path optional
-r, --remove           Stop tracking an AppImage (keeps the file)
--asset REGEX          Select the matching release asset for --add
--arch ARCH            Select the release asset for this architecture
```

Paths default to `~/Desktop` and `~/Applications`.

## GitHub tracking

The manifest lives at:

```text
${XDG_CONFIG_HOME:-~/.config}/appimage-update/sources.json
```

Each entry records the absolute path, repository, asset pattern, and the
installed release tag. The manifest is written atomically with mode `0600`.

When a GitHub release publishes a `sha256:` digest, downloads are verified
against it. If no digest is published, the tool records the installed release
tag and treats the file as unverified until the next update. Existing files are
never overwritten silently.

Only `github.com` repositories are supported. The tool uses `gh auth token`
when available, then `GITHUB_TOKEN`, then anonymous GitHub API requests.

## Tests

```sh
cd appimage-update
python3 -B -m unittest -v
```

## License

MIT. See the repository-wide [LICENSE](../LICENSE).
