# dbxm3u8 (Dropbox → M3U Playlist Builder + Updater)

`dbxm3u8` is a Windows-first Python app that turns folders in your **Dropbox** into **extended M3U playlists** that can be played/consumed by:

- VLC (desktop/mobile)
- Audio players that support M3U playlists
- IPTV players / VOD libraries (via optional Series/VOD formatting)

The main GUI app is **Smart Streamer** (`dbxm3u8.py`). It focuses on:

- **Fast generation** of playlists from multiple Dropbox folders
- **Stable incremental updates** (add new files without creating duplicates)
- **Player-friendly metadata** (`group-title`, optional `tvg-name`, optional `tvg-logo`)
- Helpful UX: progress UI, preview, conflict resolution choices, and 1‑click update

---

## Contents

- [Quick start](#quick-start)
- [What Smart Streamer does](#what-smart-streamer-does)
- [Key features](#key-features)
- [App tour (UI + menus)](#app-tour-ui--menus)
- [Workflows](#workflows)
- [Series/VOD mode (IPTV-friendly)](#seriesvod-mode-iptv-friendly)
- [M3U format notes](#m3u-format-notes)
- [Local files created by the app](#local-files-created-by-the-app)
- [Apps and scripts](#apps-and-scripts)
- [Troubleshooting / FAQ](#troubleshooting--faq)

---

## Quick start

### 1) Install dependencies

Requirements:

- Python 3.x
- Windows (primary target)

Install packages:

```bash
pip install -r requirements.txt
```

---

## Building a Windows executable (PyInstaller)

This project can be packaged as a Windows GUI `.exe` using PyInstaller.

1. Install dependencies (includes PyInstaller):

```bash
pip install -r requirements.txt
```

2. Build:

```bash
pyinstaller --clean dbxm3u8.spec
```

3. Output:

- The build output will be in `dist/`.
- Run `dist/dbxm3u8.exe`.

Notes:

- The app stores its local state in a `data/` folder next to the running script/exe.

---

## Consumer OAuth (automatic browser login)

When using the Setup Wizard OAuth flow, the app uses a localhost redirect so the user does not have to copy/paste an auth code.

Implementation notes:

- The OAuth flow uses PKCE and stores credentials in Windows Keyring.
- The app is built with an embedded Dropbox App Key by default, and can be overridden with `DBXM3U8_APP_KEY`.

### 2) Launch Smart Streamer

```bash
python dbxm3u8.py
```

### 3) Connect Dropbox (OAuth)

#### For users

1. In the app, open:
   - `Settings` → `Run Setup Wizard…`
2. Choose:
   - `OAuth (App Key + App Secret)`
3. Click:
   - `Connect in Browser`

This uses an automatic browser login and returns to the app.

Credentials are stored securely via Windows Keyring (`keyring`).

#### For developers / forks

This project supports two connection methods:

- OAuth (recommended) via Setup Wizard (automatic browser login + return)
- Access Token (advanced/manual)

If you create your own Dropbox API app (for a fork/dev build):

1. Create a Dropbox API app:
   - https://www.dropbox.com/developers/apps
2. Configure redirect URI (required for automatic OAuth):

```text
http://127.0.0.1:53682/oauth2/callback
```

3. Set the App Key used by the build:
   - embed it in the code (default), or
   - set `DBXM3U8_APP_KEY`

### OAuth warning you may see during authentication

You might see a Dropbox warning while authenticating that looks like:

"You might be putting your data at risk. Why am I seeing this warning? This app only has a small number of users and may not be the app you were intending to link."

This can happen when an app is new or has a small number of users.

- If you want to verify that the app is secure, feel free to review the code in this repository.

---

## What Smart Streamer does

Smart Streamer helps you build and maintain playlists from Dropbox folders.

At a high level:

1. You create a **Profile** (a named set of Dropbox folder paths).
2. The app scans those folders, finds supported media files, and generates M3U entries.
3. For each file, the app creates/reuses a Dropbox **shared link**, converts it to a **direct stream URL**, and writes a clean `#EXTINF + URL` pair.
4. Later, you can **update** an existing M3U by scanning the profile again and merging in **only new items**, deduplicated by URL.

---

## Key features

### Playlist profiles

- Maintain multiple profiles (e.g. `TV`, `Audiobooks`, `Arabic Music`, `Podcasts`).
- Each profile is a list of Dropbox folder paths.

### Extended M3U generation

- Writes proper extended M3U output:
  - `#EXTM3U` header
  - each entry is **two lines**:
    - `#EXTINF ...`
    - direct stream URL

### Natural sorting (optional, per update)

- During updates you can choose to re-sort within each category using a natural sort.
- Useful for episode/track ordering like `1,2,10` instead of `1,10,2`.

### Add to Existing M3U (augmentation)

- `Tools` → `Add to Existing M3U…`
- Loads an existing M3U, lets you select new Dropbox folders, then merges them in.
- Deduplicates by URL to prevent duplicates on repeated runs.

### Update Existing M3U (from Profile)

- `Tools` → `Update Existing M3U (from Profile)…`
- Rescans the folders in the current profile.
- Merges new entries using URL-based dedupe.
- **Preserves existing category order**, and optionally sorts within categories.
- Creates a `.bak` backup when overwriting the same file.

### Conflict resolution UI (URL-not-found)

During update, you can choose:

- Keep old entries even if not found in scan
- Or remove entries that are no longer found in scan (**detection is URL-not-found**)

This is a simple, reliable first version of “conflict resolution”.

### 1‑Click Update (Local + Cloud)

- `Tools` → `1-Click Update (Local + Cloud)`
- Re-runs update using the **last selected local M3U path** and the last chosen update options.
- Overwrites the local file in place (with `.bak`).
- Uploads the updated M3U to Dropbox as `/<profile_name>.m3u`.

### Preview features

- **Preview a profile folder** (button: `Preview`) to browse inside a chosen Dropbox folder.
- **Preview an existing M3U**:
  - `Tools` → `Preview Existing M3U…`
  - shows total entries + per-`group-title` counts

### Menu-driven UX

- Core actions are accessible through the menu bar (with shortcuts).
- `File` → `Exit` closes the app.

---

## App tour (UI + menus)

### Left side: Dropbox Explorer

- Shows folder names for the current Dropbox path.
- Double-click / Enter: enter folder
- Go Up: navigate to parent folder
- Context menu / keyboard shortcuts allow adding selected folders

### Right side: Current profile folders

- Displays the Dropbox folders included in the selected profile.
- `Remove Folder` deletes from the profile.
- `Preview` opens a folder browsing dialog.

### Menus

`File`

- `Exit`

`Actions`

- `Save Profile Locally` (`Ctrl+S`)
- `Upload to Dropbox Cloud` (`Ctrl+U`)
- `Copy Playlist Link` (`Ctrl+L`) (copies a direct link to the uploaded profile M3U)

`Tools`

- `Add to Existing M3U…` (`Ctrl+M`)
- `Update Existing M3U (from Profile)…`
- `1-Click Update (Local + Cloud)`
- `Preview Existing M3U…`

`Settings`

- `Settings` (account + playlist settings)
- `Run Setup Wizard…`

---

## Workflows

### Generate a new playlist locally

1. Select/create a profile.
2. Add Dropbox folders to it.
3. `Actions` → `Save Profile Locally`.

### Generate a playlist in Dropbox Cloud

1. Build your profile.
2. `Actions` → `Upload to Dropbox Cloud`.
3. `Actions` → `Copy Playlist Link` to get a streamable link to that uploaded M3U.

### Add folders into an existing playlist

1. `Tools` → `Add to Existing M3U…` and select a playlist.
2. Select new Dropbox folders to add.
3. Click `Process & Merge New Folders`.
4. Save the merged M3U.

### Keep an existing playlist up to date (incremental)

1. `Tools` → `Update Existing M3U (from Profile)…`
2. Choose:
   - sort within categories?
   - remove missing URLs?
3. Pick the existing M3U file.
4. Save the updated result.

### Daily-driver mode

After you run the update once:

1. `Tools` → `1-Click Update (Local + Cloud)`

It uses your saved profile settings and updates both:

- the local M3U
- the cloud `/dbxm3u8/<profile_name>.m3u`

---

## Series/VOD mode (IPTV-friendly)

Smart Streamer can format output for IPTV “VOD/Series” style libraries.

In Series/VOD mode:

- Entries include IPTV-style tags like:
  - `tvg-name`
  - `tvg-logo`
  - `group-title`
- Naming logic is designed to keep entries unique and stable.

Tip:

- You can set a logo URL in Settings and it will be reused for generated entries.

---

## M3U format notes

Example output (standard mode):

```text
#EXTM3U
#EXTINF:-1 group-title="Audiobooks / Book Name", Track 01.mp3
https://dl.dropboxusercontent.com/...&dl=1
```

Important details:

- `group-title` is derived from the Dropbox folder structure.
- Dropbox shared links are converted to direct stream URLs (host rewritten and forced `dl=1`).
- The app writes clean 2-line entries to stay compatible with IPTV players.

---

## Local files created by the app

These files are created/updated in `./data/` (next to `dbxm3u8.py`):

- `data/streamer_profiles.json`
  - profile name → list of Dropbox folder paths
- `data/library_manifest.json`
  - caching/manifest used by the library logic (when applicable)
- `data/series_logo.json`
  - stores the configured logo URL for Series/VOD mode
- `data/profile_update_settings.json`
  - per-profile settings used by 1‑click update:
    - last local M3U path
    - sort-within-groups choice
    - remove-missing choice

Credentials are stored using `keyring` (Windows credential vault integration):

- Service: `DropboxAudioStreamer_Secure`
- Keys: `app_key`, `app_secret`, `refresh_token`, `access_token`

---

## Apps and scripts

- **`dbxm3u8.py`**
  - Smart Streamer main GUI
- **`async_processor.py`**
  - Async Dropbox scanning + shared-link generation + M3U line generation
- **`progress_window.py`**
  - Progress UI (logs, counts, cancel)
- **`category_reorder.py`**
  - GUI tool to reorder/rename/remove `group-title` categories inside an existing M3U
- **`m3u_fixer.py`**
  - CLI utility: sorts entries and normalizes some formatting
- **`db renamer.py`**
  - Separate Dropbox file manager / renamer tool

---

## Troubleshooting / FAQ

### I can’t connect to Dropbox

- Verify your Dropbox API app is created and you copied the right Key/Secret.
- Use `Settings` → `Run Setup Wizard…` to re-run onboarding.
- If you’re stuck, use “Wipe Vault Credentials” and re-connect.

### Some files are skipped

Common causes:

- unsupported file extension
- Dropbox permissions
- shared link creation failures (rate limits, transient errors)

### My IPTV player shows weird ordering

- Try `Update Existing M3U (from Profile)…` and choose **Yes** for sorting within categories.

### I used “Remove missing” and something disappeared

- Missing detection is currently URL-based.
- If Dropbox links change, a file can appear “missing” even if the file still exists.
- The update process creates a `.bak` backup when overwriting in place—restore that if needed.

### Debug mode

Set the environment variable `DBXM3U8_DEBUG` to one of:

- `1`
- `true`
- `yes`

This enables extra diagnostics in the UI.

---

Last updated: April 2026
