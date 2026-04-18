import wx
import wx.adv

import webbrowser
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

from auth_store import KeyringAuthStore
from onboarding_logic import validate_access_token


class DropboxSdkClientFactory:
    def __init__(self, dropbox_module):
        self.dropbox_module = dropbox_module

    def from_access_token(self, token: str):
        return self.dropbox_module.Dropbox(oauth2_access_token=token)


class SetupWizard(wx.adv.Wizard):
    def __init__(self, parent, service_name: str, dropbox_module, consumer_app_key: str = ""):
        super().__init__(parent, title="Setup Wizard")

        self._auth_store = KeyringAuthStore(service_name)
        self._existing_auth = self._auth_store.load()
        self._dropbox_module = dropbox_module
        self._factory = DropboxSdkClientFactory(dropbox_module)
        self._did_replace = False

        self.consumer_app_key = (consumer_app_key or "").strip()

        self.page_welcome = _WelcomePage(self)
        self.page_connected = _AlreadyConnectedPage(self)
        self.page_method = _AuthMethodPage(self)
        self.page_oauth = _OAuthPage(self)
        self.page_token = _AccessTokenPage(self)
        self.page_done = _DonePage(self)

        if self._existing_auth.has_auth():
            wx.adv.WizardPageSimple.Chain(self.page_welcome, self.page_connected)
            wx.adv.WizardPageSimple.Chain(self.page_connected, self.page_method)
            wx.adv.WizardPageSimple.Chain(self.page_method, self.page_token)
        else:
            wx.adv.WizardPageSimple.Chain(self.page_welcome, self.page_method)
            wx.adv.WizardPageSimple.Chain(self.page_method, self.page_token)

        wx.adv.WizardPageSimple.Chain(self.page_oauth, self.page_done)
        wx.adv.WizardPageSimple.Chain(self.page_token, self.page_done)

        self.GetPageAreaSizer().Add(self.page_welcome)

        wx.CallAfter(self._show_nav_buttons)

    def _show_nav_buttons(self):
        for _id in (wx.ID_BACKWARD, wx.ID_FORWARD):
            try:
                btn = self.FindWindowById(_id)
                if btn:
                    btn.Show(True)
            except Exception:
                pass

    def set_forward_enabled(self, enabled: bool):
        try:
            btn = self.FindWindowById(wx.ID_FORWARD)
            if btn:
                btn.Enable(bool(enabled))
        except Exception:
            pass

    def save_access_token(self, token: str) -> None:
        self._auth_store.wipe_all()
        self._auth_store.save_access_token(token)

    def save_oauth(self, app_key: str, refresh_token: str) -> None:
        self._auth_store.wipe_all()
        self._auth_store.save_app_key_secret(app_key, "")
        self._auth_store.save_refresh_token(refresh_token)

    def validate_token(self, token: str):
        return validate_access_token(token, self._factory)


class _WelcomePage(wx.adv.WizardPageSimple):
    def __init__(self, wizard: SetupWizard):
        super().__init__(wizard)
        self.wizard = wizard
        sizer = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(self, label="Welcome")
        title.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        sizer.Add(title, 0, wx.ALL, 10)

        body = wx.StaticText(
            self,
            label=(
                "This wizard helps you connect to Dropbox and start generating playlists.\n\n"
                "Next: continue setup."
            ),
        )
        sizer.Add(body, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizer(sizer)

        self.Bind(wx.adv.EVT_WIZARD_PAGE_CHANGED, self._on_page_changed)

    def _on_page_changed(self, event):
        if event.GetPage() is self:
            wx.CallAfter(self.wizard.set_forward_enabled, True)
        event.Skip()


class _AlreadyConnectedPage(wx.adv.WizardPageSimple):
    def __init__(self, wizard: SetupWizard):
        super().__init__(wizard)
        self.wizard = wizard

        sizer = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(self, label="Already Connected")
        title.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        sizer.Add(title, 0, wx.ALL, 10)

        mode = "access token" if wizard._existing_auth.access_token else "refresh token" if wizard._existing_auth.refresh_token else "unknown"
        body = wx.StaticText(
            self,
            label=(
                "Dropbox credentials are already stored on this machine.\n\n"
                f"Current mode: {mode}\n\n"
                "What would you like to do?"
            ),
        )
        sizer.Add(body, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.choice_keep = wx.RadioButton(self, label="Keep current connection", style=wx.RB_GROUP)
        self.choice_replace = wx.RadioButton(self, label="Replace connection")
        sizer.Add(self.choice_keep, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(self.choice_replace, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizer(sizer)

        self.Bind(wx.adv.EVT_WIZARD_PAGE_CHANGED, self._on_page_changed)

    def _on_page_changed(self, event):
        if event.GetPage() is self:
            try:
                btn = self.wizard.FindWindowById(wx.ID_FORWARD)
                if btn:
                    btn.Enable(True)
            except Exception:
                pass
        event.Skip()

    def GetNext(self):
        if self.choice_keep.GetValue():
            return self.wizard.page_done
        return self.wizard.page_method


class _AuthMethodPage(wx.adv.WizardPageSimple):
    def __init__(self, wizard: SetupWizard):
        super().__init__(wizard)
        self.wizard = wizard

        sizer = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(self, label="Choose Connection Method")
        title.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        sizer.Add(title, 0, wx.ALL, 10)

        body = wx.StaticText(
            self,
            label=(
                "Choose how you want to connect to Dropbox:\n\n"
                "- OAuth (recommended): App Key/Secret + auth code, saved as a refresh token.\n"
                "- Access Token (advanced): paste an access token directly."
            ),
        )
        sizer.Add(body, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.choice_oauth = wx.RadioButton(self, label="OAuth (App Key + App Secret)", style=wx.RB_GROUP)
        self.choice_token = wx.RadioButton(self, label="Paste Access Token")
        sizer.Add(self.choice_oauth, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        sizer.Add(self.choice_token, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizer(sizer)

        self.Bind(wx.adv.EVT_WIZARD_PAGE_CHANGED, self._on_page_changed)

    def _on_page_changed(self, event):
        if event.GetPage() is self:
            try:
                btn = self.wizard.FindWindowById(wx.ID_FORWARD)
                if btn:
                    btn.Enable(True)
            except Exception:
                pass
        event.Skip()

    def GetNext(self):
        if self.choice_oauth.GetValue():
            return self.wizard.page_oauth
        return self.wizard.page_token


class _OAuthPage(wx.adv.WizardPageSimple):
    def __init__(self, wizard: SetupWizard):
        super().__init__(wizard)
        self.wizard = wizard

        self._flow = None
        self._session = {}
        self._csrf_key = "dropbox-auth-csrf-token"
        self._oauth_ok = False

        sizer = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(self, label="OAuth Connect (Recommended)")
        title.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        sizer.Add(title, 0, wx.ALL, 10)

        self.info_box = wx.TextCtrl(
            self,
            value=(
                "OAuth (Automatic)\r\n\r\n"
                "Click 'Connect in Browser' to sign in to Dropbox.\r\n"
                "After approval, the browser will redirect back to this app automatically.\r\n\r\n"
                "Status: Not connected"
            ),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
        )
        sizer.Add(self.info_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.open_btn = wx.Button(self, label="Connect in Browser")
        self.open_btn.Bind(wx.EVT_BUTTON, self.on_open_auth)
        btn_row.Add(self.open_btn, 0, wx.RIGHT, 8)

        sizer.Add(btn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizer(sizer)

        self.Bind(wx.adv.EVT_WIZARD_PAGE_CHANGED, self._on_page_changed)

    def _on_page_changed(self, event):
        if event.GetPage() is self:
            wx.CallAfter(self._set_forward_enabled, False)
        event.Skip()

    def _set_forward_enabled(self, enabled: bool):
        try:
            btn = self.wizard.FindWindowById(wx.ID_FORWARD)
            if btn:
                btn.Enable(bool(enabled))
        except Exception:
            pass

    def _set_info(self, text: str):
        try:
            self.info_box.SetValue(text)
            self.info_box.SetInsertionPointEnd()
        except Exception:
            pass

    def on_open_auth(self, event):
        app_key = (getattr(self.wizard, "consumer_app_key", None) or "").strip()
        if not app_key:
            wx.MessageBox(
                "No Dropbox App Key is configured for this build.\n\n"
                "For a consumer app, the developer must embed an App Key in the application.",
                "OAuth",
                wx.OK | wx.ICON_ERROR,
            )
            self._set_info(
                "OAuth (Automatic)\r\n\r\n"
                "Status: Error - no App Key configured for this build."
            )
            return

        host = "127.0.0.1"
        port = 53682
        redirect_uri = f"http://{host}:{port}/oauth2/callback"

        try:
            flow = self.wizard._dropbox_module.DropboxOAuth2Flow(
                consumer_key=app_key,
                redirect_uri=redirect_uri,
                session=self._session,
                csrf_token_session_key=self._csrf_key,
                consumer_secret=None,
                token_access_type='offline',
                use_pkce=True,
            )
        except Exception as e:
            wx.MessageBox(f"Failed to create OAuth flow: {e}", "Error", wx.OK | wx.ICON_ERROR)
            return

        self._flow = flow

        auth_url = flow.start()

        query_params_holder = {}
        done_event = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                qs = parse_qs(parsed.query)
                query_params_holder.clear()
                for k, v in qs.items():
                    query_params_holder[k] = v[0] if isinstance(v, list) and v else v

                body = (
                    "<html><body><h2>Dropbox authorization complete.</h2>"
                    "<p>You can close this tab and return to the app.</p></body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

                done_event.set()

            def log_message(self, format, *args):
                return

        try:
            httpd = HTTPServer((host, port), Handler)
        except OSError as e:
            wx.MessageBox(
                f"Failed to start local callback server on {host}:{port}.\n\n{e}",
                "OAuth",
                wx.OK | wx.ICON_ERROR,
            )
            return

        def serve_once():
            try:
                httpd.handle_request()
            finally:
                try:
                    httpd.server_close()
                except Exception:
                    pass

        threading.Thread(target=serve_once, daemon=True).start()

        webbrowser.open(auth_url)
        self._set_info(
            "OAuth (Automatic)\r\n\r\n"
            "Browser opened. Complete authorization in the browser.\r\n\r\n"
            "Status: Waiting for authorization..."
        )
        self.Layout()

        def wait_and_finish():
            ok = done_event.wait(timeout=300)
            if not ok:
                wx.CallAfter(
                    self._set_info,
                    "OAuth (Automatic)\r\n\r\nStatus: Timed out waiting for authorization.",
                )
                return

            try:
                res = flow.finish(query_params_holder)
                refresh_token = getattr(res, 'refresh_token', None)
                if not refresh_token:
                    wx.CallAfter(
                        self._set_info,
                        "OAuth (Automatic)\r\n\r\nStatus: No refresh token returned.",
                    )
                    return

                try:
                    dbx = self.wizard._dropbox_module.Dropbox(oauth2_refresh_token=refresh_token, app_key=app_key)
                    acc = dbx.users_get_current_account()
                    display_name = getattr(getattr(acc, 'name', None), 'display_name', None) or '(unknown account)'
                except Exception:
                    display_name = '(connected)'

                self.wizard.save_oauth(app_key, refresh_token)
                self.wizard._did_replace = True
                self._oauth_ok = True
                wx.CallAfter(
                    self._set_info,
                    f"OAuth (Automatic)\r\n\r\nStatus: Connected as {display_name}.\r\n\r\nFinishing setup...",
                )
                wx.CallAfter(self.open_btn.Hide)
                wx.CallAfter(self._set_forward_enabled, True)
                wx.CallAfter(self.wizard.ShowPage, self.wizard.page_done)
            except Exception as e:
                wx.CallAfter(
                    self._set_info,
                    f"OAuth (Automatic)\r\n\r\nStatus: OAuth failed: {e}",
                )

        threading.Thread(target=wait_and_finish, daemon=True).start()

    def GetNext(self):
        if self._oauth_ok:
            return self.wizard.page_done
        return None


class _AccessTokenPage(wx.adv.WizardPageSimple):
    def __init__(self, wizard: SetupWizard):
        super().__init__(wizard)
        self.wizard = wizard

        sizer = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(self, label="Simple Connect (Access Token)")
        title.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        sizer.Add(title, 0, wx.ALL, 10)

        grid = wx.FlexGridSizer(rows=2, cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        grid.Add(wx.StaticText(self, label="Access Token:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.token_input = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.token_input.SetHint("Paste Dropbox access token")
        grid.Add(self.token_input, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Status:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.status_text = wx.StaticText(self, label="Not validated")
        grid.Add(self.status_text, 1, wx.EXPAND)

        sizer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.test_btn = wx.Button(self, label="Test Connection")
        self.test_btn.Bind(wx.EVT_BUTTON, self.on_test)
        btn_row.Add(self.test_btn, 0, wx.RIGHT, 8)

        self.save_btn = wx.Button(self, label="Save Token")
        self.save_btn.Bind(wx.EVT_BUTTON, self.on_save)
        self.save_btn.Enable(False)
        btn_row.Add(self.save_btn, 0)

        sizer.Add(btn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        help_text = wx.StaticText(
            self,
            label=(
                "Tip: You can also use Advanced OAuth in Settings later if you prefer a refresh token."
            ),
        )
        sizer.Add(help_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizer(sizer)

        self._last_validation_ok = False

        wx.CallAfter(self._set_forward_enabled, False)

    def _set_forward_enabled(self, enabled: bool):
        try:
            btn = self.wizard.FindWindowById(wx.ID_FORWARD)
            if btn:
                btn.Enable(bool(enabled))
        except Exception:
            pass

    def on_test(self, event):
        token = self.token_input.GetValue().strip()
        res = self.wizard.validate_token(token)
        if res.ok:
            self._last_validation_ok = True
            self.status_text.SetLabel(f"OK: {res.account_display_name}")
            self.save_btn.Enable(True)
            self._set_forward_enabled(False)
        else:
            self._last_validation_ok = False
            self.status_text.SetLabel(res.error_message or "Validation failed")
            self.save_btn.Enable(False)
            self._set_forward_enabled(False)

        self.Layout()

    def on_save(self, event):
        token = self.token_input.GetValue().strip()
        res = self.wizard.validate_token(token)
        if not res.ok:
            wx.MessageBox(res.error_message or "Token invalid", "Error", wx.OK | wx.ICON_ERROR)
            self.save_btn.Enable(False)
            return

        self.wizard.save_access_token(token)
        self.wizard._did_replace = True
        wx.MessageBox("Token saved. Click Next to finish.", "Saved", wx.OK | wx.ICON_INFORMATION)
        self._set_forward_enabled(True)

    def GetNext(self):
        if self.wizard._did_replace:
            return self.wizard.page_done
        return None


class _DonePage(wx.adv.WizardPageSimple):
    def __init__(self, wizard: SetupWizard):
        super().__init__(wizard)
        self.wizard = wizard
        sizer = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(self, label="Setup Complete")
        title.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        sizer.Add(title, 0, wx.ALL, 10)

        body = wx.StaticText(
            self,
            label=(
                "Dropbox connection is configured.\n\n"
                "You can now select folders in the main window and generate playlists."
            ),
        )
        sizer.Add(body, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizer(sizer)

    def GetPrev(self):
        if self.wizard._existing_auth.has_auth() and not self.wizard._did_replace:
            return self.wizard.page_connected
        return super().GetPrev()


def run_setup_wizard(parent, service_name: str, dropbox_module, consumer_app_key: str = "") -> bool:
    wiz = SetupWizard(parent, service_name, dropbox_module, consumer_app_key=consumer_app_key)
    ok = wiz.RunWizard(wiz.page_welcome)
    wiz.Destroy()
    return bool(ok)
