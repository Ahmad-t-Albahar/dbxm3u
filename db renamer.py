import os
import wx
import dropbox
import threading
import time
import keyring
import webbrowser
from dropbox import DropboxOAuth2FlowNoRedirect

# =========================
# Security / Token Handling
# =========================
SERVICE_ID = "DropboxRenamer"
USER_ID = "dropbox_token"
APP_KEY_ID = "dropbox_app_key"


def save_token(token: str):
    """Securely save token to system keyring."""
    try:
        keyring.set_password(SERVICE_ID, USER_ID, token)
        return True
    except Exception as e:
        print(f"Keyring error: {e}")
        return False


def load_token():
    """Retrieve token from system keyring."""
    try:
        return keyring.get_password(SERVICE_ID, USER_ID)
    except Exception:
        return None


def delete_token():
    """Remove token from system keyring."""
    try:
        keyring.delete_password(SERVICE_ID, USER_ID)
    except Exception:
        pass


def save_app_key(app_key: str):
    """Securely save App Key to system keyring."""
    try:
        keyring.set_password(SERVICE_ID, APP_KEY_ID, app_key)
    except Exception:
        pass


def load_app_key():
    """Retrieve App Key from system keyring."""
    try:
        return keyring.get_password(SERVICE_ID, APP_KEY_ID)
    except Exception:
        return None


def get_access_token_noninteractive():
    """Return token from env or keyring; no GUI here."""
    token = os.getenv("DROPBOX_ACCESS_TOKEN")
    if token:
        return token
    token = load_token()
    return token


# =========================
# Dropbox API Helpers
# =========================
def list_folder(dbx: dropbox.Dropbox, path: str = "", recursive: bool = False, log_func=None):
    """
    List immediate children at `path` ('' = root). Includes paging.
    """
    try:
        if log_func:
            log_func(f"API call: list_folder path='{path or '/'}' recursive={recursive}")
        result = dbx.files_list_folder(path, recursive=recursive)
        entries = result.entries
        while result.has_more:
            if log_func:
                log_func("API call: files/list_folder/continue")
            result = dbx.files_list_folder_continue(result.cursor)
            entries.extend(result.entries)
        if log_func:
            log_func(f"✅ Listed '{path or '/'}' ({len(entries)} items)")
        return entries
    except ApiError as e:
        if log_func:
            log_func(f"❌ API error listing '{path or '/'}': {e}")
        return []
    except Exception as e:
        if log_func:
            log_func(f"❌ Unexpected error: {e}")
        return []


def get_metadata(dbx: dropbox.Dropbox, path: str, log_func=None):
    try:
        if log_func:
            log_func(f"API call: files/get_metadata path='{path or '/'}'")
        return dbx.files_get_metadata(path)
    except ApiError as e:
        if log_func:
            log_func(f"❌ API error get_metadata '{path}': {e}")
        return None
    except Exception as e:
        if log_func:
            log_func(f"❌ Unexpected error get_metadata '{path}': {e}")
        return None


def move_path(dbx: dropbox.Dropbox, src: str, dst: str, log_func=None):
    try:
        if log_func:
            log_func(f"API call: files/move_v2 from='{src}' to='{dst}'")
        dbx.files_move_v2(src, dst, autorename=True)
        if log_func:
            log_func(f"✅ Moved '{src}' → '{dst}'")
        return True
    except ApiError as e:
        if log_func:
            log_func(f"❌ API error move '{src}' → '{dst}': {e}")
        return False
        return False
    except Exception as e:
        if log_func:
            log_func(f"❌ Unexpected error move '{src}' → '{dst}': {e}")
        return False


def create_folder(dbx: dropbox.Dropbox, path: str, log_func=None):
    try:
        if log_func:
            log_func(f"API call: files/create_folder_v2 path='{path}'")
        res = dbx.files_create_folder_v2(path)
        if log_func:
            log_func(f"✅ Created folder '{path}'")
        return res.metadata
    except ApiError as e:
        if log_func:
            log_func(f"❌ API error create_folder '{path}': {e}")
        return None
    except Exception as e:
        if log_func:
            log_func(f"❌ Unexpected error create_folder '{path}': {e}")
        return None


# =========================
# Dropbox Tree Picker (Explorer Style)
# =========================
class DropboxBrowser(wx.Dialog):
    """
    Explorer-style browser with Tree (Folders) + List (Files).
    """
    def __init__(self, dbx, parent, message="Browse Dropbox", log_func=None):
        super().__init__(parent=parent, title=message, size=(900, 600), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.dbx = dbx
        self.log_func = log_func
        self.selected_paths = []
        self.folder_cache = {} # path -> list of entries
        self.current_entries = [] # Entries currently in list view

        # Layout
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Top Bar (Label + Back Button)
        top_bar = wx.BoxSizer(wx.HORIZONTAL)
        top_bar.Add(wx.StaticText(self, label=message), 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        
        self.btn_back = wx.Button(self, label="<- Back")
        top_bar.Add(self.btn_back, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        self.btn_new_folder = wx.Button(self, label="New Folder")
        top_bar.Add(self.btn_new_folder, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        
        vbox.Add(top_bar, 0, wx.EXPAND)

        self.splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        
        # Left: Tree
        self.tree = wx.TreeCtrl(self.splitter, style=wx.TR_DEFAULT_STYLE | wx.TR_SINGLE)
        self.root = self.tree.AddRoot("Dropbox Home")
        self.tree.SetItemData(self.root, "")
        
        # Right: List
        self.list = wx.ListCtrl(self.splitter, style=wx.LC_REPORT | wx.LC_VRULES)
        self.list.InsertColumn(0, "Name", width=400)
        self.list.InsertColumn(1, "Type", width=100)
        self.list.InsertColumn(2, "Size", width=100)

        self.splitter.SplitVertically(self.tree, self.list, 280)
        self.splitter.SetMinimumPaneSize(150)
        
        vbox.Add(self.splitter, 1, wx.EXPAND | wx.ALL, 5)

        # Buttons
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(self, wx.ID_OK, "OK")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Cancel")
        btn_row.Add(ok_btn, 0, wx.RIGHT, 10)
        btn_row.Add(cancel_btn, 0)
        vbox.Add(btn_row, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        
        self.SetSizer(vbox)

        # Initial Populate (CallAfter to prevent blocking __init__)
        wx.CallAfter(self.first_load)

        # Bindings
        self.tree.Bind(wx.EVT_TREE_ITEM_EXPANDING, self.on_tree_expand)
        self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_tree_sel)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_list_dbl_click)
        ok_btn.Bind(wx.EVT_BUTTON, self.on_ok)
        
        self.btn_back.Bind(wx.EVT_BUTTON, self.on_back)
        self.btn_new_folder.Bind(wx.EVT_BUTTON, self.on_new_folder)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)

    def on_new_folder(self, event):
        item = self.tree.GetSelection()
        if not item.IsOk(): return
        
        path = self.tree.GetItemData(item)
        if path is None: return # Should not happen if item ok
        
        dlg = wx.TextEntryDialog(self, "Enter name for new folder:", "New Folder")
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name:
                # Construct new path
                # API expects /Root/NewName or /NewName
                new_full_path = (path + "/" + name).replace("//", "/")
                
                md = create_folder(self.dbx, new_full_path, log_func=self.log_func)
                if md:
                     wx.MessageBox("Folder created successfully!", "Success")
                     # Refresh
                     if path in self.folder_cache:
                         del self.folder_cache[path]
                     
                     self.populate_list(path)
                     
                     # Update Tree? Scanning children again is complex.
                     # We can just append the new child to current tree node if expanded?
                     # But alphabetical order...
                     # Simplest: Delete children and re-expand?
                     # Or just manually append.
                     child = self.tree.AppendItem(item, md.name)
                     self.tree.SetItemData(child, md.path_lower)
                     self.tree.SetItemHasChildren(child, True)
                     self.tree.SortChildren(item)
                else:
                     wx.MessageBox("Failed to create folder. Check logs.", "Error", wx.ICON_ERROR)
        dlg.Destroy()

    def on_key(self, event):
        # Handle Backspace
        if event.GetKeyCode() == wx.WXK_BACK:
            self.on_back(None)
        else:
            event.Skip()

    def on_back(self, event):
        # Simply move up the tree
        curr = self.tree.GetSelection()
        if curr.IsOk() and curr != self.root:
            parent = self.tree.GetItemParent(curr)
            if parent.IsOk():
                self.tree.SelectItem(parent)
                # self.tree.Collapse(curr) # Optional: collapse the folder we just left?
        else:
            # At Root or invalid
            pass

    def first_load(self):
        try:
            self.populate_tree_node(self.root, "")
            self.tree.SelectItem(self.root) # Select Root to show files
        except Exception as e:
            if self.log_func:
                self.log_func(f"Error loading root: {e}")
            wx.MessageBox(f"Error loading Dropbox: {e}", "Error", wx.ICON_ERROR)

    def get_entries(self, path):
        if path in self.folder_cache:
            return self.folder_cache[path]
        
        # Fetch
        entries = list_folder(self.dbx, path, log_func=self.log_func)
        
        # Sort Folders > Files, Alphabetical
        folders = sorted([e for e in entries if isinstance(e, dropbox.files.FolderMetadata)], key=lambda x: x.name.lower())
        files = sorted([e for e in entries if isinstance(e, dropbox.files.FileMetadata)], key=lambda x: x.name.lower())
        
        final = folders + files
        self.folder_cache[path] = final
        return final

    def populate_tree_node(self, node, path):
        # Add FOLDERS only to tree
        entries = self.get_entries(path)
        for e in entries:
            if isinstance(e, dropbox.files.FolderMetadata):
                child = self.tree.AppendItem(node, e.name)
                self.tree.SetItemData(child, e.path_lower)
                # Dummy child to enable expand icon if we haven't checked children?
                # Actually we have the entries now. 
                # If we want lazy-load for grandchildren, we should peek?
                # For simplicity, we assume folders MIGHT have children -> SetItemHasChildren = True
                # Or we can check explicitly but that requires recursion or another call.
                self.tree.SetItemHasChildren(child, True)

    def on_tree_expand(self, event):
        item = event.GetItem()
        path = self.tree.GetItemData(item)
        if path is None: return
        
        # If not already populated (no children but has button), populate
        # Note: GetChildrenCount might return 0 if empty folder.
        # But we check if we already added real items.
        # Simplest: Check if first child is valid or check a flag.
        # We'll rely on: if has children nodes, don't repopulate.
        if self.tree.GetChildrenCount(item) == 0:
            self.populate_tree_node(item, path)

    def on_tree_sel(self, event):
        item = event.GetItem()
        path = self.tree.GetItemData(item)
        if path is not None:
            self.populate_list(path)

    def populate_list(self, path):
        self.list.DeleteAllItems()
        self.current_entries = self.get_entries(path)
        
        self.current_path = path

        for i, e in enumerate(self.current_entries):
            kind = "Folder" if isinstance(e, dropbox.files.FolderMetadata) else "File"
            size_str = ""
            if isinstance(e, dropbox.files.FileMetadata):
                 size_str = f"{e.size // 1024} KB"
            
            idx = self.list.InsertItem(i, e.name)
            self.list.SetItem(idx, 1, kind)
            self.list.SetItem(idx, 2, size_str)
            
            # Simple icon logic (optional, requires ImageList, skipping for now)

    def on_list_dbl_click(self, event):
        idx = event.GetIndex()
        entry = self.current_entries[idx]
        if isinstance(entry, dropbox.files.FolderMetadata):
            # Navigate into folder
            self.navigate_to_folder(entry.path_lower)

    def navigate_to_folder(self, target_path):
        # We need to find the node in the tree corresponding to this path
        # 1. Ensure parent is expanded
        # 2. Select child
        # This is tricky because we might need to lazy-load nodes down the chain.
        # For now, we only support navigating into immediate children easily if current tree node is parent.
        
        current_tree_item = self.tree.GetSelection()
        if not current_tree_item.IsOk(): 
             current_tree_item = self.root
             
        # Check if the target is a child of current
        # Iterate children
        cookie = 0
        child, cookie = self.tree.GetFirstChild(current_tree_item)
        found = False
        while child.IsOk():
            p = self.tree.GetItemData(child)
            if p == target_path:
                self.tree.SelectItem(child)
                self.tree.Expand(child)
                found = True
                break
            child, cookie = self.tree.GetNextChild(current_tree_item, cookie)
            
        if not found:
            # Maybe we are jumping around? For now just reload list?
            # But the Tree Selection indicates "Current Folder".
            # If we just update List, Tree is out of sync.
            # Force expand current to ensure children exist
            self.populate_tree_node(current_tree_item, self.tree.GetItemData(current_tree_item))
            # Retry
            child, cookie = self.tree.GetFirstChild(current_tree_item)
            while child.IsOk():
                p = self.tree.GetItemData(child)
                if p == target_path:
                    self.tree.SelectItem(child)
                    self.tree.Expand(child)
                    return
                child, cookie = self.tree.GetNextChild(current_tree_item, cookie)

    def on_ok(self, event):
        selected_indices = []
        item = self.list.GetFirstSelected()
        while item != -1:
            selected_indices.append(item)
            item = self.list.GetNextSelected(item)
            
        self.selected_paths = []
        if selected_indices:
             for idx in selected_indices:
                 self.selected_paths.append(self.current_entries[idx].path_lower)
        else:
             # Nothing selected in list -> Use current folder (Tree Selection)
             if self.current_path is not None:
                 self.selected_paths.append(self.current_path)
             else:
                 self.selected_paths.append("") # Root

        self.EndModal(wx.ID_OK)



# =========================
# Login & Auth (GUI)
# =========================
        self.EndModal(wx.ID_OK)


class PreviewDialog(wx.Dialog):
    def __init__(self, parent, proposed_changes):
        """
        proposed_changes: List of (old_name, new_name, src_path, dst_path)
        """
        super().__init__(parent, title="Preview Renames", size=(600, 400))
        self.proposed = proposed_changes

        vbox = wx.BoxSizer(wx.VERTICAL)
        
        lbl = wx.StaticText(self, label=f"Found {len(proposed_changes)} files to rename. Please review:")
        vbox.Add(lbl, 0, wx.ALL, 10)

        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_VRULES | wx.LC_HRULES)
        self.list.InsertColumn(0, "Old Name", width=250)
        self.list.InsertColumn(1, "New Name", width=250)
        
        self.populate()
        vbox.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_ok = wx.Button(self, wx.ID_OK, "Apply Changes")
        self.btn_cancel = wx.Button(self, wx.ID_CANCEL, "Cancel")
        
        btn_row.Add(self.btn_ok, 0, wx.RIGHT, 10)
        btn_row.Add(self.btn_cancel, 0)
        vbox.Add(btn_row, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        self.SetSizer(vbox)
        
    def populate(self):
        self.list.DeleteAllItems()
        for i, (old, new, _, _) in enumerate(self.proposed):
            idx = self.list.InsertItem(i, old)
            self.list.SetItem(idx, 1, new)


# =========================
# Login & Auth (GUI)
# =========================
class LoginDialog(wx.Dialog):
    def __init__(self, parent=None):
        super().__init__(parent, title="Dropbox Login", size=(400, 350))
        self.auth_flow = None
        self.refresh_token = None

        vbox = wx.BoxSizer(wx.VERTICAL)

        # Instruction
        lbl = wx.StaticText(self, label="1. Enter your Dropbox App Key:")
        vbox.Add(lbl, 0, wx.ALL, 5)

        # App Key Input
        self.key_input = wx.TextCtrl(self, value=load_app_key() or "")
        vbox.Add(self.key_input, 0, wx.EXPAND | wx.ALL, 5)

        # Start Button
        self.btn_start = wx.Button(self, label="2. Launch Browser Login")
        vbox.Add(self.btn_start, 0, wx.ALL, 5)

        # Code Input
        vbox.Add(wx.StaticText(self, label="3. Paste the code from browser:"), 0, wx.LEFT | wx.TOP, 10)
        self.code_input = wx.TextCtrl(self)
        self.code_input.Disable()
        vbox.Add(self.code_input, 0, wx.EXPAND | wx.ALL, 5)

        # Buttons
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_ok = wx.Button(self, label="Login")
        self.btn_ok.Disable()
        btn_cancel = wx.Button(self, label="Cancel")
        
        btn_box.Add(self.btn_ok, 0, wx.RIGHT, 10)
        btn_box.Add(btn_cancel, 0)
        vbox.Add(btn_box, 0, wx.ALIGN_CENTER | wx.ALL, 15)

        self.SetSizer(vbox)

        # Events
        self.btn_start.Bind(wx.EVT_BUTTON, self.on_start)
        self.btn_ok.Bind(wx.EVT_BUTTON, self.on_ok)
        btn_cancel.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))

    def on_start(self, event):
        app_key = self.key_input.GetValue().strip()
        if not app_key:
            wx.MessageBox("Please enter an App Key first.", "Error", wx.ICON_ERROR)
            return
        
        # Save key for future
        save_app_key(app_key)

        try:
            self.auth_flow = DropboxOAuth2FlowNoRedirect(
                app_key,
                use_pkce=True,
                token_access_type='offline'
            )
            authorize_url = self.auth_flow.start()
            webbrowser.open(authorize_url)
            
            self.code_input.Enable()
            self.btn_ok.Enable()
            self.code_input.SetFocus()
        except Exception as e:
            wx.MessageBox(f"Error initializing auth flow: {e}", "Error", wx.ICON_ERROR)

    def on_ok(self, event):
        code = self.code_input.GetValue().strip()
        if not code:
            wx.MessageBox("Please enter the authorization code.", "Error", wx.ICON_ERROR)
            return

        try:
            res = self.auth_flow.finish(code)
            self.refresh_token = res.refresh_token
            if not self.refresh_token:
                # Fallback if no refresh token (shouldn't happen with offline access)
                wx.MessageBox("Warning: No refresh token received. Session will expire.", "Warning", wx.ICON_WARNING)
                self.refresh_token = res.access_token
            self.EndModal(wx.ID_OK)
        except Exception as e:
            wx.MessageBox(f"Login failed: {e}", "Error", wx.ICON_ERROR)


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, dbx_ref):
        super().__init__(parent, title="Settings", size=(350, 200))
        self.dbx_ref = dbx_ref
        self.parent = parent

        vbox = wx.BoxSizer(wx.VERTICAL)
        status = "✅ Token is saved" if load_token() else "❌ No token saved"
        vbox.Add(wx.StaticText(self, label=f"Current Token: {status}"), 0, wx.ALL, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        reauth_btn = wx.Button(self, label="Re-authenticate / Change Account")
        logout_btn = wx.Button(self, label="Log Out")
        close_btn = wx.Button(self, label="Close")
        
        row.Add(reauth_btn, 0, wx.RIGHT, 6)
        row.Add(logout_btn, 0, wx.RIGHT, 6)
        row.Add(close_btn, 0)
        vbox.Add(row, 0, wx.ALIGN_CENTER | wx.ALL, 15)

        self.SetSizer(vbox)

        reauth_btn.Bind(wx.EVT_BUTTON, self.on_reauth)
        logout_btn.Bind(wx.EVT_BUTTON, self.on_logout)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))

    def on_reauth(self, event):
        dlg = LoginDialog(self)
        if dlg.ShowModal() == wx.ID_OK and dlg.refresh_token:
            save_token(dlg.refresh_token)
            # Update live instance
            try:
                # We need app_key for refresh logic
                ak = load_app_key()
                self.dbx_ref[0] = dropbox.Dropbox(app_key=ak, oauth2_refresh_token=dlg.refresh_token)
                self.dbx_ref[0].users_get_current_account()
                wx.MessageBox("✅ Re-authenticated!", "Success", wx.ICON_INFORMATION)
                self.EndModal(wx.ID_OK)
            except Exception as e:
                wx.MessageBox(f"Error connecting: {e}", "Error", wx.ICON_ERROR)
        dlg.Destroy()

    def on_logout(self, event):
        delete_token()
        wx.MessageBox("✅ Token deleted. Restart required.", "Info", wx.ICON_INFORMATION)
        self.EndModal(wx.ID_OK)


# =========================
# Main Application (GUI)
# =========================
class DropboxApp(wx.Frame):
    def __init__(self, dbx):
        super().__init__(parent=None, title="Dropbox File Manager", size=(980, 740))
        self.dbx = dbx

        # Thread control
        self.cancel_flag = False
        self.pause_flag = False
        self.start_time = None
        self.total_files = 0
        self.files_done = 0

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Path & Browse
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(panel, label="Path(s):"), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 8)
        self.path_input = wx.TextCtrl(panel, value="")
        row.Add(self.path_input, 1, wx.RIGHT, 8)
        self.btn_browse = wx.Button(panel, label="Browse Dropbox")
        row.Add(self.btn_browse, 0)
        vbox.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        # Action buttons (Clean Layout)
        actions_sizer = wx.BoxSizer(wx.VERTICAL)
        
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_list = wx.Button(panel, label="List Files")
        self.btn_renamer = wx.Button(panel, label="Renamer Tool")
        self.btn_move = wx.Button(panel, label="Move Manager")
        
        btn_row.Add(self.btn_list, 0, wx.RIGHT, 10)
        btn_row.Add(self.btn_renamer, 0, wx.RIGHT, 10)
        btn_row.Add(self.btn_move, 0)
        actions_sizer.Add(btn_row, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        vbox.Add(actions_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        # Main log
        self.log = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        vbox.Add(self.log, 1, wx.EXPAND | wx.ALL, 10)

        # Progress + controls
        ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        self.progress = wx.Gauge(panel, range=100, style=wx.GA_HORIZONTAL)
        self.btn_pause = wx.Button(panel, label="Pause")
        self.btn_cancel = wx.Button(panel, label="Cancel")
        ctrl_row.Add(self.progress, 1, wx.RIGHT, 8)
        ctrl_row.Add(self.btn_pause, 0, wx.RIGHT, 6)
        ctrl_row.Add(self.btn_cancel, 0)
        vbox.Add(ctrl_row, 0, wx.EXPAND | wx.ALL, 10)

        self.eta_label = wx.StaticText(panel, label="ETA: --")
        vbox.Add(self.eta_label, 0, wx.ALIGN_CENTER | wx.ALL, 4)

        # API log
        vbox.Add(wx.StaticText(panel, label="API Log:"), 0, wx.LEFT | wx.TOP, 5)
        self.api_log = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        vbox.Add(self.api_log, 1, wx.EXPAND | wx.ALL, 10)

        panel.SetSizer(vbox)

        # Status Bar
        self.CreateStatusBar()
        self.SetStatusText("Ready")

        # Menu
        menubar = wx.MenuBar()
        
        # File Menu
        file_menu = wx.Menu()
        exit_item = file_menu.Append(wx.ID_EXIT, "Exit")
        menubar.Append(file_menu, "&File")
        
        # Options Menu
        settings_menu = wx.Menu()
        settings_item = settings_menu.Append(wx.ID_ANY, "Settings")
        menubar.Append(settings_menu, "&Options")
        
        self.SetMenuBar(menubar)
        self.Bind(wx.EVT_MENU, self.on_settings, settings_item)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), exit_item)

        # Events
        self.btn_browse.Bind(wx.EVT_BUTTON, self.on_browse)
        self.btn_list.Bind(wx.EVT_BUTTON, self.on_list)
        self.btn_renamer.Bind(wx.EVT_BUTTON, self.on_renamer_tool)
        self.btn_move.Bind(wx.EVT_BUTTON, self.on_move_manager)
        self.btn_cancel.Bind(wx.EVT_BUTTON, self.on_cancel)
        self.btn_pause.Bind(wx.EVT_BUTTON, self.on_pause)
        self.path_input.Bind(wx.EVT_TEXT, self.on_path_change)

        # Initial state
        self.set_busy_state(False)
        self.on_path_change(None) # Validate initial empty state

        self.Show()

    # ---- UI Logging helpers ----
    def log_msg(self, msg: str):
        wx.CallAfter(self.log.AppendText, msg + "\n")

    def api_log_msg(self, msg: str):
        wx.CallAfter(self.api_log.AppendText, msg + "\n")

    def set_progress(self, value: int):
        wx.CallAfter(self.progress.SetValue, value)

    def update_eta(self):
        if self.files_done > 0 and self.total_files > 0:
            elapsed = time.time() - self.start_time
            avg = elapsed / self.files_done
            remaining = max(self.total_files - self.files_done, 0)
            seconds_left = int(avg * remaining)
            mins, secs = divmod(seconds_left, 60)
            status = f"Processing... ETA: {mins}m {secs}s"
        else:
            status = "Ready"
        
        # Update Status Bar instead of label (if on main thread, else CallAfter)
        wx.CallAfter(self.SetStatusText, status)
        # Keep old label update just in case, or remove it? Let's hide/remove it from layout?
        # User asked for improvements, so I'll rely on Status Bar primarily.
        wx.CallAfter(self.eta_label.SetLabel, "") 

    def set_busy_state(self, is_busy: bool):
        """Toggle controls based on state."""
        # Active Operation: Disable inputs, Enable Pause/Cancel
        # Idle: Enable inputs (if valid), Disable Pause/Cancel
        
        self.btn_browse.Enable(not is_busy)
        self.path_input.Enable(not is_busy)
        
        # Action buttons depend on both busy state AND path validity. 
        # We'll just disable them if busy. If not busy, on_path_change determines state.
        if is_busy:
            self.btn_list.Disable()
            self.btn_renamer.Disable()
            self.btn_move.Disable()
            
            self.btn_pause.Enable()
            self.btn_cancel.Enable()
            self.SetCursor(wx.Cursor(wx.CURSOR_WAIT))
        else:
            self.on_path_change(None) # Re-evaluate validity
            
            self.btn_pause.Disable()
            self.btn_cancel.Disable()
            self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))
            self.SetStatusText("Ready")

    def on_path_change(self, event):
        """Enable action buttons only if path is not empty and not busy."""
        if not self.path_input.IsEnabled():
            return
            
        has_text = bool(self.path_input.GetValue().strip())
        self.btn_list.Enable(has_text)
        # Renamer and Move are independent tools, always enabled if not busy
        self.btn_renamer.Enable(True)
        self.btn_move.Enable(True) 

    def run_in_background(self, func, *args):
        def wrapper():
            wx.CallAfter(self.set_busy_state, True)
            try:
                func(*args)
            except Exception as e:
                self.log_msg(f"Error: {e}")
            finally:
                wx.CallAfter(self.set_busy_state, False)
        
        threading.Thread(target=wrapper, daemon=True).start()

    # ---- Control handlers ----
    def on_cancel(self, event):
        self.cancel_flag = True
        self.log_msg("⏹️ Operation cancelled.")

    def on_pause(self, event):
        self.pause_flag = not self.pause_flag
        if self.pause_flag:
            self.btn_pause.SetLabel("Resume")
            self.log_msg("⏸️ Operation paused.")
        else:
            self.btn_pause.SetLabel("Pause")
            self.log_msg("▶️ Operation resumed.")

    # ---- Actions ----
    def on_browse(self, event):
        try:
            dlg = DropboxBrowser(self.dbx, self, log_func=self.api_log_msg)
            if dlg.ShowModal() == wx.ID_OK and dlg.selected_paths:
                self.path_input.SetValue(", ".join(dlg.selected_paths))
            dlg.Destroy()
        except Exception as e:
            wx.MessageBox(f"Error opening browser: {e}", "Debug Error", wx.ICON_ERROR)
            self.log_msg(f"Error opening browser: {e}")
            import traceback
            traceback.print_exc()

    def on_list(self, event):
        paths = [p.strip() for p in self.path_input.GetValue().split(",") if p.strip() != "" or p == ""]
        if not paths: return
        
        self.set_busy_state(True)
        # Run in thread so it doesn't freeze UI
        def _do_list():
            wx.CallAfter(self.log.Clear)
            for path in paths:
                entries = list_folder(self.dbx, path, log_func=self.api_log_msg)
                self.log_msg(f"📂 {path or '/'}:")
                for e in entries:
                    kind = "Folder" if isinstance(e, dropbox.files.FolderMetadata) else "File"
                    self.log_msg(f" - [{kind}] {e.name}")
            wx.CallAfter(self.set_busy_state, False)
            
        threading.Thread(target=_do_list, daemon=True).start()

    # ---- Bulk Rename Generic ----
    def _count_targets(self, paths, recursive):
        """
        Count potential files for ETA. 
        Note: Recursive counting might be slow, so we might skip deep counting 
        or just count top level to avoid delay. For now, basic version.
        """
        # If recursive is on, counting is expensive. 
        # We'll just show indeterminant progress or skip precise total.
        if recursive:
            return 0 # 0 means indeterminate
            
        total = 0
        for p in paths:
            if p == "":
                entries = list_folder(self.dbx, "", recursive=False)
                total += len(entries)
            else:
                md = get_metadata(self.dbx, p)
                if not md: continue
                if isinstance(md, dropbox.files.FolderMetadata):
                     entries = list_folder(self.dbx, p, recursive=False)
                     total += len(entries)
                else:
                    total += 1
        return max(total, 1)

    def on_renamer_tool(self, event):
        dlg = RenamerDialog(self, self.dbx)
        if dlg.ShowModal() == wx.ID_OK:
            config = dlg.get_config()
            # config: (paths, from_ext, to_ext, recursive)
            if not config[0]:
                 wx.MessageBox("No paths selected.", "Info")
                 dlg.Destroy()
                 return
            
            self.run_in_background(self.rename_bulk, *config)
        dlg.Destroy()

    def rename_bulk(self, paths, from_ext, to_ext, recursive):
        """
        Entry point: Starts scan in background.
        """
        from_ext = from_ext.lower()
        to_ext = to_ext.lower()
        
        if not from_ext or not to_ext:
             wx.CallAfter(wx.MessageBox, "Invalid extensions.", "Error")
             return

        # Normalize extensions (ensure dot)
        if not from_ext.startswith("."): from_ext = "." + from_ext
        if not to_ext.startswith("."): to_ext = "." + to_ext

        # 1. Scan Phase
        self.log_msg("🔍 Scanning for files...")
        proposed = self.scan_renames(paths, from_ext, to_ext, recursive)
        
        if not proposed:
            wx.CallAfter(wx.MessageBox, "No files found matching criteria.", "Info")
            return

        # 2. Preview Phase (Must run on GUI thread)
        def show_preview():
            # Temporarily un-busy to allow interaction
            self.set_busy_state(False)
            dlg = PreviewDialog(self, proposed)
            result = dlg.ShowModal()
            dlg.Destroy()
            
            if result == wx.ID_OK:
                # 3. Execution Phase
                self.run_in_background(self.execute_renames, proposed)
            else:
                self.log_msg("⏹️ Rename cancelled by user.")

        wx.CallAfter(show_preview)


    def scan_renames(self, paths, from_ext, to_ext, recursive):
        proposed = [] # (old_name, new_name, src_path, dst_path)
        
        # We need to count files for progress bar during scan? 
        # Scanning itself takes time. Let's just pulsate.
        wx.CallAfter(self.progress.Pulse)
        
        for p in paths:
            if self.cancel_flag: break
            
            target_path = "" if p == "" else p
            
            try:
                md = None
                if target_path != "":
                    md = get_metadata(self.dbx, target_path)
                
                is_folder = (target_path == "") or (isinstance(md, dropbox.files.FolderMetadata))
                
                entries = []
                if is_folder:
                     entries_raw = list_folder(self.dbx, target_path, recursive=recursive)
                     entries = [e for e in entries_raw if isinstance(e, dropbox.files.FileMetadata)]
                elif isinstance(md, dropbox.files.FileMetadata):
                     entries = [md]
                
                for file_md in entries:
                    if file_md.name.lower().endswith(from_ext):
                        # Calculate new name/path
                        old_name = file_md.name
                        new_name = old_name[:-len(from_ext)] + to_ext
                        
                        old_path = file_md.path_display or file_md.path_lower
                        
                        # Parent path logic
                        if "/" in old_path:
                             head = "/".join(old_path.split("/")[:-1])
                        else:
                             head = ""
                             
                        new_path = (head + "/" + new_name).replace("//", "/")
                        
                        proposed.append((old_name, new_name, file_md.path_lower, new_path))
            except Exception as e:
                self.log_msg(f"Error scanning {p}: {e}")
                
        return proposed

    def execute_renames(self, proposed):
        self.total_files = len(proposed)
        self.files_done = 0
        self.cancel_flag = False
        self.pause_flag = False
        self.start_time = time.time()
        self.set_progress(0)
        self.update_eta()

        for old_name, new_name, src, dst in proposed:
            if self.cancel_flag: break
            while self.pause_flag: time.sleep(0.2)
            
            ok = move_path(self.dbx, src, dst, log_func=self.api_log_msg)
            if ok:
                self.log_msg(f"✅ {old_name} → {new_name}")
            else:
                self.log_msg(f"❌ Failed rename: {old_name}")
            
            self.files_done += 1
            self.set_progress(int((self.files_done / self.total_files) * 100))
            self.update_eta()
            
        self.update_eta()

    # ---- Bulk Move ----
    # ---- Bulk Move ----
    # ---- Bulk Move ----
    def on_move_manager(self, event):
        """
        Open Move Manager Dialog.
        """
        dlg = MoveManagerDialog(self, self.dbx)
        if dlg.ShowModal() == wx.ID_OK:
            move_pairs = dlg.get_pairs()
            if not move_pairs: 
                dlg.Destroy()
                return
            
            # Run the actual moves in background
            self.run_in_background(self._run_bulk_moves, move_pairs)
        dlg.Destroy()

    def _run_bulk_moves(self, move_pairs):
        self.total_files = len(move_pairs)
        self.files_done = 0
        self.cancel_flag = False
        self.pause_flag = False
        self.start_time = time.time()
        self.set_progress(0)
        self.update_eta()

        for src, dst in move_pairs:
            if self.cancel_flag: break
            while self.pause_flag: time.sleep(0.2)

            ok = move_path(self.dbx, src, dst, log_func=self.api_log_msg)
            if ok:
                self.log_msg(f"✅ Moved {src} → {dst}")
            else:
                self.log_msg(f"❌ Failed move {src} → {dst}")

            self.files_done += 1
            self.set_progress(int((self.files_done / self.total_files) * 100))
            self.update_eta()

    # ---- Settings ----
    def on_settings(self, event):
        dlg = SettingsDialog(self, [self.dbx])
        dlg.ShowModal()
        dlg.Destroy()


class RenamerDialog(wx.Dialog):
    def __init__(self, parent, dbx):
        super().__init__(parent, title="Extension Renamer Tool", size=(500, 450))
        self.dbx = dbx
        self.paths = []

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # 1. Paths List
        vbox.Add(wx.StaticText(panel, label="Target Files/Folders:"), 0, wx.ALL, 5)
        self.list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_HRULES | wx.LC_VRULES)
        self.list_ctrl.InsertColumn(0, "Path", width=420)
        vbox.Add(self.list_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Path Buttons
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add = wx.Button(panel, label="+ Add")
        self.btn_clear = wx.Button(panel, label="Clear")
        btn_row.Add(self.btn_add, 0, wx.RIGHT, 5)
        btn_row.Add(self.btn_clear, 0)
        vbox.Add(btn_row, 0, wx.ALL, 10)

        # 2. Settings (From / To / Recursive)
        sb = wx.StaticBox(panel, label="Renaming Rules")
        sbs = wx.StaticBoxSizer(sb, wx.VERTICAL)
        
        input_grid = wx.FlexGridSizer(rows=2, cols=2, vgap=10, hgap=10)
        
        input_grid.Add(wx.StaticText(panel, label="From Extension:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.txt_from = wx.TextCtrl(panel, value=".mp3", size=(100, -1))
        input_grid.Add(self.txt_from, 0, wx.EXPAND)
        
        input_grid.Add(wx.StaticText(panel, label="To Extension:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.txt_to = wx.TextCtrl(panel, value=".mp4", size=(100, -1))
        input_grid.Add(self.txt_to, 0, wx.EXPAND)
        
        sbs.Add(input_grid, 0, wx.ALL, 10)
        
        self.chk_recursive = wx.CheckBox(panel, label="Recursive Search")
        sbs.Add(self.chk_recursive, 0, wx.ALL, 10)
        
        vbox.Add(sbs, 0, wx.EXPAND | wx.ALL, 10)

        # 3. Action Buttons
        hbox_cmds = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_run = wx.Button(panel, wx.ID_OK, label="Preview Changes")
        self.btn_cancel = wx.Button(panel, wx.ID_CANCEL, label="Cancel")
        hbox_cmds.Add(self.btn_run, 0, wx.RIGHT, 10)
        hbox_cmds.Add(self.btn_cancel, 0)
        vbox.Add(hbox_cmds, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        panel.SetSizer(vbox)

        # Bindings
        self.btn_add.Bind(wx.EVT_BUTTON, self.on_add)
        self.btn_clear.Bind(wx.EVT_BUTTON, self.on_clear)

    def on_add(self, event):
        # Pass log_func from parent if possible
        log_f = None
        if isinstance(self.GetParent(), DropboxApp):
            log_f = self.GetParent().api_log_msg
            
        dlg = DropboxBrowser(self.dbx, self, message="Select Files or Folders to Rename", log_func=log_f)
        if dlg.ShowModal() == wx.ID_OK:
            for p in dlg.selected_paths:
                if p not in self.paths:
                    self.paths.append(p)
                    self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), p)
        dlg.Destroy()

    def on_clear(self, event):
        self.paths = []
        self.list_ctrl.DeleteAllItems()
        
    def get_config(self):
        return (
            self.paths,
            self.txt_from.GetValue().strip(),
            self.txt_to.GetValue().strip(),
            self.chk_recursive.IsChecked()
        )


class MoveManagerDialog(wx.Dialog):
    def __init__(self, parent, dbx):
        super().__init__(parent, title="Move Manager", size=(600, 400))
        self.dbx = dbx
        self.pairs = [] # List of (src, dst)

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # List Control
        self.list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_HRULES | wx.LC_VRULES)
        self.list_ctrl.InsertColumn(0, "Source Path", width=280)
        self.list_ctrl.InsertColumn(1, "Destination Path", width=280)
        vbox.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 10)

        # Buttons
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add = wx.Button(panel, label="+ Add Move Pair")
        self.btn_remove = wx.Button(panel, label="- Remove Selected")
        self.btn_change = wx.Button(panel, label="Change Destination")
        self.btn_clear = wx.Button(panel, label="Clear All")
        
        btn_box.Add(self.btn_add, 0, wx.RIGHT, 5)
        btn_box.Add(self.btn_remove, 0, wx.RIGHT, 5)
        btn_box.Add(self.btn_change, 0, wx.RIGHT, 5)
        btn_box.Add(self.btn_clear, 0)
        vbox.Add(btn_box, 0, wx.ALIGN_LEFT | wx.LEFT | wx.RIGHT, 10)

        # Main Actions
        action_box = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(panel, wx.ID_OK, label="Run Moves")
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, label="Cancel")
        action_box.Add(ok_btn, 0, wx.RIGHT, 10)
        action_box.Add(cancel_btn, 0)
        vbox.Add(action_box, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        panel.SetSizer(vbox)

        # Events
        self.btn_add.Bind(wx.EVT_BUTTON, self.on_add)
        self.btn_remove.Bind(wx.EVT_BUTTON, self.on_remove)
        self.btn_change.Bind(wx.EVT_BUTTON, self.on_change_dest)
        self.btn_clear.Bind(wx.EVT_BUTTON, self.on_clear)

    def on_add(self, event):
        # 1. Pick Source Files/Folders (using existing DropboxPicker)
        # Note: DropboxPicker selects PATHS.
        # Pass log_func from parent (DropboxApp)
        log_f = None
        if isinstance(self.GetParent(), DropboxApp):
            log_f = self.GetParent().api_log_msg

        dlg = DropboxBrowser(self.dbx, self, message="Select Source File(s) or Folder(s)", log_func=log_f)
        if dlg.ShowModal() == wx.ID_OK:
            sources = dlg.selected_paths
            if not sources:
                dlg.Destroy()
                return
            
            # 2. Pick Destination Folder
            dlg_dst = DropboxBrowser(self.dbx, self, message=f"Select Destination Folder for {len(sources)} items", log_func=log_f)
            if dlg_dst.ShowModal() == wx.ID_OK:
                dst_targets = dlg_dst.selected_paths
                if len(dst_targets) == 1:
                    base_dst = dst_targets[0]
                    # Logic: New path = base_dst + / + original_filename
                    for src in sources:
                         filename = src.split("/")[-1] # Basic split (Dropbox paths always /)
                         if not filename: continue # root?
                         new_full_path = (base_dst + "/" + filename).replace("//", "/")
                         self.add_pair(src, new_full_path)
                else:
                    wx.MessageBox("Please select exactly ONE destination folder.", "Error", wx.ICON_ERROR)
            dlg_dst.Destroy()
        dlg.Destroy()

    def add_pair(self, src, dst):
        self.pairs.append((src, dst))
        idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), src)
        self.list_ctrl.SetItem(idx, 1, dst)

    def on_remove(self, event):
        item = self.list_ctrl.GetFirstSelected()
        while item != -1:
            # Note: Deleting items shifts indices, so best to collect indices first or delete from bottom.
            # Or just delete one by one and restart search (inefficient but safe for single select).
            # If multiple style enabled? Default is multiple.
            # Let's just delete the first selected and return (re-click for more) OR handle carefully.
            # Simpler: Get all selected.
            pass
        
        # Robust delete:
        selected = []
        item = self.list_ctrl.GetFirstSelected()
        while item != -1:
            selected.append(item)
            item = self.list_ctrl.GetNextSelected(item)
        
        selected.sort(reverse=True) # Delete from bottom up
        for idx in selected:
            self.list_ctrl.DeleteItem(idx)
            del self.pairs[idx]

    def on_clear(self, event):
        self.list_ctrl.DeleteAllItems()
        self.pairs = []

    def on_change_dest(self, event):
        idx = self.list_ctrl.GetFirstSelected()
        if idx == -1: return

        # Get current pair
        src, old_dst = self.pairs[idx]
        
        # Pick new folder
        log_f = None
        if isinstance(self.GetParent(), DropboxApp):
            log_f = self.GetParent().api_log_msg

        dlg = DropboxBrowser(self.dbx, self, message="Select NEW Destination Folder", log_func=log_f)
        if dlg.ShowModal() == wx.ID_OK:
            targets = dlg.selected_paths
            # We expect 1 folder (or root)
            # If user picked multiple, take first? 
            # Or assume browser returns list.
            if targets:
                base_dst = targets[0]
                # Reconstruct filename
                filename = src.split("/")[-1]
                new_full_path = (base_dst + "/" + filename).replace("//", "/")
                
                # Update data
                self.pairs[idx] = (src, new_full_path)
                # Update UI
                self.list_ctrl.SetItem(idx, 1, new_full_path)
        dlg.Destroy()

    def get_pairs(self):
        return self.pairs




# =========================
# Entry Point
# =========================
if __name__ == "__main__":
    # Create GUI app first so we can show dialogs if token missing
    app = wx.App(False)

    token = get_access_token_noninteractive()
    if not token:
        # Ask via LoginDialog (OAuth)
        dlg = LoginDialog(None)
        if dlg.ShowModal() == wx.ID_OK:
            token = dlg.refresh_token
            if token:
                save_token(token)
        dlg.Destroy()

    if not token:
        wx.MessageBox("No Dropbox API token provided. Exiting.", "Error", wx.ICON_ERROR)
        raise SystemExit(1)

    app_key = load_app_key()
    try:
        # If we have an app key, try to use refresh token logic
        if app_key:
             dbx = dropbox.Dropbox(app_key=app_key, oauth2_refresh_token=token)
             # Force a check to ensure token is valid/refreshable
             dbx.users_get_current_account()
        else:
             # Legacy fallback (shouldn't be hit with new flow)
             dbx = dropbox.Dropbox(token)
             dbx.users_get_current_account()
             
        print("✅ Connected to Dropbox")
    except AuthError as e:
        wx.MessageBox(f"Invalid Dropbox token: {e}", "Auth Error", wx.ICON_ERROR)
        raise SystemExit(1)

    frame = DropboxApp(dbx)
    app.MainLoop()
