import wx
import os
import re
from pathlib import Path
from collections import OrderedDict

class CategoryReorderTool(wx.Frame):
    def __init__(self):
        super().__init__(None, title="M3U Category Reorder Tool", size=(800, 600))
        
        self.current_file = None
        self.categories = OrderedDict()
        self.modified = False
        
        self.init_ui()
        self.create_menu_bar()
        self.bind_keyboard_shortcuts()
        self.Centre()
        
    def init_ui(self):
        self.panel = wx.Panel(self)
        main_vbox = wx.BoxSizer(wx.VERTICAL)
        
        # File info section
        info_box = wx.BoxSizer(wx.HORIZONTAL)
        self.file_label = wx.StaticText(self.panel, label="No file loaded")
        self.file_label.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        info_box.Add(self.file_label, 0, wx.ALL, 5)
        main_vbox.Add(info_box, 0, wx.EXPAND | wx.ALL, 10)
        
        # Categories list section
        list_label = wx.StaticText(self.panel, label="Categories (Shift+Up/Down to reorder, F2 to rename, Delete to remove):")
        main_vbox.Add(list_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        
        self.category_list = wx.ListBox(self.panel, style=wx.LB_EXTENDED | wx.LB_NEEDED_SB)
        self.category_list.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
        self.category_list.Bind(wx.EVT_LISTBOX, self.on_category_select)
        main_vbox.Add(self.category_list, 1, wx.EXPAND | wx.ALL, 10)
        
        # Control buttons
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        
        self.move_up_btn = wx.Button(self.panel, label="Move Up (Shift+↑)")
        self.move_up_btn.Bind(wx.EVT_BUTTON, self.on_move_up)
        self.move_up_btn.Enable(False)
        btn_box.Add(self.move_up_btn, 0, wx.RIGHT, 10)
        
        self.move_down_btn = wx.Button(self.panel, label="Move Down (Shift+↓)")
        self.move_down_btn.Bind(wx.EVT_BUTTON, self.on_move_down)
        self.move_down_btn.Enable(False)
        btn_box.Add(self.move_down_btn, 0, wx.RIGHT, 10)
        
        self.rename_btn = wx.Button(self.panel, label="Rename (F2)")
        self.rename_btn.Bind(wx.EVT_BUTTON, self.on_rename_category)
        self.rename_btn.Enable(False)
        btn_box.Add(self.rename_btn, 0, wx.RIGHT, 10)
        
        self.remove_btn = wx.Button(self.panel, label="Remove Selected (Delete)")
        self.remove_btn.Bind(wx.EVT_BUTTON, self.on_remove_categories)
        self.remove_btn.Enable(False)
        btn_box.Add(self.remove_btn, 0)
        
        main_vbox.Add(btn_box, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        # Status bar
        self.status_bar = self.CreateStatusBar()
        self.status_bar.SetStatusText("Ready. Press Ctrl+O to open an M3U file")
        
        self.panel.SetSizer(main_vbox)
        
    def create_menu_bar(self):
        menubar = wx.MenuBar()
        
        # File menu
        file_menu = wx.Menu()
        open_item = file_menu.Append(wx.ID_OPEN, "&Open M3U\tCtrl+O", "Open an M3U playlist file")
        file_menu.AppendSeparator()
        save_item = file_menu.Append(wx.ID_SAVE, "&Save\tCtrl+S", "Save changes to current file")
        save_as_item = file_menu.Append(wx.ID_SAVEAS, "Save &As\tCtrl+Shift+S", "Save to a new file")
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "E&xit\tAlt+F4", "Exit application")
        
        self.Bind(wx.EVT_MENU, self.on_open, open_item)
        self.Bind(wx.EVT_MENU, self.on_save, save_item)
        self.Bind(wx.EVT_MENU, self.on_save_as, save_as_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        
        menubar.Append(file_menu, "&File")
        
        # Help menu
        help_menu = wx.Menu()
        about_item = help_menu.Append(wx.ID_ABOUT, "&About\tF1", "About this tool")
        self.Bind(wx.EVT_MENU, self.on_about, about_item)
        
        menubar.Append(help_menu, "&Help")
        
        self.SetMenuBar(menubar)
        
    def bind_keyboard_shortcuts(self):
        # Escape to close
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_NORMAL, wx.WXK_ESCAPE, wx.ID_EXIT)
        ])
        self.SetAcceleratorTable(accel_tbl)
        
    def on_open(self, event):
        dlg = wx.FileDialog(
            self, 
            "Open M3U Playlist", 
            wildcard="M3U Playlist (*.m3u)|*.m3u|All files (*.*)|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )
        
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self.load_m3u(path)
        
        dlg.Destroy()
        
    def load_m3u(self, file_path):
        try:
            self.status_bar.SetStatusText(f"Loading {os.path.basename(file_path)}...")
            
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            if not lines or not lines[0].strip().startswith('#EXTM3U'):
                wx.MessageBox("Not a valid M3U file", "Error", wx.OK | wx.ICON_ERROR)
                self.status_bar.SetStatusText("Failed to load file")
                return
            
            self.categories = OrderedDict()
            i = 1
            
            while i < len(lines):
                line = lines[i].strip()
                
                if line.startswith('#EXTINF'):
                    # Extract category
                    match = re.search(r'group-title="([^"]+)"', line)
                    if match:
                        category = match.group(1)
                        
                        if category not in self.categories:
                            self.categories[category] = []
                        
                        # Get URL line
                        if i + 1 < len(lines):
                            url_line = lines[i + 1].strip()
                            self.categories[category].append({
                                'extinf': line,
                                'url': url_line
                            })
                            i += 2
                        else:
                            i += 1
                    else:
                        i += 1
                else:
                    i += 1
            
            self.current_file = file_path
            self.modified = False
            self.update_category_list()
            
            total_files = sum(len(entries) for entries in self.categories.values())
            self.file_label.SetLabel(f"File: {os.path.basename(file_path)}")
            self.status_bar.SetStatusText(
                f"Loaded {len(self.categories)} categories with {total_files} total files"
            )
            
            # Set focus to list
            self.category_list.SetFocus()
            if self.category_list.GetCount() > 0:
                self.category_list.SetSelection(0)
                self.update_button_states()
            
        except Exception as e:
            wx.MessageBox(f"Error loading file:\n{e}", "Error", wx.OK | wx.ICON_ERROR)
            self.status_bar.SetStatusText("Failed to load file")
            
    def update_category_list(self):
        self.category_list.Clear()
        for category, entries in self.categories.items():
            file_count = len(entries)
            display_text = f"{category} ({file_count} file{'s' if file_count != 1 else ''})"
            self.category_list.Append(display_text, category)
        
    def on_category_select(self, event):
        self.update_button_states()
        
    def update_button_states(self):
        selections = self.category_list.GetSelections()
        count = self.category_list.GetCount()
        
        # Enable remove button if any categories are selected
        self.remove_btn.Enable(len(selections) > 0)
        
        # Move and rename buttons only work with single selection
        if len(selections) == 1:
            selection = selections[0]
            self.move_up_btn.Enable(selection > 0)
            self.move_down_btn.Enable(selection < count - 1)
            self.rename_btn.Enable(True)
        else:
            self.move_up_btn.Enable(False)
            self.move_down_btn.Enable(False)
            self.rename_btn.Enable(False)
    
    def on_key_down(self, event):
        keycode = event.GetKeyCode()
        
        if event.ShiftDown() and keycode == wx.WXK_UP:
            self.move_category_up()
        elif event.ShiftDown() and keycode == wx.WXK_DOWN:
            self.move_category_down()
        elif keycode == wx.WXK_F2:
            self.on_rename_category(event)
        elif keycode == wx.WXK_DELETE:
            self.on_remove_categories(event)
        else:
            event.Skip()
    
    def on_move_up(self, event):
        self.move_category_up()
        
    def on_move_down(self, event):
        self.move_category_down()
        
    def move_category_up(self):
        selections = self.category_list.GetSelections()
        if len(selections) != 1:
            return
        selection = selections[0]
        if selection <= 0:
            return
        
        # Get category keys as list
        categories_list = list(self.categories.keys())
        
        # Swap in list
        categories_list[selection], categories_list[selection - 1] = \
            categories_list[selection - 1], categories_list[selection]
        
        # Rebuild OrderedDict
        new_categories = OrderedDict()
        for cat in categories_list:
            new_categories[cat] = self.categories[cat]
        
        self.categories = new_categories
        self.modified = True
        
        # Update UI
        self.update_category_list()
        self.category_list.SetSelection(selection - 1)
        self.update_button_states()
        
        category_name = categories_list[selection - 1]
        self.status_bar.SetStatusText(f"Moved '{category_name}' up")
        
    def move_category_down(self):
        selections = self.category_list.GetSelections()
        if len(selections) != 1:
            return
        selection = selections[0]
        if selection >= self.category_list.GetCount() - 1:
            return
        
        # Get category keys as list
        categories_list = list(self.categories.keys())
        
        # Swap in list
        categories_list[selection], categories_list[selection + 1] = \
            categories_list[selection + 1], categories_list[selection]
        
        # Rebuild OrderedDict
        new_categories = OrderedDict()
        for cat in categories_list:
            new_categories[cat] = self.categories[cat]
        
        self.categories = new_categories
        self.modified = True
        
        # Update UI
        self.update_category_list()
        self.category_list.SetSelection(selection + 1)
        self.update_button_states()
        
        category_name = categories_list[selection + 1]
        self.status_bar.SetStatusText(f"Moved '{category_name}' down")
        
    def on_save(self, event):
        if not self.current_file:
            wx.MessageBox("No file loaded", "Cannot Save", wx.OK | wx.ICON_WARNING)
            return
        
        if not self.modified:
            wx.MessageBox("No changes to save", "Nothing to Save", wx.OK | wx.ICON_INFORMATION)
            return
        
        # Create backup
        backup_path = Path(self.current_file).with_suffix('.m3u.bak')
        try:
            Path(self.current_file).rename(backup_path)
            self.save_m3u(self.current_file)
            self.status_bar.SetStatusText(f"Saved to {os.path.basename(self.current_file)} (backup created)")
        except Exception as e:
            wx.MessageBox(f"Error saving file:\n{e}", "Save Error", wx.OK | wx.ICON_ERROR)
            
    def on_save_as(self, event):
        if not self.categories:
            wx.MessageBox("No categories loaded", "Cannot Save", wx.OK | wx.ICON_WARNING)
            return
        
        default_name = os.path.basename(self.current_file) if self.current_file else "playlist.m3u"
        default_dir = os.path.dirname(self.current_file) if self.current_file else os.getcwd()
        
        dlg = wx.FileDialog(
            self,
            "Save M3U As",
            defaultDir=default_dir,
            defaultFile=default_name,
            wildcard="M3U Playlist (*.m3u)|*.m3u",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        )
        
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self.save_m3u(path)
            self.current_file = path
            self.file_label.SetLabel(f"File: {os.path.basename(path)}")
            self.status_bar.SetStatusText(f"Saved to {os.path.basename(path)}")
        
        dlg.Destroy()
        
    def on_rename_category(self, event):
        selections = self.category_list.GetSelections()
        if len(selections) != 1:
            return
        
        idx = selections[0]
        old_category = self.category_list.GetClientData(idx)
        
        if not old_category or old_category not in self.categories:
            return
        
        # Show rename dialog
        dlg = wx.TextEntryDialog(
            self,
            f"Enter new name for category:\n\nCurrent: {old_category}",
            "Rename Category",
            old_category
        )
        
        if dlg.ShowModal() == wx.ID_OK:
            new_category = dlg.GetValue().strip()
            
            if not new_category:
                wx.MessageBox("Category name cannot be empty", "Invalid Name", wx.OK | wx.ICON_WARNING)
                dlg.Destroy()
                return
            
            if new_category == old_category:
                dlg.Destroy()
                return
            
            # Check if new name already exists
            if new_category in self.categories:
                result = wx.MessageBox(
                    f"Category '{new_category}' already exists.\n\nMerge '{old_category}' into '{new_category}'?",
                    "Category Exists",
                    wx.YES_NO | wx.ICON_QUESTION
                )
                
                if result == wx.YES:
                    # Merge: add old category's files to existing category
                    self.categories[new_category].extend(self.categories[old_category])
                    del self.categories[old_category]
                    self.modified = True
                    self.update_category_list()
                    self.status_bar.SetStatusText(f"Merged '{old_category}' into '{new_category}'")
                    
                    # Select the merged category
                    for i in range(self.category_list.GetCount()):
                        if self.category_list.GetClientData(i) == new_category:
                            self.category_list.SetSelection(i)
                            break
                    self.update_button_states()
                
                dlg.Destroy()
                return
            
            # Rename category
            new_categories = OrderedDict()
            for cat, entries in self.categories.items():
                if cat == old_category:
                    new_categories[new_category] = entries
                else:
                    new_categories[cat] = entries
            
            self.categories = new_categories
            self.modified = True
            
            # Update UI
            self.update_category_list()
            self.status_bar.SetStatusText(f"Renamed '{old_category}' to '{new_category}'")
            
            # Re-select the renamed category
            for i in range(self.category_list.GetCount()):
                if self.category_list.GetClientData(i) == new_category:
                    self.category_list.SetSelection(i)
                    break
            
            self.update_button_states()
            self.category_list.SetFocus()
        
        dlg.Destroy()
    
    def on_remove_categories(self, event):
        selections = self.category_list.GetSelections()
        if not selections:
            return
        
        # Get category names to remove
        categories_to_remove = []
        for idx in selections:
            category_key = self.category_list.GetClientData(idx)
            categories_to_remove.append(category_key)
        
        # Confirm deletion
        if len(categories_to_remove) == 1:
            msg = f"Remove category '{categories_to_remove[0]}'?\n\nThis will delete all files in this category."
        else:
            msg = f"Remove {len(categories_to_remove)} selected categories?\n\nThis will delete all files in these categories."
        
        dlg = wx.MessageDialog(
            self,
            msg,
            "Confirm Remove",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION
        )
        
        if dlg.ShowModal() == wx.ID_YES:
            # Remove categories
            for category in categories_to_remove:
                if category in self.categories:
                    del self.categories[category]
            
            self.modified = True
            
            # Update UI
            self.update_category_list()
            
            # Update status
            if len(categories_to_remove) == 1:
                self.status_bar.SetStatusText(f"Removed category '{categories_to_remove[0]}'")
            else:
                self.status_bar.SetStatusText(f"Removed {len(categories_to_remove)} categories")
            
            # Set focus back to list
            self.category_list.SetFocus()
            if self.category_list.GetCount() > 0:
                # Select first item if available
                self.category_list.SetSelection(0)
            self.update_button_states()
        
        dlg.Destroy()
    
    def save_m3u(self, file_path):
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('#EXTM3U\n')
                
                for category, entries in self.categories.items():
                    for entry in entries:
                        f.write(entry['extinf'] + '\n')
                        f.write(entry['url'] + '\n')
            
            self.modified = False
            wx.MessageBox(
                f"Successfully saved {len(self.categories)} categories",
                "Save Complete",
                wx.OK | wx.ICON_INFORMATION
            )
            
        except Exception as e:
            raise Exception(f"Failed to write file: {e}")
            
    def on_about(self, event):
        info = wx.adv.AboutDialogInfo()
        info.SetName("M3U Category Reorder Tool")
        info.SetVersion("1.0")
        info.SetDescription(
            "Reorder and manage categories in M3U playlists with keyboard shortcuts.\n\n"
            "Keyboard Shortcuts:\n"
            "• Ctrl+O - Open M3U file\n"
            "• Ctrl+S - Save changes\n"
            "• Ctrl+Shift+S - Save As\n"
            "• Shift+Up - Move category up\n"
            "• Shift+Down - Move category down\n"
            "• F2 - Rename category\n"
            "• Delete - Remove selected categories\n"
            "• Ctrl+Click - Multi-select categories\n"
            "• Escape - Exit\n\n"
            "Fully accessible for screen readers."
        )
        wx.adv.AboutBox(info)
        
    def on_exit(self, event):
        if self.modified:
            dlg = wx.MessageDialog(
                self,
                "You have unsaved changes. Exit anyway?",
                "Unsaved Changes",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION
            )
            if dlg.ShowModal() == wx.ID_NO:
                dlg.Destroy()
                return
            dlg.Destroy()
        
        self.Close()

if __name__ == '__main__':
    app = wx.App()
    frame = CategoryReorderTool()
    frame.Show()
    app.MainLoop()
