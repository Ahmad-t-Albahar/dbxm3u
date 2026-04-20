# dbxm3u

Windows-first wxPython app that builds and updates **extended M3U playlists** from **Dropbox folders**.

## Background

I built this app because I couldn't find an Apple TV app that lets me stream Dropbox files in an accessible way.
So I took a different route: using an IPTV player on Apple TV and loading playlists generated from Dropbox folders.

Later, I realized other people could benefit from this too, especially if they want to generate M3U files without having to rely on IPTV-specific conventions.

## What it does

- **Generate** a new M3U from one or more Dropbox folders
- **Update** an existing M3U incrementally (URL-based dedupe)
- **Upload** the playlist to Dropbox and copy a direct playlist link

## Features

- **Profiles**: save sets of Dropbox folders and reuse them.
- **Incremental updates**: merge new items without duplicating existing entries (URL-based).
- **Direct stream URLs**: creates/reuses Dropbox shared links and converts them into streamable URLs.
- **Preview + browsing**: pick folders by browsing Dropbox from inside the app.
- **Configurable media extensions**: set which file types are included.
- **Series/VOD mode (IPTV-oriented)**: optional IPTV-style tags/formatting for players that expect “VOD/Series” conventions.

## Basic workflow

1. Connect Dropbox.
2. Create/select a profile.
3. Add one or more Dropbox folders to the profile.
4. Save a local M3U, or upload it to Dropbox and copy the playlist link.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Windows (primary target)

## Install

**1. Install uv (if you haven't already)**

For Windows (using PowerShell):
```powershell
powershell -ExecutionPolicy ByPass -c "irm [https://astral.sh/uv/install.ps1](https://astral.sh/uv/install.ps1) | iex"
```

*(Alternatively, if you already have Python installed, you can simply run `pip install uv`)*

**2. Install project dependencies**

Once `uv` is installed, navigate to the project directory and run:
```bash
uv sync
```

## Run

To run the application using `uv`'s managed environment:

```bash
uv run dbxm3u.py
```

*(Note: If you configured a script entry point in your `pyproject.toml`, you can also run it via `uv run start`)*

## Connect Dropbox

In the app:

1. `Settings` -> `Run Setup Wizard...`
2. Choose OAuth and click `Connect in Browser`

Notes:

- Credentials are stored via Windows Credential Vault (`keyring`).
- The OAuth flow uses a localhost callback (PKCE).

## Supported media

You can configure extensions in Settings (one per line). Defaults:

```text
.mp3
.wav
.m4a
.flac
.aac
.ogg
.opus
.wma
.aiff
.aif
.ape
.mka
.mp2
.mpga
```

## Privacy / how it works

- The app scans Dropbox folders and creates/reuses Dropbox shared links for files.
- It converts those shared links into direct stream URLs and writes them into the M3U.
- Credentials are stored via `keyring` (Windows Credential Vault integration).

## Known limitations

- Updates use URL-based dedupe and “missing” detection is URL-based.
- Shared-link creation can be rate-limited by Dropbox.

## Project status

This is an actively maintained personal project. It targets Windows first and is intended to be practical and simple to run.

## Developers

### Dropbox app setup (for forks)

If you create your own Dropbox API app, add this redirect URI:

```text
[http://127.0.0.1:53682/oauth2/callback](http://127.0.0.1:53682/oauth2/callback)
```

You can override the embedded app key with:

```text
DBXM3U8_APP_KEY
```

### Build a Windows .exe (PyInstaller)

To compile the executable using `uv`, run:

```bash
uv run pyinstaller --clean dbxm3u.spec
```

Output is in `dist/`.

### Local app data

The app writes state next to the script/exe in `data/`:

- `data/streamer_profiles.json`
- `data/profile_update_settings.json`
- `data/library_manifest.json`
- `data/series_logo.json`

### Debug mode

Set `DBXM3U8_DEBUG` to `1` / `true` / `yes`.