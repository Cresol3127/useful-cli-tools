# useful-cli-tools

A small monorepo of command-line tools for Linux. Each tool lives in its own
directory and can be installed independently.

| Tool | What it does |
| --- | --- |
| [`audiofetch`](audiofetch/) | Download audio from YouTube, or clean up and rewrite audio metadata. |
| [`appimage-update`](appimage-update/) | Check and update AppImages, including portable apps that lack embedded update information. |

## Install

Clone the repository, then link the scripts into a directory on your `PATH`:

```sh
git clone https://github.com/Cresol3127/useful-cli-tools.git
cd useful-cli-tools
mkdir -p ~/.local/bin
ln -sf "$PWD/audiofetch/audiofetch" ~/.local/bin/audiofetch
ln -sf "$PWD/appimage-update/appimage_update.py" ~/.local/bin/appimage-update
```

Both tools are self-contained scripts. See each tool's README for dependencies
and usage examples.

## Requirements

- `audiofetch`: Bash, `yt-dlp`, `ffmpeg`, `ffprobe`, `fzf`
- `appimage-update`: Python 3.11+, plus `appimageupdatetool` for AppImages that
  do not have a GitHub release source

## Tests

```sh
python3 -B -m unittest discover -s appimage-update -v
bash -n audiofetch/audiofetch
```

## License

MIT. See [LICENSE](LICENSE).
