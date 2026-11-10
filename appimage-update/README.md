# appimage-update

Check or update all AppImages in `~/Desktop` and `~/Applications` with one
command.

`appimage-update` handles two kinds of AppImages:

1. Apps tracked by a GitHub release in its manifest — useful for portable apps
   that have no embedded update information.
2. Apps with embedded AppImageUpdate information — via `appimageupdatetool`.

For GitHub-tracked apps, it can also create desktop entries and explicit command
wrappers. These integrations follow versioned AppImage filenames when an app is
updated. Command names are opt-in; the tool never exposes every binary inside an
AppImage automatically.

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

Create a desktop entry and command-line launcher for a tracked AppImage:

```sh
appimage-update --add m-uvex/loaf-fm \
  --desktop --name Loaf --icon system-file-manager \
  --mime-type inode/directory --command loaf \
  ~/Applications/Loaf-v0.3.0-x86_64.AppImage
```

`--desktop` generates a `.desktop` entry in `${XDG_DATA_HOME:-~/.local/share}/applications`.
`--name` defaults to a name inferred from the asset filename, while `--icon`
defaults to `application-x-executable`. Repeat `--mime-type` for additional
associations; `--desktop-id` can override the generated `.desktop` filename.

Each `--command NAME` creates an executable wrapper in `~/.local/bin` that runs
the AppImage and forwards its arguments. Repeat it to add more command names, or
set `APPIMAGE_UPDATE_BIN_DIR` to use another command directory. Existing files
that were not created by this tool are never overwritten. Desktop entries and
command wrappers are refreshed when a tracked AppImage changes filename.

Stop tracking an app (the file is kept):

```sh
appimage-update --remove ~/Applications/Some.AppImage
```

This removes update tracking only; the AppImage and any generated launchers remain.

### Options

```text
usage: appimage-update [options] [path ...]

Check or update AppImages.

options:
  -h, --help                 show this help message and exit
  -c, --check                check only (default)
  -u, --update               update existing AppImage files, not install new apps
  -p, --prune, --remove-old  remove old copies (requires --update)
  -a, --add REPO             track a GitHub repo or URL; path optional
  -r, --remove               stop tracking an AppImage (keeps the file)
  --asset REGEX              select the matching release asset for --add
  --arch ARCH                select release asset for this architecture (default: host)
  --desktop                  generate a desktop entry for --add
  --name NAME                desktop display name (requires --desktop)
  --desktop-id ID.desktop    desktop entry filename
  --icon ICON                desktop icon name
  --mime-type MIME           desktop MIME association; may be repeated
  --command NAME             create a command wrapper; may be repeated

Paths default to ~/Desktop and ~/Applications. Add by repo: --add OWNER/REPO or GitHub URL.
```

Paths default to `~/Desktop` and `~/Applications`.

## GitHub tracking

The manifest lives at:

```text
${XDG_CONFIG_HOME:-~/.config}/appimage-update/sources.json
```

Each entry records the absolute path, repository, asset pattern, and installed
release tag. Optional desktop and command integration settings are stored with
the tracked source. The manifest is written atomically with mode `0600`.

When a GitHub release publishes a `sha256:` digest, downloads are verified
against it. If no digest is published, the tool records the installed release
tag and treats the file as unverified until the next update. Existing files are
never overwritten silently.

Only `github.com` repositories are supported. The tool uses `gh auth token`
when available, then `GITHUB_TOKEN`, then anonymous GitHub API requests.

## Acknowledgements

The GitHub-release tracking idea was inspired by
[`Obtainium`](https://github.com/ImranR98/Obtainium), which helps Android users
install and update apps directly from their upstream release sources.

## Tests

```sh
cd appimage-update
python3 -B -m unittest -v
```

## License

MIT. See the repository-wide [LICENSE](../LICENSE).
