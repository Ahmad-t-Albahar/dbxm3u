import wx
import dropbox
import keyring
import webbrowser
import os
import json
import datetime
import traceback
import time
import threading
import asyncio
import sys

from dropbox import DropboxOAuth2FlowNoRedirect
from progress_window import ProgressWindow
from async_processor import run_async_processing
from onboarding_wizard import run_setup_wizard
from link_utils import get_or_create_shared_link, to_direct_stream_url

# Configuration Constants
SERVICE_NAME = "DropboxAudioStreamer_Secure"
APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
DATA_DIR = os.path.join(APP_DIR, "data")

PROFILES_FILE = os.path.join(DATA_DIR, "streamer_profiles.json")
MANIFEST_FILE = os.path.join(DATA_DIR, "library_manifest.json")
PROFILE_UPDATE_SETTINGS_FILE = os.path.join(DATA_DIR, "profile_update_settings.json")
MEDIA_EXTENSIONS_FILE = os.path.join(DATA_DIR, "media_extensions.json")
SERIES_LOGO_FILE = os.path.join(DATA_DIR, "series_logo.json")
REMOTE_PLAYLIST_FOLDER = "/dbxm3u8"
DEBUG_MODE = os.environ.get("DBXM3U8_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

DEFAULT_MEDIA_EXTENSIONS = [
    '.mp3', '.wav', '.m4a', '.flac', '.aac',
    '.ogg', '.opus', '.wma', '.aiff', '.aif',
    '.ape', '.mka', '.mp2', '.mpga',
    '.m4b',
    '.mp4', '.mkv', '.avi', '.mov', '.m4v',
    '.webm', '.ts',
]


class SettingsDialog(wx.Dialog):
    """Settings dialog for Dropbox authentication management"""
    def __init__(self, parent, app_key, app_secret, refresh_token, series_mode: bool, series_logo: str, media_extensions):
        super().__init__(parent, title="Settings", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.parent = parent

        self.app_key = app_key
        self.app_secret = app_secret
        self.refresh_token = refresh_token
        self.series_mode = bool(series_mode)
        self.series_logo = (series_logo or "").strip()
        self.media_extensions = list(media_extensions or [])

        vbox = wx.BoxSizer(wx.VERTICAL)

        notebook = wx.Notebook(self)
        vbox.Add(notebook, 1, wx.EXPAND | wx.ALL, 10)

        # --- TAB: ACCOUNT ---
        account_panel = wx.Panel(notebook)
        account_vbox = wx.BoxSizer(wx.VERTICAL)

        creds_box = wx.StaticBox(account_panel, label="API Credentials")
        creds_sizer = wx.StaticBoxSizer(creds_box, wx.VERTICAL)

        grid = wx.FlexGridSizer(rows=2, cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        grid.Add(wx.StaticText(account_panel, label="App Key:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.key_input = wx.TextCtrl(account_panel, value=self.app_key or "", style=wx.TE_PASSWORD)
        self.key_input.SetHint("App Key")
        grid.Add(self.key_input, 1, wx.EXPAND)

        grid.Add(wx.StaticText(account_panel, label="App Secret:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.secret_input = wx.TextCtrl(account_panel, value=self.app_secret or "", style=wx.TE_PASSWORD)
        self.secret_input.SetHint("App Secret")
        grid.Add(self.secret_input, 1, wx.EXPAND)

        creds_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)

        save_creds_btn = wx.Button(account_panel, label="Save Credentials")
        save_creds_btn.Bind(wx.EVT_BUTTON, self.on_save_creds)
        creds_sizer.Add(save_creds_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        account_vbox.Add(creds_sizer, 0, wx.EXPAND | wx.ALL, 10)

        auth_box = wx.StaticBox(account_panel, label="Account Connection")
        auth_sizer = wx.StaticBoxSizer(auth_box, wx.VERTICAL)

        self.status_text = wx.StaticText(account_panel, label="")
        auth_sizer.Add(self.status_text, 0, wx.ALL, 10)

        login_btn = wx.Button(account_panel, label="Connect to Dropbox")
        login_btn.Bind(wx.EVT_BUTTON, self.on_login)
        auth_sizer.Add(login_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        if self.refresh_token:
            login_btn.SetLabel("Connected")
            login_btn.Enable(False)

        account_vbox.Add(auth_sizer, 0, wx.EXPAND | wx.ALL, 10)

        danger_box = wx.StaticBox(account_panel, label="Danger Zone")
        danger_sizer = wx.StaticBoxSizer(danger_box, wx.VERTICAL)
        wipe_btn = wx.Button(account_panel, label="Wipe Vault Credentials")
        wipe_btn.SetForegroundColour(wx.RED)
        wipe_btn.Bind(wx.EVT_BUTTON, self.on_wipe_vault)
        danger_sizer.Add(wipe_btn, 0, wx.ALL, 10)
        account_vbox.Add(danger_sizer, 0, wx.EXPAND | wx.ALL, 10)

        account_panel.SetSizer(account_vbox)
        notebook.AddPage(account_panel, "Account")

        # --- TAB: PLAYLIST ---
        playlist_panel = wx.Panel(notebook)
        playlist_vbox = wx.BoxSizer(wx.VERTICAL)

        series_box = wx.StaticBox(playlist_panel, label="Series/VOD Mode")
        series_sizer = wx.StaticBoxSizer(series_box, wx.VERTICAL)

        self.series_checkbox = wx.CheckBox(playlist_panel, label="Enable Series/VOD Mode (IPTV Players - formats as S01 Exx)")
        self.series_checkbox.SetValue(self.series_mode)
        self.series_checkbox.SetToolTip("When enabled, files are formatted with episode numbers for IPTV VOD/Series libraries")
        series_sizer.Add(self.series_checkbox, 0, wx.ALL, 10)

        logo_row = wx.BoxSizer(wx.HORIZONTAL)
        logo_row.Add(wx.StaticText(playlist_panel, label="Logo URL:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.series_logo_input = wx.TextCtrl(playlist_panel, value=self.series_logo)
        self.series_logo_input.SetHint("Enter URL to logo image (optional)")
        logo_row.Add(self.series_logo_input, 1, wx.EXPAND)
        series_sizer.Add(logo_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        playlist_vbox.Add(series_sizer, 0, wx.EXPAND | wx.ALL, 10)

        ext_box = wx.StaticBox(playlist_panel, label="Media Extensions")
        ext_sizer = wx.StaticBoxSizer(ext_box, wx.VERTICAL)
        ext_sizer.Add(
            wx.StaticText(playlist_panel, label="One extension per line (include the dot)."),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP,
            10,
        )
        self.extensions_input = wx.TextCtrl(
            playlist_panel,
            value="\n".join(self.media_extensions),
            style=wx.TE_MULTILINE,
        )
        ext_sizer.Add(self.extensions_input, 1, wx.EXPAND | wx.ALL, 10)
        playlist_vbox.Add(ext_sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        playlist_panel.SetSizer(playlist_vbox)
        notebook.AddPage(playlist_panel, "Playlist")

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(self, wx.ID_OK)
        cancel_btn = wx.Button(self, wx.ID_CANCEL)
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        vbox.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizerAndFit(vbox)
        self.SetMinSize((560, 420))

        self.SetAffirmativeId(wx.ID_OK)
        self.SetEscapeId(wx.ID_CANCEL)

        ok_btn.SetDefault()

        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self._on_cancel, id=wx.ID_CANCEL)
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)

        self._refresh_status_text()
        self.CentreOnParent()

    def _on_activate(self, event):
        if event.GetActive():
            self.Raise()
        event.Skip()

    def _on_ok(self, event):
        wx.CallAfter(self.EndModal, wx.ID_OK)

    def _on_cancel(self, event):
        wx.CallAfter(self.EndModal, wx.ID_CANCEL)

    def _refresh_status_text(self):
        if self.refresh_token:
            self.status_text.SetLabel("Connected to Dropbox")
            self.status_text.SetForegroundColour(wx.Colour(46, 125, 50))

    def get_playlist_values(self):
        raw = self.extensions_input.GetValue() if hasattr(self, 'extensions_input') else ""
        exts = []
        for line in (raw or "").splitlines():
            s = (line or "").strip().lower()
            if not s:
                continue
            if not s.startswith('.'):
                s = '.' + s
            if s not in exts:
                exts.append(s)
        return bool(self.series_checkbox.GetValue()), self.series_logo_input.GetValue().strip(), exts

    def on_save_creds(self, event):
        """Save API credentials to OS vault"""
        key = self.key_input.GetValue().strip()
        secret = self.secret_input.GetValue().strip()

        if not key or not secret:
            wx.MessageBox("Both App Key and App Secret are required.", "Missing Credentials", wx.OK | wx.ICON_WARNING)
            self.key_input.SetFocus()
            return

        keyring.set_password(SERVICE_NAME, "app_key", key)
        keyring.set_password(SERVICE_NAME, "app_secret", secret)
        self.app_key = key
        self.app_secret = secret
        wx.MessageBox("Credentials saved to OS Vault.", "Saved", wx.OK | wx.ICON_INFORMATION)

    def on_login(self, event):
        """Authenticate with Dropbox"""
        if not self.app_key or not self.app_secret:
            wx.MessageBox("Please save your App Key and Secret first.", "Missing Credentials", wx.OK | wx.ICON_WARNING)
            self.key_input.SetFocus()
            return

        try:
            flow = DropboxOAuth2FlowNoRedirect(self.app_key, self.app_secret, token_access_type='offline')
            auth_url = flow.start()
            webbrowser.open(auth_url)

            dlg = wx.TextEntryDialog(self, "Paste the authorization code from your browser:", "Dropbox Authentication")
            if dlg.ShowModal() == wx.ID_OK:
                code = dlg.GetValue().strip()
                if code:
                    try:
                        res = flow.finish(code)
                        keyring.set_password(SERVICE_NAME, "refresh_token", res.refresh_token)
                        self.refresh_token = res.refresh_token
                        wx.MessageBox("Successfully authenticated with Dropbox!", "Connected", wx.OK | wx.ICON_INFORMATION)
                        self._refresh_status_text()
                    except Exception as e:
                        wx.MessageBox(f"Authentication failed: {e}", "Error", wx.OK | wx.ICON_ERROR)
            dlg.Destroy()
        except Exception as e:
            wx.MessageBox(f"Failed to start authentication: {e}", "Error", wx.OK | wx.ICON_ERROR)

    def on_wipe_vault(self, event):
        confirm = wx.MessageDialog(
            self,
            "This will delete App Key, App Secret, and Refresh Token from the OS Vault.\n\nContinue?",
            "Confirm Wipe",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        )
        res = confirm.ShowModal()
        if res == wx.ID_YES:
            if hasattr(self.parent, 'on_reset'):
                self.parent.on_reset(event)
            wx.CallAfter(self.EndModal, wx.ID_CANCEL)
        confirm.Destroy()

        if res != wx.ID_YES:
            self.Raise()
            self.SetFocus()


class FolderPreviewDialog(wx.Dialog):
    def __init__(self, parent, dbx, start_path):
        super().__init__(parent, title="Folder Preview", size=(650, 500))

        self.dbx = dbx
        self.current_path = start_path
        self.item_paths = []
        self.item_kinds = []

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.path_label = wx.StaticText(panel, label="")
        vbox.Add(self.path_label, 0, wx.EXPAND | wx.ALL, 10)

        self.listbox = wx.ListBox(panel, style=wx.LB_SINGLE)
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_open_selected)
        vbox.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        up_btn = wx.Button(panel, label="Go Up")
        up_btn.Bind(wx.EVT_BUTTON, self.on_go_up)
        btn_row.Add(up_btn, 0, wx.RIGHT, 10)

        close_btn = wx.Button(panel, id=wx.ID_CLOSE)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        btn_row.Add(close_btn, 0)
        vbox.Add(btn_row, 0, wx.ALL, 10)

        panel.SetSizer(vbox)
        self.refresh_listing()

    def refresh_listing(self):
        self.listbox.Clear()
        self.item_paths = []
        self.item_kinds = []
        self.path_label.SetLabel(self.current_path or "/")

        try:
            res = self.dbx.files_list_folder(self.current_path)
        except Exception as e:
            wx.MessageBox(f"Failed to list folder:\n\n{e}", "Error", wx.OK | wx.ICON_ERROR)
            return

        folders = []
        files = []
        for entry in res.entries:
            if isinstance(entry, dropbox.files.FolderMetadata):
                folders.append((entry.name, entry.path_display))
            elif isinstance(entry, dropbox.files.FileMetadata):
                files.append((entry.name, entry.path_display))

        folders.sort(key=lambda x: x[0].lower())
        files.sort(key=lambda x: x[0].lower())

        for name, full_path in folders:
            self.listbox.Append(f"[Folder] {name}")
            self.item_paths.append(full_path)
            self.item_kinds.append('folder')

        for name, full_path in files:
            self.listbox.Append(name)
            self.item_paths.append(full_path)
            self.item_kinds.append('file')

        self.Layout()

    def on_open_selected(self, event):
        idx = self.listbox.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        if idx >= len(self.item_paths) or idx >= len(self.item_kinds):
            return
        if self.item_kinds[idx] != 'folder':
            return
        next_path = self.item_paths[idx]
        if not next_path:
            return
        self.current_path = next_path
        self.refresh_listing()

    def on_go_up(self, event):
        if not self.current_path:
            return
        parent = os.path.dirname(self.current_path)
        if parent == self.current_path:
            return
        self.current_path = parent
        self.refresh_listing()


class SmartStreamer(wx.Frame):
    def __init__(self, parent, title):
        super(SmartStreamer, self).__init__(parent, title=title, size=(1000, 800))
        os.makedirs(DATA_DIR, exist_ok=True)
        self.dbx = None
        self.current_dropbox_path = ""

        self.explorer_paths = []

        # Load Security from OS Vault
        self.app_key = keyring.get_password(SERVICE_NAME, "app_key")
        self.app_secret = keyring.get_password(SERVICE_NAME, "app_secret")
        self.refresh_token = keyring.get_password(SERVICE_NAME, "refresh_token")
        self.access_token = keyring.get_password(SERVICE_NAME, "access_token")

        # Data Persistence
        self.profiles = self.load_data(PROFILES_FILE, {"Default": []})
        self.manifest = self.load_data(MANIFEST_FILE, {})
        self.profile_update_settings = self.load_data(PROFILE_UPDATE_SETTINGS_FILE, {})
        self.media_extensions = self.load_data(MEDIA_EXTENSIONS_FILE, {'extensions': DEFAULT_MEDIA_EXTENSIONS}).get('extensions', DEFAULT_MEDIA_EXTENSIONS)
        if not isinstance(self.media_extensions, list) or not self.media_extensions:
            self.media_extensions = list(DEFAULT_MEDIA_EXTENSIONS)
        self.current_profile = "Default"

        # M3U Augmentation State
        self.loaded_m3u_file = None
        self.loaded_m3u_entries = []
        self.augment_folders = []

        # Series Mode State
        self.series_mode = False
        self.series_logo = self.load_data(SERIES_LOGO_FILE, {'url': ''}).get('url', '')

        self.init_ui()
        if self.has_auth():
            self.connect_to_dropbox()
            self.load_dropbox_explorer("")
        else:
            wx.CallAfter(self._maybe_prompt_setup)

        self.refresh_ui()
        self.Centre()

    def _maybe_prompt_setup(self):
        if self.has_auth():
            return
        dlg = wx.MessageDialog(
            self,
            "Dropbox is not connected yet. Run the Setup Wizard now?",
            "Not Connected",
            wx.YES_NO | wx.YES_DEFAULT | wx.ICON_INFORMATION,
        )
        res = dlg.ShowModal()
        dlg.Destroy()
        if res == wx.ID_YES:
            self.on_run_setup_wizard(None)

    def init_ui(self):
        # --- MENU BAR ---
        menubar = wx.MenuBar()

        file_menu = wx.Menu()
        exit_item = file_menu.Append(wx.ID_EXIT, "Exit\tAlt+F4")
        self.Bind(wx.EVT_MENU, lambda _e: self.Close(True), exit_item)
        menubar.Append(file_menu, "&File")

        actions_menu = wx.Menu()
        save_local_item = actions_menu.Append(wx.ID_ANY, "Save Profile Locally\tCtrl+S")
        upload_item = actions_menu.Append(wx.ID_ANY, "Upload to Dropbox Cloud\tCtrl+U")
        actions_menu.AppendSeparator()
        copy_link_item = actions_menu.Append(wx.ID_ANY, "Copy Playlist Link\tCtrl+L")
        self.Bind(wx.EVT_MENU, self.on_save_local, save_local_item)
        self.Bind(wx.EVT_MENU, self.on_smart_sync, upload_item)
        self.Bind(wx.EVT_MENU, self.on_copy_link, copy_link_item)
        menubar.Append(actions_menu, "&Actions")

        tools_menu = wx.Menu()
        augment_item = tools_menu.Append(wx.ID_ANY, "Add to Existing M3U…\tCtrl+M")
        self.Bind(wx.EVT_MENU, self.on_augment_m3u, augment_item)
        update_item = tools_menu.Append(wx.ID_ANY, "Update Existing M3U (from Profile)…")
        self.Bind(wx.EVT_MENU, self.on_update_existing_m3u, update_item)
        quick_update_item = tools_menu.Append(wx.ID_ANY, "1-Click Update (Local + Cloud)")
        self.Bind(wx.EVT_MENU, self.on_quick_update, quick_update_item)
        preview_existing_item = tools_menu.Append(wx.ID_ANY, "Preview Existing M3U…")
        self.Bind(wx.EVT_MENU, self.on_preview_existing_m3u, preview_existing_item)
        menubar.Append(tools_menu, "&Tools")

        settings_menu = wx.Menu()
        settings_item = settings_menu.Append(wx.ID_ANY, "&Settings\tAlt+S", "Account and playlist settings")
        self.Bind(wx.EVT_MENU, self.on_open_settings, settings_item)
        wizard_item = settings_menu.Append(wx.ID_ANY, "Run Setup &Wizard…\tAlt+W", "Guided setup")
        self.Bind(wx.EVT_MENU, self.on_run_setup_wizard, wizard_item)

        if DEBUG_MODE:
            settings_menu.AppendSeparator()
            diag_item = settings_menu.Append(wx.ID_ANY, "Debug: Connection Status…", "Show debug connection info")
            self.Bind(wx.EVT_MENU, self.on_debug_connection_status, diag_item)

        menubar.Append(settings_menu, "&Settings")
        self.SetMenuBar(menubar)

        self.panel = wx.Panel(self)
        self.main_vbox = wx.BoxSizer(wx.VERTICAL)

        # --- PROFILE & ACTIONS ---
        self.prof_box = wx.StaticBox(self.panel, label="Playlist Profile")
        p_sizer = wx.StaticBoxSizer(self.prof_box, wx.HORIZONTAL)

        self.prof_choice = wx.Choice(self.panel, choices=list(self.profiles.keys()))
        self.prof_choice.SetStringSelection(self.current_profile)
        self.prof_choice.Bind(wx.EVT_CHOICE, self.on_switch_profile)

        new_btn = wx.Button(self.panel, label="New"); new_btn.Bind(wx.EVT_BUTTON, self.on_new_profile)
        ren_btn = wx.Button(self.panel, label="Rename"); ren_btn.Bind(wx.EVT_BUTTON, self.on_rename_profile)
        del_btn = wx.Button(self.panel, label="Delete"); del_btn.Bind(wx.EVT_BUTTON, self.on_delete_profile)

        p_sizer.AddMany([
            (self.prof_choice, 1, wx.CENTER | wx.RIGHT, 10),
            (new_btn, 0, wx.RIGHT, 5),
            (ren_btn, 0, wx.RIGHT, 5),
            (del_btn, 0),
        ])
        self.main_vbox.Add(p_sizer, 0, wx.EXPAND | wx.ALL, 10)

        # --- STEP 3: DUAL-LIST EXPLORER ---
        self.lists_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Left: Dropbox Explorer
        l_vbox = wx.BoxSizer(wx.VERTICAL)
        l_vbox.Add(wx.StaticText(self.panel, label="Dropbox"))
        self.explorer_path_label = wx.StaticText(self.panel, label="")
        l_vbox.Add(self.explorer_path_label, 0, wx.EXPAND | wx.TOP, 2)
        self.explorer = wx.ListBox(self.panel, style=wx.LB_EXTENDED)
        self.explorer.Bind(wx.EVT_LISTBOX_DCLICK, self.on_explorer_dclick)
        self.explorer.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)  # Applications Key support
        # Use CHAR_HOOK to intercept Enter key before ListBox processes it
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        l_vbox.Add(self.explorer, 1, wx.EXPAND | wx.TOP, 5)

        # Navigation buttons
        nav_box = wx.BoxSizer(wx.HORIZONTAL)
        back_btn = wx.Button(self.panel, label="Go Up"); back_btn.Bind(wx.EVT_BUTTON, self.on_go_back)
        enter_btn = wx.Button(self.panel, label="Enter Folder"); enter_btn.Bind(wx.EVT_BUTTON, self.on_enter_folder)
        nav_box.Add(back_btn, 1, wx.EXPAND | wx.RIGHT, 5)
        nav_box.Add(enter_btn, 1, wx.EXPAND)
        l_vbox.Add(nav_box, 0, wx.EXPAND | wx.TOP, 5)

        # Right: Playlist Folders
        r_vbox = wx.BoxSizer(wx.VERTICAL)
        r_vbox.Add(wx.StaticText(self.panel, label="Included Folders in this M3U:"))
        self.playlist_list = wx.ListBox(self.panel, choices=self.profiles[self.current_profile])
        r_vbox.Add(self.playlist_list, 1, wx.EXPAND | wx.TOP, 5)

        prof_btns = wx.BoxSizer(wx.HORIZONTAL)
        self.preview_btn = wx.Button(self.panel, label="Preview")
        self.preview_btn.Bind(wx.EVT_BUTTON, self.on_preview_profile_folder)
        rem_btn = wx.Button(self.panel, label="Remove Folder"); rem_btn.Bind(wx.EVT_BUTTON, self.on_remove_folder)
        prof_btns.Add(self.preview_btn, 1, wx.EXPAND | wx.RIGHT, 5)
        prof_btns.Add(rem_btn, 1, wx.EXPAND)
        r_vbox.Add(prof_btns, 0, wx.EXPAND | wx.TOP, 5)

        self.lists_sizer.AddMany([(l_vbox, 1, wx.EXPAND | wx.ALL, 5), (r_vbox, 1, wx.EXPAND | wx.ALL, 5)])
        self.main_vbox.Add(self.lists_sizer, 1, wx.EXPAND | wx.ALL, 5)

        # --- STEP 4: ACTIONS ---
        # Menu-driven actions still rely on these objects for enable/disable logic
        self.save_local_btn = wx.Button(self.panel, label="Save Profile Locally", size=(-1, 50))
        self.save_local_btn.Bind(wx.EVT_BUTTON, self.on_save_local)
        self.save_local_btn.Hide()

        self.sync_btn = wx.Button(self.panel, label="Upload to Dropbox Cloud", size=(-1, 50))
        self.sync_btn.Bind(wx.EVT_BUTTON, self.on_smart_sync)
        self.sync_btn.Hide()

        self.augment_btn = wx.Button(self.panel, label="Add to Existing M3U", size=(-1, 50))
        self.augment_btn.Bind(wx.EVT_BUTTON, self.on_augment_m3u)
        self.augment_btn.Hide()

        self.panel.SetSizer(self.main_vbox)

    # --- LOGIC: UI REFRESH & STATE ---
    def refresh_ui(self):
        auth = bool(self.has_auth())
        self.prof_box.Show(auth)
        self.lists_sizer.ShowItems(auth)
        if hasattr(self, 'preview_btn'):
            self.preview_btn.Show(auth)

        # Action buttons are menu-driven and hidden

        # Update title based on auth status
        if auth and self.dbx:
            # Title already set in connect_to_dropbox
            pass
        else:
            self.SetTitle("Audio Streamer Pro - Not Connected")

        # Proper sizer management to prevent overlap
        self.main_vbox.Layout()
        self.panel.Layout()
        self.panel.Fit()
        self.Fit()
        self.Refresh()

        # Focus management for accessibility
        if auth:
            self.prof_choice.SetFocus()

    def has_auth(self) -> bool:
        if self.access_token:
            return True
        return bool(self.app_key and self.app_secret and self.refresh_token)

    def connect_to_dropbox(self):
        try:
            if self.access_token:
                self.dbx = dropbox.Dropbox(oauth2_access_token=self.access_token)
            else:
                self.dbx = dropbox.Dropbox(app_key=self.app_key, app_secret=self.app_secret,
                                           oauth2_refresh_token=self.refresh_token)
            acc = self.dbx.users_get_current_account()
            self.status_title = f"Connected: {acc.name.display_name}"
            self.SetTitle(f"Audio Streamer Pro - {self.status_title}")
        except:
            self.refresh_token = None
            self.access_token = None

    def on_run_setup_wizard(self, event):
        if self.has_auth():
            dlg = wx.MessageDialog(
                self,
                "You are already connected to Dropbox.\n\nRun the Setup Wizard anyway (to replace credentials)?",
                "Already Connected",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            )
            res = dlg.ShowModal()
            dlg.Destroy()
            if res != wx.ID_YES:
                return

        ok = run_setup_wizard(self, SERVICE_NAME, dropbox)
        if ok:
            self.access_token = keyring.get_password(SERVICE_NAME, "access_token")
            self.refresh_token = keyring.get_password(SERVICE_NAME, "refresh_token")
            if self.has_auth():
                self.connect_to_dropbox()
                self.load_dropbox_explorer("")
            self.refresh_ui()

    def on_debug_connection_status(self, event):
        mode = "access_token" if self.access_token else "refresh_token" if self.refresh_token else "none"
        acc_name = ""
        err = ""
        if self.dbx:
            try:
                acc = self.dbx.users_get_current_account()
                acc_name = acc.name.display_name
            except Exception as e:
                err = str(e)

        msg = (
            f"DEBUG Connection Status\n\n"
            f"Auth mode: {mode}\n"
            f"Account: {acc_name or '(unknown)'}\n"
            f"Connected client: {'yes' if self.dbx else 'no'}\n"
            f"Last error: {err or '(none)'}\n"
        )
        wx.MessageBox(msg, "Debug: Connection Status", wx.OK | wx.ICON_INFORMATION)

    # --- LOGIC: EXPLORER & NAVIGATION ---
    def load_dropbox_explorer(self, path):
        if not self.dbx:
            return
        self.explorer.Clear()
        self.explorer_paths = []
        self.current_dropbox_path = path
        if hasattr(self, 'explorer_path_label'):
            self.explorer_path_label.SetLabel(path or "/")

        try:
            res = self.dbx.files_list_folder(path)
        except Exception as e:
            wx.MessageBox(f"Failed to list folder:\n\n{e}", "Error", wx.OK | wx.ICON_ERROR)
            return

        folders = []
        for entry in res.entries:
            if isinstance(entry, dropbox.files.FolderMetadata):
                folders.append((entry.name, entry.path_display))

        # Sort folders alphabetically (case-insensitive)
        folders.sort(key=lambda x: x[0].lower())

        for name, full_path in folders:
            self.explorer.Append(name)
            self.explorer_paths.append(full_path)

    def on_context_menu(self, event):
        menu = wx.Menu()
        add = menu.Append(wx.ID_ANY, "Add Selection to Profile")
        self.Bind(wx.EVT_MENU, self.on_add_to_profile, add)
        self.PopupMenu(menu)
        menu.Destroy()

    def on_add_to_profile(self, event):
        items = self.explorer.GetSelections()
        added_count = 0
        paths = [self.explorer_paths[i] for i in items if 0 <= i < len(self.explorer_paths)]

        # Check if in augmentation mode
        if self.loaded_m3u_file:
            # Add to augmentation list
            for p in paths:
                if p not in self.augment_folders:
                    self.augment_folders.append(p)
                    self.playlist_list.Append(p)
                    added_count += 1
            if added_count > 0:
                wx.MessageBox(f"{added_count} folder(s) added. Click 'Process & Merge' when ready.", "Added")
        else:
            # Normal profile mode
            for p in paths:
                if p not in self.profiles[self.current_profile]:
                    self.profiles[self.current_profile].append(p)
                    self.playlist_list.Append(p)
                    added_count += 1
            if added_count > 0:
                self.save_data(PROFILES_FILE, self.profiles)
                wx.MessageBox(f"{added_count} folder(s) added to profile.", "Added")

        self.playlist_list.SetFocus()

    # --- LOGIC: ASYNC SMART SYNC ENGINE ---
    def on_smart_sync(self, event):
        if not self.profiles[self.current_profile]:
            wx.MessageBox("No folders selected for this profile.", "Error")
            self.prof_choice.SetFocus()
            return

        # Create and show progress window
        progress_win = ProgressWindow(self, "Uploading to Dropbox Cloud")
        progress_win.Show()

        # Disable buttons during processing
        self.sync_btn.Enable(False)
        self.save_local_btn.Enable(False)

        # Run async processing in background thread
        def run_async_thread():
            # Create progress callback that updates window
            def progress_callback(action, *args):
                if action == 'log':
                    progress_win.log(args[0], args[1] if len(args) > 1 else 'info')
                elif action == 'set_total':
                    progress_win.set_total(args[0])
                elif action == 'update_progress':
                    progress_win.update_progress(args[0], args[1], args[2] if len(args) > 2 else "")
                elif action == 'increment_processed':
                    progress_win.increment_processed()
                elif action == 'increment_skipped':
                    progress_win.increment_skipped()

            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                # Run async processing
                m3u_lines, stats = loop.run_until_complete(
                    run_async_processing(
                        self.dbx,
                        self.profiles[self.current_profile],
                        progress_callback,
                        max_concurrent=5,
                        series_mode=self.series_mode,
                        series_logo=self.series_logo,
                        extensions=self.media_extensions
                    )
                )

                loop.close()

                # Upload M3U file
                filename = f"{self.current_profile.lower().replace(' ', '_')}.m3u"
                content = "\n".join(m3u_lines)

                progress_callback('log', f"Uploading {filename} to Dropbox...", 'info')

                try:
                    self._ensure_remote_playlist_folder_exists()
                    remote_path = self._profile_remote_m3u_name(self.current_profile)
                    self.dbx.files_upload(content.encode('utf-8'), remote_path, mode=dropbox.files.WriteMode.overwrite)
                    progress_callback('log', f"Successfully uploaded to {remote_path}", 'success')

                    # Show completion
                    wx.CallAfter(progress_win.mark_complete)
                    wx.CallAfter(
                        wx.MessageBox,
                        f"Upload Complete!\n\nProcessed: {stats['processed']}\nSkipped: {stats['skipped']}\nTotal: {stats['total']}\n\nUploaded to: {remote_path}",
                        "Cloud Sync Success"
                    )
                except Exception as e:
                    progress_callback('log', f"Upload failed: {e}", 'error')
                    wx.CallAfter(wx.MessageBox, f"Upload failed:\n\n{e}", "Upload Error")

            except Exception as e:
                error_msg = traceback.format_exc()
                progress_callback('log', f"Processing error: {e}", 'error')
                wx.CallAfter(wx.MessageBox, f"Processing failed:\n\n{error_msg}", "Error")
            finally:
                # Re-enable buttons
                wx.CallAfter(self.sync_btn.Enable, True)
                wx.CallAfter(self.save_local_btn.Enable, True)
                wx.CallAfter(self.sync_btn.SetFocus)

        # Start background thread
        thread = threading.Thread(target=run_async_thread, daemon=True)
        thread.start()

    # --- LOGIC: ASYNC SAVE PROFILE LOCALLY ---
    def on_save_local(self, event):
        if not self.profiles[self.current_profile]:
            wx.MessageBox("No folders selected for this profile.", "Error")
            self.prof_choice.SetFocus()
            return

        # Create and show progress window
        progress_win = ProgressWindow(self, "Generating M3U Playlist")
        progress_win.Show()

        # Disable buttons during processing
        self.sync_btn.Enable(False)
        self.save_local_btn.Enable(False)

        # Run async processing in background thread
        def run_async_thread():
            # Create progress callback that updates window
            def progress_callback(action, *args):
                if action == 'log':
                    progress_win.log(args[0], args[1] if len(args) > 1 else 'info')
                elif action == 'set_total':
                    progress_win.set_total(args[0])
                elif action == 'update_progress':
                    progress_win.update_progress(args[0], args[1], args[2] if len(args) > 2 else "")
                elif action == 'increment_processed':
                    progress_win.increment_processed()
                elif action == 'increment_skipped':
                    progress_win.increment_skipped()

            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                # Run async processing
                m3u_lines, stats = loop.run_until_complete(
                    run_async_processing(
                        self.dbx,
                        self.profiles[self.current_profile],
                        progress_callback,
                        max_concurrent=5,
                        series_mode=self.series_mode,
                        series_logo=self.series_logo,
                        extensions=self.media_extensions
                    )
                )

                loop.close()

                if stats['processed'] == 0:
                    progress_callback('log', "No files could be processed", 'error')
                    wx.CallAfter(wx.MessageBox, "No files could be processed. All files were skipped due to errors.", "Error")
                    wx.CallAfter(progress_win.mark_complete)
                    return

                # Save M3U file locally
                progress_callback('log', "Processing complete - ready to save", 'success')
                wx.CallAfter(progress_win.mark_complete)

                # Show file save dialog
                default_filename = f"{self.current_profile.lower().replace(' ', '_')}.m3u"

                def show_save_dialog():
                    dlg = wx.FileDialog(
                        self,
                        "Save M3U Playlist",
                        defaultDir=os.getcwd(),
                        defaultFile=default_filename,
                        wildcard="M3U Playlist (*.m3u)|*.m3u",
                        style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
                    )

                    if dlg.ShowModal() == wx.ID_OK:
                        save_path = dlg.GetPath()
                        try:
                            with open(save_path, 'w', encoding='utf-8') as f:
                                f.write("\n".join(m3u_lines))

                            summary_msg = f"Processed: {stats['processed']}\nSkipped: {stats['skipped']}\nTotal: {stats['total']}"
                            wx.MessageBox(f"Profile saved successfully!\n\n{summary_msg}\n\nLocation: {save_path}", "Saved")
                        except Exception as e:
                            wx.MessageBox(f"Failed to save file:\n{e}", "Save Error")

                    dlg.Destroy()

                wx.CallAfter(show_save_dialog)

            except Exception as e:
                error_msg = traceback.format_exc()
                progress_callback('log', f"Processing error: {e}", 'error')
                wx.CallAfter(wx.MessageBox, f"Processing failed:\n\n{error_msg}", "Error")
            finally:
                # Re-enable buttons
                wx.CallAfter(self.sync_btn.Enable, True)
                wx.CallAfter(self.save_local_btn.Enable, True)
                wx.CallAfter(self.save_local_btn.SetFocus)

        thread = threading.Thread(target=run_async_thread, daemon=True)
        thread.start()

    # --- LOGIC: ADD TO EXISTING M3U ---
    def on_augment_m3u(self, event):
        """Load existing M3U and add new folders to it"""
        import re

        # Step 1: Load existing M3U file
        dlg = wx.FileDialog(
            self,
            "Select M3U file to add folders to",
            wildcard="M3U Playlist (*.m3u)|*.m3u",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )

        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        m3u_file = dlg.GetPath()
        dlg.Destroy()

        # Parse existing M3U
        try:
            with open(m3u_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            if not lines or not lines[0].strip().startswith('#EXTM3U'):
                wx.MessageBox("Not a valid M3U file", "Error", wx.OK | wx.ICON_ERROR)
                return

            # Extract existing entries
            existing_entries = []
            existing_categories = set()
            i = 1

            while i < len(lines):
                line = lines[i].strip()
                if line.startswith('#EXTINF'):
                    # Extract category
                    match = re.search(r'group-title="([^"]+)"', line)
                    if match:
                        category = match.group(1)
                        existing_categories.add(category)

                    if i + 1 < len(lines):
                        url_line = lines[i + 1].strip()
                        existing_entries.append({
                            'extinf': line,
                            'url': url_line
                        })
                        i += 2
                    else:
                        i += 1
                else:
                    i += 1

            self.loaded_m3u_file = m3u_file
            self.loaded_m3u_entries = existing_entries

            # Show info and ask user to select folders
            info_msg = (
                f"Loaded: {os.path.basename(m3u_file)}\n"
                f"Categories: {len(existing_categories)}\n"
                f"Total files: {len(existing_entries)}\n\n"
                f"Now select folders from the Dropbox Explorer on the left.\n"
                f"Use Ctrl+Space or right-click to add folders to the list on the right.\n"
                f"Then click this button again to process and merge."
            )
            wx.MessageBox(info_msg, "M3U Loaded - Select New Folders", wx.OK | wx.ICON_INFORMATION)

            # Clear and prepare for folder selection
            self.augment_folders = []
            self.playlist_list.Clear()
            self.playlist_list.Append(f"[Existing M3U: {len(existing_entries)} files]")
            for cat in sorted(existing_categories):
                self.playlist_list.Append(cat)

            # Change button to "Process & Merge"
            self.augment_btn.SetLabel("Process & Merge New Folders")
            self.augment_btn.Unbind(wx.EVT_BUTTON)
            self.augment_btn.Bind(wx.EVT_BUTTON, self.on_process_and_merge)

        except Exception as e:
            wx.MessageBox(f"Error loading M3U file:\n{e}", "Error", wx.OK | wx.ICON_ERROR)

    def on_update_existing_m3u(self, event):
        """Update an existing M3U by rescanning the current profile folders and merging new items."""
        if not self.profiles.get(self.current_profile):
            wx.MessageBox("No folders selected for this profile.", "Error")
            self.prof_choice.SetFocus()
            return

        sort_dlg = wx.MessageDialog(
            self,
            "Do you want to re-sort items within each category (group-title) using natural sort?\n\n"
            "- Yes: new episodes/chapters will be inserted in the correct order.\n"
            "- No: preserves your existing file order and appends new items at the end.",
            "Update Options",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        sort_within_groups = sort_dlg.ShowModal() == wx.ID_YES
        sort_dlg.Destroy()

        remove_dlg = wx.MessageDialog(
            self,
            "Do you want to remove entries from the existing M3U that are no longer found in the profile scan?\n\n"
            "(Detection is based on URL-not-found.)",
            "Conflict Resolution",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        remove_missing = remove_dlg.ShowModal() == wx.ID_YES
        remove_dlg.Destroy()

        dlg = wx.FileDialog(
            self,
            "Select M3U file to update from this profile",
            wildcard="M3U Playlist (*.m3u)|*.m3u",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )

        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        m3u_file = dlg.GetPath()
        dlg.Destroy()

        # Parse existing M3U
        try:
            with open(m3u_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            if not lines or not lines[0].strip().startswith('#EXTM3U'):
                wx.MessageBox("Not a valid M3U file", "Error", wx.OK | wx.ICON_ERROR)
                return
        except Exception as e:
            wx.MessageBox(f"Error loading M3U file:\n{e}", "Error", wx.OK | wx.ICON_ERROR)
            return

        existing_entries = []
        i = 1
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('#EXTINF'):
                if i + 1 < len(lines):
                    url_line = lines[i + 1].strip()
                    if url_line:
                        existing_entries.append({'extinf': line, 'url': url_line})
                    i += 2
                else:
                    i += 1
            else:
                i += 1

        self._set_profile_update_setting(self.current_profile, {
            'last_local_m3u_path': m3u_file,
            'sort_within_groups': bool(sort_within_groups),
            'remove_missing': bool(remove_missing),
        })

        self._start_profile_update(existing_entries, m3u_file, sort_within_groups, remove_missing, save_path_override=None)

    def _start_profile_update(self, existing_entries, m3u_file, sort_within_groups, remove_missing, save_path_override):
        import re

        progress_win = ProgressWindow(self, "Updating Existing M3U")
        progress_win.Show()

        self.sync_btn.Enable(False)
        self.save_local_btn.Enable(False)
        self.augment_btn.Enable(False)

        def run_async_thread():
            def progress_callback(action, *args):
                if action == 'log':
                    progress_win.log(args[0], args[1] if len(args) > 1 else 'info')
                elif action == 'set_total':
                    progress_win.set_total(args[0])
                elif action == 'update_progress':
                    progress_win.update_progress(args[0], args[1], args[2] if len(args) > 2 else "")
                elif action == 'increment_processed':
                    progress_win.increment_processed()
                elif action == 'increment_skipped':
                    progress_win.increment_skipped()

            def natural_key(s: str):
                chunks = re.split(r'(\d+)', (s or '').lower())
                out = []
                for c in chunks:
                    out.append(int(c) if c.isdigit() else c)
                return out

            def get_group(extinf_line: str) -> str:
                m = re.search(r'group-title="([^"]+)"', extinf_line or '')
                return m.group(1) if m else ''

            def get_display_name(extinf_line: str) -> str:
                if not extinf_line:
                    return ''
                idx = extinf_line.rfind(',')
                if idx == -1:
                    return ''
                return extinf_line[idx + 1:].strip()

            def upload_to_cloud(local_path: str):
                if not self.dbx:
                    return
                try:
                    with open(local_path, 'rb') as f:
                        content_bytes = f.read()
                    self._ensure_remote_playlist_folder_exists()
                    remote_path = self._profile_remote_m3u_name(self.current_profile)
                    self.dbx.files_upload(content_bytes, remote_path, mode=dropbox.files.WriteMode.overwrite)
                except Exception as e:
                    wx.CallAfter(wx.MessageBox, f"Cloud upload failed:\n\n{e}", "Cloud Upload")

            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                progress_callback('log', f"Processing {len(self.profiles[self.current_profile])} folder(s)...", 'info')
                new_m3u_lines, _stats = loop.run_until_complete(
                    run_async_processing(
                        self.dbx,
                        self.profiles[self.current_profile],
                        progress_callback,
                        max_concurrent=5,
                        series_mode=self.series_mode,
                        series_logo=self.series_logo,
                        extensions=self.media_extensions
                    )
                )
                loop.close()

                existing_urls = {e.get('url', '').strip() for e in existing_entries if e.get('url')}

                added = 0
                skipped_dupe = 0
                new_entries = []
                for block in new_m3u_lines[1:]:
                    if not block or not str(block).strip():
                        continue
                    parts = [p.strip() for p in str(block).splitlines() if p.strip()]
                    if len(parts) < 2:
                        continue
                    extinf = parts[0]
                    url = parts[-1]
                    if not extinf.startswith('#EXTINF') or not url:
                        continue
                    if url in existing_urls:
                        skipped_dupe += 1
                        continue
                    new_entries.append({'extinf': extinf, 'url': url})
                    existing_urls.add(url)
                    added += 1

                scanned_urls = {e['url'] for e in new_entries}
                missing_urls = {e.get('url', '').strip() for e in existing_entries if e.get('url')} - scanned_urls

                group_order = []
                seen_groups = set()
                for entry in existing_entries:
                    g = get_group(entry.get('extinf', ''))
                    if g not in seen_groups:
                        group_order.append(g)
                        seen_groups.add(g)

                base_entries = existing_entries
                if remove_missing and missing_urls:
                    base_entries = [e for e in existing_entries if (e.get('url', '').strip() not in missing_urls)]

                groups = {}
                for entry in base_entries + new_entries:
                    g = get_group(entry.get('extinf', ''))
                    groups.setdefault(g, []).append(entry)

                new_groups = [g for g in groups.keys() if g not in seen_groups]
                group_order.extend(sorted(new_groups, key=natural_key))

                final_m3u = ['#EXTM3U']
                total_out = 0
                for g in group_order:
                    entries = groups.get(g, [])
                    if sort_within_groups:
                        entries.sort(key=lambda e: natural_key(get_display_name(e.get('extinf', ''))))
                    for e in entries:
                        final_m3u.append(e['extinf'])
                        final_m3u.append(e['url'])
                        total_out += 1

                wx.CallAfter(progress_win.mark_complete)

                def finalize_save(save_path: str):
                    try:
                        if save_path == m3u_file:
                            backup_path = save_path + '.bak'
                            if os.path.exists(m3u_file):
                                import shutil
                                shutil.copy2(m3u_file, backup_path)

                        with open(save_path, 'w', encoding='utf-8') as f:
                            f.write("\n".join(final_m3u))

                        upload_to_cloud(save_path)

                        self._set_profile_update_setting(self.current_profile, {
                            'last_local_m3u_path': save_path,
                            'sort_within_groups': bool(sort_within_groups),
                            'remove_missing': bool(remove_missing),
                        })

                        summary = (
                            f"Update Complete!\n\n"
                            f"Existing files: {len(existing_entries)}\n"
                            f"Added: {added}\n"
                            f"Duplicates skipped: {skipped_dupe}\n"
                            f"Missing in scan: {len(missing_urls)}\n"
                            f"Total: {total_out}\n\n"
                            f"Saved to: {save_path}"
                        )
                        wx.MessageBox(summary, "Updated", wx.OK | wx.ICON_INFORMATION)
                    except Exception as e:
                        wx.MessageBox(f"Failed to save:\n{e}", "Save Error", wx.OK | wx.ICON_ERROR)

                def show_save_dialog():
                    default_name = os.path.basename(m3u_file)
                    default_dir = os.path.dirname(m3u_file)

                    save_dlg = wx.FileDialog(
                        self,
                        "Save Updated M3U",
                        defaultDir=default_dir,
                        defaultFile=default_name,
                        wildcard="M3U Playlist (*.m3u)|*.m3u",
                        style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
                    )

                    if save_dlg.ShowModal() == wx.ID_OK:
                        finalize_save(save_dlg.GetPath())
                    save_dlg.Destroy()

                if save_path_override:
                    wx.CallAfter(finalize_save, save_path_override)
                else:
                    wx.CallAfter(show_save_dialog)

            except Exception as e:
                error_msg = traceback.format_exc()
                progress_callback('log', f"Update error: {e}", 'error')
                wx.CallAfter(wx.MessageBox, f"Update failed:\n\n{error_msg}", "Error")
            finally:
                wx.CallAfter(self.sync_btn.Enable, True)
                wx.CallAfter(self.save_local_btn.Enable, True)
                wx.CallAfter(self.augment_btn.Enable, True)
                wx.CallAfter(self.augment_btn.SetFocus)

        thread = threading.Thread(target=run_async_thread, daemon=True)
        thread.start()

    def on_process_and_merge(self, event):
        """Process new folders and merge with existing M3U"""
        if not self.augment_folders:
            wx.MessageBox("No new folders selected. Use the explorer to add folders first.", "No Folders", wx.OK | wx.ICON_WARNING)
            return

        # Create and show progress window
        progress_win = ProgressWindow(self, "Processing New Folders")
        progress_win.Show()

        # Disable buttons during processing
        self.sync_btn.Enable(False)
        self.save_local_btn.Enable(False)
        self.augment_btn.Enable(False)

        # Run async processing in background thread
        def run_async_thread():
            def progress_callback(action, *args):
                if action == 'log':
                    progress_win.log(args[0], args[1] if len(args) > 1 else 'info')
                elif action == 'set_total':
                    progress_win.set_total(args[0])
                elif action == 'update_progress':
                    progress_win.update_progress(args[0], args[1], args[2] if len(args) > 2 else "")
                elif action == 'increment_processed':
                    progress_win.increment_processed()
                elif action == 'increment_skipped':
                    progress_win.increment_skipped()

            try:
                # Process new folders
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                progress_callback('log', f"Processing {len(self.augment_folders)} new folders...", 'info')

                new_m3u_lines, stats = loop.run_until_complete(
                    run_async_processing(
                        self.dbx,
                        self.augment_folders,
                        progress_callback,
                        max_concurrent=5,
                        series_mode=self.series_mode,
                        series_logo=self.series_logo,
                        extensions=self.media_extensions
                    )
                )

                loop.close()

                # Merge with existing entries
                progress_callback('log', "Merging with existing M3U...", 'info')

                existing_urls = set()
                for entry in self.loaded_m3u_entries:
                    if isinstance(entry, dict):
                        url = (entry.get('url') or '').strip()
                        if url:
                            existing_urls.add(url)

                added = 0
                skipped_dupe = 0
                merged_entries = list(self.loaded_m3u_entries)
                for block in new_m3u_lines[1:]:
                    if not block or not str(block).strip():
                        continue

                    parts = [p.strip() for p in str(block).splitlines() if p.strip()]
                    url = parts[-1] if parts else ''
                    if url and url in existing_urls:
                        skipped_dupe += 1
                        continue

                    merged_entries.append(block)
                    if url:
                        existing_urls.add(url)
                    added += 1

                # Build final M3U
                final_m3u = ['#EXTM3U']
                for entry in merged_entries:
                    if isinstance(entry, dict):
                        final_m3u.append(entry['extinf'])
                        final_m3u.append(entry['url'])
                    else:
                        final_m3u.append(entry)

                progress_callback('log', f"Merge complete! Total: {len(merged_entries)} entries", 'success')
                wx.CallAfter(progress_win.mark_complete)

                def show_save_dialog():
                    default_name = os.path.basename(self.loaded_m3u_file)
                    default_dir = os.path.dirname(self.loaded_m3u_file)

                    save_dlg = wx.FileDialog(
                        self,
                        "Save Merged M3U",
                        defaultDir=default_dir,
                        defaultFile=default_name,
                        wildcard="M3U Playlist (*.m3u)|*.m3u",
                        style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
                    )

                    if save_dlg.ShowModal() == wx.ID_OK:
                        save_path = save_dlg.GetPath()
                        try:
                            if save_path == self.loaded_m3u_file:
                                backup_path = save_path + '.bak'
                                if os.path.exists(self.loaded_m3u_file):
                                    import shutil
                                    shutil.copy2(self.loaded_m3u_file, backup_path)

                            with open(save_path, 'w', encoding='utf-8') as f:
                                f.write("\n".join(final_m3u))

                            summary = (
                                f"Merge Complete!\n\n"
                                f"Existing files: {len(self.loaded_m3u_entries)}\n"
                                f"Added: {added}\n"
                                f"Duplicates skipped: {skipped_dupe}\n"
                                f"Total: {len(merged_entries)}\n\n"
                                f"Saved to: {save_path}"
                            )
                            wx.MessageBox(summary, "Success", wx.OK | wx.ICON_INFORMATION)
                        except Exception as e:
                            wx.MessageBox(f"Failed to save:\n{e}", "Save Error", wx.OK | wx.ICON_ERROR)

                    save_dlg.Destroy()

                    # Reset augmentation state
                    self.loaded_m3u_file = None
                    self.loaded_m3u_entries = []
                    self.augment_folders = []
                    self.playlist_list.SetItems(self.profiles[self.current_profile])
                    self.augment_btn.SetLabel("Add to Existing M3U")
                    self.augment_btn.Unbind(wx.EVT_BUTTON)
                    self.augment_btn.Bind(wx.EVT_BUTTON, self.on_augment_m3u)

                wx.CallAfter(show_save_dialog)

            except Exception as e:
                error_msg = traceback.format_exc()
                progress_callback('log', f"Processing error: {e}", 'error')
                wx.CallAfter(wx.MessageBox, f"Processing failed:\n\n{error_msg}", "Error")
            finally:
                wx.CallAfter(self.sync_btn.Enable, True)
                wx.CallAfter(self.save_local_btn.Enable, True)
                wx.CallAfter(self.augment_btn.Enable, True)
                wx.CallAfter(self.augment_btn.SetFocus)

        thread = threading.Thread(target=run_async_thread, daemon=True)
        thread.start()

    # --- SERIES MODE TOGGLE ---
    def on_series_toggle(self, event):
        """Handle Series/VOD Mode checkbox toggle"""
        if hasattr(self, 'series_checkbox'):
            self.series_mode = self.series_checkbox.GetValue()
        mode_text = "enabled" if self.series_mode else "disabled"
        wx.MessageBox(
            f"Series/VOD Mode {mode_text}.\n\n"
            f"When enabled, files will be formatted as:\n"
            f"• Episode naming: S01 E01, S01 E02, etc.\n"
            f"• Enhanced metadata: tvg-id, tvg-name, tvg-logo\n"
            f"• Optimized for IPTV VOD/Series libraries",
            "Series Mode",
            wx.OK | wx.ICON_INFORMATION
        )

    def on_logo_url_change(self, event):
        """Handle logo URL text change"""
        if hasattr(self, 'series_logo_input'):
            self.series_logo = self.series_logo_input.GetValue()
        # Save to preferences
        self.save_data(SERIES_LOGO_FILE, {'url': self.series_logo})

    # --- SETTINGS DIALOG ---
    def on_open_settings(self, event):
        """Open the Settings dialog for account management"""
        dlg = SettingsDialog(self, self.app_key, self.app_secret, self.refresh_token, self.series_mode, self.series_logo, self.media_extensions)
        if dlg.ShowModal() == wx.ID_OK:
            # User saved new credentials or logged in
            self.app_key = dlg.app_key
            self.app_secret = dlg.app_secret
            self.refresh_token = dlg.refresh_token

            series_mode, series_logo, media_extensions = dlg.get_playlist_values()
            self.series_mode = series_mode
            self.series_logo = series_logo
            self.save_data(SERIES_LOGO_FILE, {'url': self.series_logo})

            self.media_extensions = media_extensions if media_extensions else list(DEFAULT_MEDIA_EXTENSIONS)
            if not self.media_extensions:
                self.media_extensions = list(DEFAULT_MEDIA_EXTENSIONS)
            self.save_data(MEDIA_EXTENSIONS_FILE, {'extensions': self.media_extensions})

            # Reconnect if authenticated
            if self.has_auth():
                self.connect_to_dropbox()
                self.load_dropbox_explorer("")

            self.refresh_ui()
        dlg.Destroy()

    # --- UTILITIES: DATA & AUTH ---
    def on_copy_link(self, event):
        fname = self._profile_remote_m3u_name(self.current_profile)
        try:
            shared = get_or_create_shared_link(self.dbx, fname, direct_only=True)
            stream_url = to_direct_stream_url(shared.url)
            
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(stream_url))
                wx.TheClipboard.Close()
                wx.MessageBox(f"Direct M3U stream link copied!\n\nURL: {stream_url}", "Playlist Link Copied")
            self.sync_btn.SetFocus()
        except Exception as e: 
            wx.MessageBox(f"Please generate the M3U file first.\n\nError: {e}", "File Not Found")
            self.sync_btn.SetFocus()

    def load_data(self, f, default):
        if os.path.exists(f):
            with open(f, 'r', encoding='utf-8') as file: return json.load(file)
        return default

    def save_data(self, f, data):
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, 'w', encoding='utf-8') as file: json.dump(data, file)

    def _profile_remote_m3u_name(self, profile_name: str) -> str:
        safe = (profile_name or "").strip().lower().replace(' ', '_')
        if not safe:
            safe = "default"
        return f"{REMOTE_PLAYLIST_FOLDER}/{safe}.m3u"

    def _ensure_remote_playlist_folder_exists(self):
        if not self.dbx:
            return
        try:
            self.dbx.files_create_folder_v2(REMOTE_PLAYLIST_FOLDER)
        except Exception as e:
            # Ignore "already exists" conflicts.
            try:
                if hasattr(e, 'error') and hasattr(e.error, 'is_path') and e.error.is_path():
                    pe = e.error.get_path()
                    if pe and hasattr(pe, 'is_conflict') and pe.is_conflict():
                        return
            except Exception:
                pass
            raise

    def _get_profile_update_setting(self, profile_name: str) -> dict:
        return dict(self.profile_update_settings.get(profile_name, {}))

    def _set_profile_update_setting(self, profile_name: str, updates: dict):
        current = dict(self.profile_update_settings.get(profile_name, {}))
        current.update(updates or {})
        self.profile_update_settings[profile_name] = current
        self.save_data(PROFILE_UPDATE_SETTINGS_FILE, self.profile_update_settings)

    def on_quick_update(self, event):
        if not self.profiles.get(self.current_profile):
            wx.MessageBox("No folders selected for this profile.", "Error")
            self.prof_choice.SetFocus()
            return

        settings = self._get_profile_update_setting(self.current_profile)
        m3u_file = (settings.get('last_local_m3u_path') or '').strip()
        if not m3u_file or not os.path.exists(m3u_file):
            wx.MessageBox(
                "No previous local M3U path saved for this profile.\n\nRun 'Update Existing M3U (from Profile)…' once to select a file.",
                "1-Click Update",
                wx.OK | wx.ICON_INFORMATION,
            )
            return

        sort_within_groups = bool(settings.get('sort_within_groups', False))
        remove_missing = bool(settings.get('remove_missing', False))

        # Parse existing M3U into entries
        try:
            with open(m3u_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            if not lines or not lines[0].strip().startswith('#EXTM3U'):
                wx.MessageBox("Not a valid M3U file", "Error", wx.OK | wx.ICON_ERROR)
                return
        except Exception as e:
            wx.MessageBox(f"Error loading M3U file:\n{e}", "Error", wx.OK | wx.ICON_ERROR)
            return

        existing_entries = []
        i = 1
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('#EXTINF'):
                if i + 1 < len(lines):
                    url_line = lines[i + 1].strip()
                    if url_line:
                        existing_entries.append({'extinf': line, 'url': url_line})
                    i += 2
                else:
                    i += 1
            else:
                i += 1

        # Overwrite in place (with backup) and upload to cloud.
        self._start_profile_update(existing_entries, m3u_file, sort_within_groups, remove_missing, save_path_override=m3u_file)

    def on_preview_existing_m3u(self, event):
        dlg = wx.FileDialog(
            self,
            "Select M3U file to preview",
            wildcard="M3U Playlist (*.m3u)|*.m3u",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )

        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        m3u_file = dlg.GetPath()
        dlg.Destroy()

        try:
            with open(m3u_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            wx.MessageBox(f"Failed to read file:\n{e}", "Preview", wx.OK | wx.ICON_ERROR)
            return

        if not lines or not lines[0].strip().startswith('#EXTM3U'):
            wx.MessageBox("Not a valid M3U file", "Preview", wx.OK | wx.ICON_ERROR)
            return

        import re
        counts = {}
        total = 0
        for line in lines:
            s = line.strip()
            if not s.startswith('#EXTINF'):
                continue
            total += 1
            m = re.search(r'group-title="([^"]+)"', s)
            g = m.group(1) if m else ''
            counts[g] = counts.get(g, 0) + 1

        rows = sorted(counts.items(), key=lambda kv: (-kv[1], (kv[0] or '').lower()))
        text = f"File: {os.path.basename(m3u_file)}\nTotal entries: {total}\nCategories: {len(counts)}\n\n"
        for name, c in rows:
            label = name if name else "(no group-title)"
            text += f"{label}: {c}\n"

        try:
            from wx.lib.dialogs import ScrolledMessageDialog
            dlg2 = ScrolledMessageDialog(self, text, "M3U Preview")
            dlg2.ShowModal()
            dlg2.Destroy()
        except Exception:
            wx.MessageBox(text, "M3U Preview", wx.OK | wx.ICON_INFORMATION)

    # Standard handlers
    def on_switch_profile(self, e):
        self.current_profile = self.prof_choice.GetStringSelection()
        self.playlist_list.SetItems(self.profiles[self.current_profile])
        self.playlist_list.SetFocus()
    def on_new_profile(self, e):
        dlg = wx.TextEntryDialog(self, "Enter name for new profile:", "New Profile")
        if dlg.ShowModal() == wx.ID_OK:
            n = dlg.GetValue().strip()
            if n:
                if n in self.profiles:
                    wx.MessageBox(f"Profile '{n}' already exists.", "Duplicate Name")
                else:
                    self.profiles[n] = []
                    self.prof_choice.Append(n)
                    self.prof_choice.SetStringSelection(n)
                    self.current_profile = n
                    self.playlist_list.SetItems([])
                    self.save_data(PROFILES_FILE, self.profiles)
                    wx.MessageBox(f"Profile '{n}' created.", "Success")
        dlg.Destroy()
        self.prof_choice.SetFocus()
    def on_rename_profile(self, e):
        old_name = self.prof_choice.GetStringSelection()
        if not old_name:
            wx.MessageBox("Please select a profile to rename.", "No Selection")
            self.prof_choice.SetFocus()
            return
        if old_name == "Default":
            wx.MessageBox("Cannot rename the Default profile.", "Protected Profile")
            self.prof_choice.SetFocus()
            return
        
        dlg = wx.TextEntryDialog(self, f"Enter new name for '{old_name}':", "Rename Profile", old_name)
        if dlg.ShowModal() == wx.ID_OK:
            new_name = dlg.GetValue().strip()
            if new_name and new_name != old_name:
                if new_name in self.profiles:
                    wx.MessageBox(f"Profile '{new_name}' already exists.", "Duplicate Name")
                else:
                    # Transfer data
                    self.profiles[new_name] = self.profiles[old_name]
                    del self.profiles[old_name]
                    
                    # Transfer manifest if exists
                    if old_name in self.manifest:
                        self.manifest[new_name] = self.manifest[old_name]
                        del self.manifest[old_name]
                        self.save_data(MANIFEST_FILE, self.manifest)
                    
                    # Update UI
                    self.prof_choice.SetItems(list(self.profiles.keys()))
                    self.prof_choice.SetStringSelection(new_name)
                    self.current_profile = new_name
                    self.playlist_list.SetItems(self.profiles[self.current_profile])
                    self.save_data(PROFILES_FILE, self.profiles)
                    wx.MessageBox(f"Profile renamed to '{new_name}'.", "Success")
        dlg.Destroy()
        self.prof_choice.SetFocus()
    def on_delete_profile(self, e):
        n = self.prof_choice.GetStringSelection()
        if not n:
            wx.MessageBox("Please select a profile to delete.", "No Selection")
            self.prof_choice.SetFocus()
            return
        if n == "Default":
            wx.MessageBox("Cannot delete the Default profile.", "Protected Profile")
            self.prof_choice.SetFocus()
            return
        
        confirm = wx.MessageDialog(
            self,
            f"Delete profile '{n}' and its manifest data?\nThis cannot be undone.",
            "Confirm Delete",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        )
        res = confirm.ShowModal()
        if res == wx.ID_YES:
            # Delete profile data
            del self.profiles[n]
            
            # Delete manifest data if exists
            if n in self.manifest:
                del self.manifest[n]
                self.save_data(MANIFEST_FILE, self.manifest)
            
            # Update UI
            self.prof_choice.SetItems(list(self.profiles.keys()))
            self.prof_choice.SetSelection(0)
            self.current_profile = self.prof_choice.GetStringSelection()
            self.playlist_list.SetItems(self.profiles[self.current_profile])
            self.save_data(PROFILES_FILE, self.profiles)
            wx.MessageBox(f"Profile '{n}' deleted.", "Deleted")
        confirm.Destroy()
        self.prof_choice.SetFocus()
    def on_remove_folder(self, e):
        i = self.playlist_list.GetSelection()
        if i != -1:
            folder_name = self.playlist_list.GetString(i)
            self.profiles[self.current_profile].pop(i)
            self.playlist_list.Delete(i)
            self.save_data(PROFILES_FILE, self.profiles)
            wx.MessageBox(f"Removed '{folder_name}' from profile.", "Removed")
            if self.playlist_list.GetCount() > 0:
                self.playlist_list.SetSelection(min(i, self.playlist_list.GetCount() - 1))
        self.playlist_list.SetFocus()

    def on_preview_profile_folder(self, event):
        if not self.dbx:
            wx.MessageBox(
                "Not connected to Dropbox. Open Settings and connect first.",
                "Not Connected",
                wx.OK | wx.ICON_WARNING,
            )
            return

        i = self.playlist_list.GetSelection()
        if i == wx.NOT_FOUND:
            wx.MessageBox(
                "Select a folder from the profile list first.",
                "No Selection",
                wx.OK | wx.ICON_INFORMATION,
            )
            self.playlist_list.SetFocus()
            return

        path = self.playlist_list.GetString(i)
        if not path or path.startswith('['):
            wx.MessageBox(
                "Please select a real folder path (not the header line).",
                "Invalid Selection",
                wx.OK | wx.ICON_INFORMATION,
            )
            self.playlist_list.SetFocus()
            return

        dlg = FolderPreviewDialog(self, self.dbx, path)
        dlg.ShowModal()
        dlg.Destroy()
        self.playlist_list.SetFocus()
    
    def on_go_back(self, event): 
        self.load_dropbox_explorer(os.path.dirname(self.current_dropbox_path))
        self.explorer.SetFocus()
    
    def on_enter_folder(self, event):
        """Navigate into selected folder"""
        # For multi-select listbox, check selections first
        selections = self.explorer.GetSelections()
        
        if selections:
            # Use first selected item
            folder_path = self.explorer_paths[selections[0]] if selections[0] < len(self.explorer_paths) else ""
            if folder_path:  # Make sure it's not empty
                self.load_dropbox_explorer(folder_path)
                self.explorer.SetFocus()
        else:
            # No explicit selection - ListBox might have focus on an item without selection
            # Try GetSelection() which returns the focused item in single-select mode
            # For extended selection, it returns the first selected or wx.NOT_FOUND
            focus_idx = self.explorer.GetSelection()
            if focus_idx != wx.NOT_FOUND:
                folder_path = self.explorer_paths[focus_idx] if focus_idx < len(self.explorer_paths) else ""
                if folder_path:
                    self.load_dropbox_explorer(folder_path)
                    self.explorer.SetFocus()
    
    def on_explorer_dclick(self, e):
        # Double-click should navigate into the clicked folder
        selections = self.explorer.GetSelections()
        if selections:
            folder_path = self.explorer_paths[selections[0]] if selections[0] < len(self.explorer_paths) else ""
            self.load_dropbox_explorer(folder_path)
            self.explorer.SetFocus()
    
    def on_char_hook(self, e):
        """Handle keyboard shortcuts at frame level before controls process them"""
        keycode = e.GetKeyCode()
        
        # Only handle if explorer has focus
        if self.explorer.HasFocus():
            if keycode == wx.WXK_RETURN or keycode == wx.WXK_NUMPAD_ENTER:
                # Enter key navigates into selected folder
                self.on_enter_folder(e)
                return  # Don't skip - we handled it
            elif keycode == wx.WXK_BACK:
                # Backspace goes up one level
                self.on_go_back(e)
                return  # Don't skip - we handled it
            elif keycode == wx.WXK_SPACE and e.ControlDown():
                # Ctrl+Space toggles selection on focused item
                focus_idx = self.explorer.GetSelection()
                if focus_idx != wx.NOT_FOUND:
                    # Check if item is already selected
                    if self.explorer.IsSelected(focus_idx):
                        # Deselect it
                        self.explorer.Deselect(focus_idx)
                    else:
                        # Select it
                        self.explorer.SetSelection(focus_idx, select=True)
                return  # Don't skip - we handled it
        
        # Let other events pass through
        e.Skip()
    
    def on_reset(self, e):
        for k in ["app_key", "app_secret", "refresh_token", "access_token"]:
            try:
                keyring.delete_password(SERVICE_NAME, k)
            except Exception:
                pass
        self.Close()

if __name__ == '__main__':
    app = wx.App()
    SmartStreamer(None, title="Audio Streamer Pro").Show()
    app.MainLoop()  