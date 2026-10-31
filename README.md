# useful-cli-tools

A small monorepo of command-line tools for Unix-like systems and Linux desktops.
Each tool lives in its own directory and can be installed independently.

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

- `audiofetch`: Bash, `yt-dlp`, `ffmpeg`, `ffprobe`, `fzf` (Linux, macOS, and
  compatible Unix-like systems)
- `appimage-update`: Python 3.11+, plus `appimageupdatetool` for AppImages that
  do not have a GitHub release source (Linux)

## License

MIT. See [LICENSE](LICENSE).

**AI disclosure**: AI assisted with the coding; the ideas and project direction are
the author's original work.
