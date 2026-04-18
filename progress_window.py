import wx
import wx.lib.scrolledpanel as scrolled

class ProgressWindow(wx.Frame):
    def __init__(self, parent, title="Processing Files"):
        super().__init__(parent, title=title, size=(700, 500))
        self.SetBackgroundColour(wx.WHITE)
        
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Header with stats
        header_box = wx.StaticBox(panel, label="Progress Statistics")
        header_sizer = wx.StaticBoxSizer(header_box, wx.HORIZONTAL)
        
        self.processed_text = wx.StaticText(panel, label="Processed: 0")
        self.processed_text.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.processed_text.SetForegroundColour(wx.Colour(46, 125, 50))
        
        self.skipped_text = wx.StaticText(panel, label="Skipped: 0")
        self.skipped_text.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.skipped_text.SetForegroundColour(wx.Colour(211, 47, 47))
        
        self.total_text = wx.StaticText(panel, label="Total: 0")
        self.total_text.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        
        header_sizer.Add(self.processed_text, 0, wx.ALL, 10)
        header_sizer.Add(self.skipped_text, 0, wx.ALL, 10)
        header_sizer.Add(self.total_text, 0, wx.ALL, 10)
        
        main_sizer.Add(header_sizer, 0, wx.EXPAND|wx.ALL, 10)
        
        # Progress bar
        self.progress_bar = wx.Gauge(panel, range=100)
        main_sizer.Add(self.progress_bar, 0, wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, 10)
        
        # Current file label
        self.current_file_label = wx.StaticText(panel, label="Ready to start...")
        self.current_file_label.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        main_sizer.Add(self.current_file_label, 0, wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, 10)
        
        # Console log area
        log_box = wx.StaticBox(panel, label="Processing Log")
        log_sizer = wx.StaticBoxSizer(log_box, wx.VERTICAL)
        
        self.log_text = wx.TextCtrl(panel, style=wx.TE_MULTILINE|wx.TE_READONLY|wx.TE_WORDWRAP)
        self.log_text.SetFont(wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.log_text.SetBackgroundColour(wx.Colour(250, 250, 250))
        
        log_sizer.Add(self.log_text, 1, wx.EXPAND|wx.ALL, 5)
        main_sizer.Add(log_sizer, 1, wx.EXPAND|wx.LEFT|wx.RIGHT, 10)
        
        # Control buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.cancel_btn = wx.Button(panel, label="Cancel Processing")
        self.cancel_btn.SetBackgroundColour(wx.Colour(211, 47, 47))
        self.cancel_btn.SetForegroundColour(wx.WHITE)
        self.cancel_btn.Bind(wx.EVT_BUTTON, self.on_cancel)
        
        self.close_btn = wx.Button(panel, label="Close")
        self.close_btn.Enable(False)
        self.close_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        
        button_sizer.Add(self.cancel_btn, 1, wx.EXPAND|wx.RIGHT, 5)
        button_sizer.Add(self.close_btn, 1, wx.EXPAND|wx.LEFT, 5)
        
        main_sizer.Add(button_sizer, 0, wx.EXPAND|wx.ALL, 10)
        
        panel.SetSizer(main_sizer)
        
        # State tracking
        self.cancelled = False
        self.processed_count = 0
        self.skipped_count = 0
        self.total_count = 0
        
        # Center window
        self.Centre()
        
    def set_total(self, total):
        """Set total number of files to process"""
        self.total_count = total
        wx.CallAfter(self._update_total_display)
        
    def _update_total_display(self):
        self.total_text.SetLabel(f"Total: {self.total_count}")
        
    def log(self, message, status="info"):
        """Add a log message with timestamp"""
        wx.CallAfter(self._append_log, message, status)
        
    def _append_log(self, message, status):
        timestamp = wx.DateTime.Now().Format("%H:%M:%S")
        
        if status == "success":
            prefix = "✓"
            color = wx.Colour(46, 125, 50)
        elif status == "error":
            prefix = "✗"
            color = wx.Colour(211, 47, 47)
        elif status == "warning":
            prefix = "⚠"
            color = wx.Colour(245, 124, 0)
        else:
            prefix = "•"
            color = wx.Colour(66, 66, 66)
        
        formatted_msg = f"[{timestamp}] {prefix} {message}\n"
        
        # Append to log
        current_pos = self.log_text.GetLastPosition()
        self.log_text.AppendText(formatted_msg)
        
        # Auto-scroll to bottom
        self.log_text.ShowPosition(self.log_text.GetLastPosition())
        
    def update_progress(self, current, total, filename=""):
        """Update progress bar and current file label"""
        wx.CallAfter(self._update_progress_display, current, total, filename)
        
    def _update_progress_display(self, current, total, filename):
        if total > 0:
            percentage = int((current / total) * 100)
            self.progress_bar.SetValue(percentage)
        
        if filename:
            self.current_file_label.SetLabel(f"Processing: {filename}")
        
    def increment_processed(self):
        """Increment processed counter"""
        self.processed_count += 1
        wx.CallAfter(self._update_processed_display)
        
    def _update_processed_display(self):
        self.processed_text.SetLabel(f"Processed: {self.processed_count}")
        
    def increment_skipped(self):
        """Increment skipped counter"""
        self.skipped_count += 1
        wx.CallAfter(self._update_skipped_display)
        
    def _update_skipped_display(self):
        self.skipped_text.SetLabel(f"Skipped: {self.skipped_count}")
        
    def mark_complete(self):
        """Mark processing as complete"""
        wx.CallAfter(self._mark_complete_display)
        
    def _mark_complete_display(self):
        self.progress_bar.SetValue(100)
        self.current_file_label.SetLabel("Processing complete!")
        self.cancel_btn.Enable(False)
        self.close_btn.Enable(True)
        
    def mark_cancelled(self):
        """Mark processing as cancelled"""
        wx.CallAfter(self._mark_cancelled_display)
        
    def _mark_cancelled_display(self):
        self.current_file_label.SetLabel("Processing cancelled by user")
        self.cancel_btn.Enable(False)
        self.close_btn.Enable(True)
        
    def on_cancel(self, event):
        """Handle cancel button click"""
        self.cancelled = True
        self.cancel_btn.Enable(False)
        self.current_file_label.SetLabel("Cancelling...")
        self.log("Cancel requested - finishing current file...", "warning")
        
    def is_cancelled(self):
        """Check if user has cancelled"""
        return self.cancelled
