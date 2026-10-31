# audiofetch

Download audio from YouTube, or rewrite the metadata of existing audio files.

`audiofetch` is a Bash script that wraps `yt-dlp` and `ffmpeg` with an
interactive metadata workflow. It can search YouTube with `fzf`, clean up
common title clutter, prompt for artist/title/album, and write tags while
saving a predictable `Artist - Title (Album).ext` filename.

## Requirements

- Bash
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp)
- `ffmpeg` and `ffprobe`
- [`fzf`](https://github.com/junegunn/fzf) for interactive search

On NixOS:

```nix
environment.systemPackages = with pkgs; [ ffmpeg fzf yt-dlp ];
```

## Install

```sh
mkdir -p ~/.local/bin
ln -sf "$PWD/audiofetch" ~/.local/bin/audiofetch
```

Or run it directly:

```sh
./audiofetch --help
```

## Usage

Download from a URL:

```sh
audiofetch 'https://www.youtube.com/watch?v=...'
```

Search YouTube interactively:

```sh
audiofetch
```

Rewrite tags on existing files:

```sh
audiofetch --tag song.opus
audiofetch --tag *.opus
```

Preview tag changes without writing anything:

```sh
audiofetch --tag --dry-run song.opus
```

Show detected metadata without downloading:

```sh
audiofetch --no-download 'https://www.youtube.com/watch?v=...'
```

### Options

```text
-h, --help             Show help
-f, --format <ext>     Audio format (opus, m4a, mp3, flac, etc.; default: opus)
-a, --album <name>     Override album name
-o, --output <dir>     Output directory (default: ~/Music)
--no-edit              Skip the metadata edit prompt
--no-download          Only show metadata
--tag                  Interactively edit one or more files
--dry-run              Show what would be done without changes
--no-album             Skip album metadata
```

## Notes

- YouTube changes its player client regularly. `audiofetch` passes
  `--extractor-args "youtube:player_client=mweb"` to `yt-dlp`; update
  `yt-dlp` first if downloads start failing.
- Titles are cleaned of common suffixes such as `(Official Video)`,
  `[Lyric Video]`, and `- Remastered`.
- Filenames and tags are derived from the interactive values; invalid filename
  characters are removed.
- `--tag` writes tags in place and may rename the file. Keep a backup if the
  metadata matters.

## License

MIT. The repository-wide [LICENSE](../LICENSE) applies.
