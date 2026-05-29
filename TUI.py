from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Input, DataTable


# ─────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────

def get_networks_snapshot(state):
    lock = state.get("lock")

    if lock:
        with lock:
            return [net.copy() for net in state.get("networks", [])]

    return [net.copy() for net in state.get("networks", [])]


def get_crack_snapshot(state):
    lock = state.get("lock")

    if lock:
        with lock:
            return {
                "cracking": state.get("cracking", False),
                "target_id": state.get("crack_target_id"),
                "wordlist": state.get("crack_wordlist"),
                "status": state.get("crack_status", "Idle"),
                "password": state.get("crack_password"),
            }

    return {
        "cracking": state.get("cracking", False),
        "target_id": state.get("crack_target_id"),
        "wordlist": state.get("crack_wordlist"),
        "status": state.get("crack_status", "Idle"),
        "password": state.get("crack_password"),
    }


def make_network_signature(networks):
    return tuple(
        (
            str(net.get("id", "")),
            str(net.get("bssid", "")),
            str(net.get("essid", "")),
            str(net.get("enc", "")),
        )
        for net in networks
    )


def short_path(path, max_len=28):
    if not path:
        return "None"

    path = str(path)

    if len(path) <= max_len:
        return path

    return "…" + path[-(max_len - 1):]


def build_info_markup(
    iface,
    is_filter,
    is_monitor,
    network_count=0,
    crack=None,
    input_mode="COMMAND",
    pending_target_id=None,
    saved_wordlist=None,
):
    if crack is None:
        crack = {}

    filter_color = "bright_magenta" if is_filter else "bright_black"
    monitor_color = "#00ffcc" if is_monitor else "bright_black"
    status_icon = "◉" if is_monitor else "◎"

    cracking = crack.get("cracking", False)
    crack_status = crack.get("status", "Idle")
    crack_target_id = crack.get("target_id")
    crack_wordlist = crack.get("wordlist")
    crack_password = crack.get("password")

    if crack_status == "Saved to pass.txt":
        status_line = "[bold #00ff88]Saved to pass.txt[/bold #00ff88]"
    elif crack_password:
        status_line = f"[bold #00ff88]FOUND[/bold #00ff88] [#00ff88]{crack_password}[/#00ff88]"
    elif cracking:
        status_line = "[bold #ff2d78]Cracking...[/bold #ff2d78]"
    else:
        status_line = f"[dim]{crack_status}[/dim]"

    if input_mode == "NEW_WORDLIST":
        mode_line = "[#ff2d78]Waiting new wordlist path...[/#ff2d78]"
    elif input_mode == "WORDLIST":
        mode_line = "[#ff2d78]Waiting wordlist path...[/#ff2d78]"
    elif input_mode == "TARGET_ID":
        mode_line = "[#ff2d78]Waiting target ID...[/#ff2d78]"
    else:
        mode_line = "[dim]Ready[/dim]"

    return (
        f"[bold #00ffcc]▸ INTERFACE[/bold #00ffcc] "
        f"[white]{iface}[/white]\n\n"

        f"[bold #00ffcc]▸ FILTER[/bold #00ffcc] "
        f"[{filter_color}]{is_filter}[/{filter_color}]\n\n"

        f"[bold #00ffcc]▸ MONITOR[/bold #00ffcc] "
        f"[{monitor_color}]{status_icon} {is_monitor}[/{monitor_color}]\n\n"

        f"[bold #00ffcc]▸ NETWORKS[/bold #00ffcc] "
        f"[bold #ff2d78]{network_count}[/bold #ff2d78] [dim]detected[/dim]\n\n"

        f"[bold dim]──────────────────────────────────[/bold dim]\n\n"

        f"[bold #00ffcc]▸ COMMAND[/bold #00ffcc]\n"
        f"  [#ff2d78]new[/#ff2d78]   [dim]set wordlist[/dim]\n"
        f"  [#ff2d78]crack[/#ff2d78] [dim]start crack[/dim]\n"
        f"  [#ff2d78]out[/#ff2d78]   [dim]save pass.txt[/dim]\n"
        f"  [#ff2d78]stop[/#ff2d78]  [dim]stop crack[/dim]\n\n"

        f"[bold #00ffcc]▸ INPUT[/bold #00ffcc]\n"
        f"  {mode_line}\n\n"

        f"[bold #00ffcc]▸ CRACK[/bold #00ffcc]\n"
        f"  {status_line}\n"
        f"  [dim]id:[/dim] [#c8fff4]{crack_target_id or pending_target_id or 'None'}[/#c8fff4]\n"
        f"  [dim]wordlist:[/dim] [#c8fff4]{short_path(crack_wordlist)}[/#c8fff4]\n"
        f"  [dim]saved:[/dim] [#c8fff4]{short_path(saved_wordlist)}[/#c8fff4]\n"
        f"  [dim]password:[/dim] [#00ff88]{crack_password or 'None'}[/#00ff88]\n"
    )


# ─────────────────────────────────────────────────────────────
#  App handle
# ─────────────────────────────────────────────────────────────

class TextualAppHandle:
    def __init__(self, app):
        self.app = app

    def invalidate(self):
        try:
            self.app.call_from_thread(self.app.refresh_networks)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
#  TUI App
# ─────────────────────────────────────────────────────────────

class WifiTUI(App):
    CSS = """
    Screen {
        background: #020008;
        color: #c8fff4;
        layers: base;
    }

    #topbar-wrap {
        height: 3;
        width: 100%;
        background: #020008;
        border-bottom: heavy #00ffcc22;
    }

    #topbar {
        width: 1fr;
        height: 3;
        background: #020008;
        color: #00ffcc;
        padding: 1 3;
        content-align: left middle;
    }

    #topbar-right {
        width: 16;
        height: 3;
        background: #020008;
        color: #ff2d78;
        padding: 1 2;
        content-align: right middle;
    }

    #footbar {
        height: 1;
        width: 100%;
        background: #00ffcc08;
        color: #444455;
        padding: 0 3;
        dock: bottom;
        border-top: solid #00ffcc18;
    }

    #main {
        height: 1fr;
        width: 100%;
        background: #020008;
    }

    #left {
        width: 45;
        height: 100%;
        background: #04000e;
        border-right: heavy #00ffcc18;
    }

    #left-heading {
        height: 2;
        background: #04000e;
        color: #00ffcc;
        padding: 0 2;
        border-bottom: solid #00ffcc22;
        content-align: left middle;
    }

    #info {
        height: 1fr;
        padding: 1 2;
        color: #c8fff4;
        background: #04000e;
    }

    #input-heading {
        height: 2;
        background: #04000e;
        color: #00ffcc;
        padding: 0 2;
        border-top: solid #00ffcc22;
        content-align: left middle;
    }

    #cmd {
        height: 3;
        margin: 1 1 1 1;
        color: #ff2d78;
        background: #0a0018;
        border: tall #ff2d7840;
    }

    #cmd:focus {
        border: tall #ff2d78aa;
    }

    #right {
        width: 1fr;
        height: 100%;
        background: #020008;
    }

    #right-heading {
        height: 2;
        background: #020008;
        color: #ff2d78;
        padding: 0 3;
        border-bottom: solid #ff2d7830;
        content-align: left middle;
    }

    #networks {
        height: 1fr;
        width: 1fr;
        background: #020008;
        color: #c8fff4;
        overflow-x: auto;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
        scrollbar-background: #04000e;
        scrollbar-color: #00ffcc33;
        scrollbar-color-hover: #00ffcc88;
        scrollbar-color-active: #00ffcccc;
        scrollbar-corner-color: #04000e;
    }

    DataTable {
        background: #020008;
        color: #c8fff4;
    }

    DataTable > .datatable--header {
        background: #07001c;
        color: #00ffcc;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #ff2d7818;
        color: #ff88b0;
        text-style: bold;
    }

    DataTable > .datatable--hover {
        background: #00ffcc0c;
    }

    DataTable > .datatable--fixed {
        background: #07001c;
        color: #00ffcc;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit_app", "Quit"),
    ]

    def __init__(self, state, iface, is_filter, is_monitor, quit_callback):
        super().__init__()

        self.state = state
        self.iface = iface
        self.is_filter = is_filter
        self.is_monitor = is_monitor
        self.quit_callback = quit_callback

        self.info_widget = None
        self.input_widget = None
        self.table = None
        self.topbar_right = None

        self.last_network_signature = None

        self.input_mode = "COMMAND"
        self.pending_wordlist = None
        self.pending_target_id = None
        self.saved_wordlist = None

        
    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar-wrap"):
            yield Static(
                "⬡  [bold]WIFI MONITOR[/bold]  [dim]v2.4[/dim]   [dim]──[/dim]   [dim]passive scan[/dim]",
                id="topbar",
            )
            yield Static(
                "[blink]● Live[/blink]",
                id="topbar-right",
            )

        yield Static(
            "[#ff2d78]^C[/#ff2d78] quit    "
            "[#ff2d78]crack[/#ff2d78] start    "
            "[#ff2d78]stop[/#ff2d78] stop    "
            "[#ff2d78]out[/#ff2d78] save    "
            "[#ff2d78]new[/#ff2d78] wordlist    "
            "[dim]──[/dim]    "
            "[dim]interval: 1s[/dim]",
            id="footbar",
        )

        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Static("  [bold]◈  STATUS[/bold]", id="left-heading")
                yield Static(
                    build_info_markup(
                        self.iface,
                        self.is_filter,
                        self.is_monitor,
                        0,
                        get_crack_snapshot(self.state),
                        self.input_mode,
                        self.pending_target_id,
                        self.saved_wordlist,
                    ),
                    id="info",
                )

                yield Static("  [bold]◈  COMMAND[/bold]", id="input-heading")
                yield Input(placeholder="› type command…", id="cmd")

            with Vertical(id="right"):
                yield Static(
                    "  [bold]◈  DETECTED NETWORKS[/bold]",
                    id="right-heading",
                )
                yield DataTable(id="networks")

    def on_mount(self):
        self.info_widget = self.query_one("#info", Static)
        self.input_widget = self.query_one("#cmd", Input)
        self.table = self.query_one("#networks", DataTable)
        self.topbar_right = self.query_one("#topbar-right", Static)

        self.table.cursor_type = "row"
        self.table.zebra_stripes = False

        self.table.add_column("ID ", width=5)
        self.table.add_column("BSSID", width=22)
        self.table.add_column("ESSID", width=36)
        self.table.add_column("ENCRYPTION", width=30)

        self.refresh_networks()

        self.set_interval(1, self.refresh_networks)
        self.set_interval(0.5, self.refresh_info_panel)

    def refresh_info_panel(self):
        networks = get_networks_snapshot(self.state)
        crack = get_crack_snapshot(self.state)

        if self.info_widget:
            self.info_widget.update(
                build_info_markup(
                    self.iface,
                    self.is_filter,
                    self.is_monitor,
                    len(networks),
                    crack,
                    self.input_mode,
                    self.pending_target_id,
                    self.saved_wordlist,
                )
            )

        if self.topbar_right:
            if crack.get("cracking"):
                self.topbar_right.update("[blink]●[/blink] CRACK")
            else:
                self.topbar_right.update("[blink]● LIVE[/blink] ")

    def refresh_networks(self):
        networks = get_networks_snapshot(self.state)

        self.refresh_info_panel()

        if not self.table:
            return

        signature = make_network_signature(networks)

        if signature == self.last_network_signature:
            return

        self.last_network_signature = signature

        old_scroll_y = self.table.scroll_y
        old_scroll_x = self.table.scroll_x

        try:
            old_cursor = self.table.cursor_coordinate
            old_cursor_row = old_cursor.row
            old_cursor_column = old_cursor.column
        except Exception:
            old_cursor_row = 0
            old_cursor_column = 0

        self.table.clear(columns=False)

        if not networks:
            self.table.add_row("", "", "[dim]Waiting for networks…[/dim]", "")
        else:
            for net in networks:
                net_id = str(net.get("id", ""))
                bssid = str(net.get("bssid", ""))
                essid = str(net.get("essid", ""))
                enc = str(net.get("enc", ""))

                self.table.add_row(net_id, bssid, essid, enc)

        def restore_position():
            try:
                self.table.scroll_to(
                    x=old_scroll_x,
                    y=old_scroll_y,
                    animate=False,
                )
            except Exception:
                pass

            try:
                row_count = len(networks) if networks else 1
                safe_row = min(old_cursor_row, row_count - 1)

                self.table.move_cursor(
                    row=safe_row,
                    column=old_cursor_column,
                    animate=False,
                )
            except Exception:
                pass

        self.call_after_refresh(restore_position)

    def reset_command_mode(self):
        self.input_mode = "COMMAND"
        self.pending_wordlist = None
        self.pending_target_id = None

        if self.input_widget:
            self.input_widget.placeholder = "› type command…"

        self.refresh_info_panel()

    def on_input_submitted(self, event: Input.Submitted):
        cmd = event.value.strip()
        event.input.value = ""

        low = cmd.lower()

        if low == "stop":
            stop_func = self.state.get("stop_crack")

            if stop_func:
                stop_func()

            self.reset_command_mode()
            return

        if low == "out":
            save_func = self.state.get("save_password")

            if save_func:
                save_func()

            self.refresh_info_panel()
            return

        if low == "new":
            self.input_mode = "NEW_WORDLIST"
            self.pending_wordlist = None
            self.pending_target_id = None
            self.input_widget.placeholder = "› enter new wordlist path…"
            self.refresh_info_panel()
            return

        if self.input_mode == "NEW_WORDLIST":
            if not cmd:
                self.input_widget.placeholder = "› wordlist path cannot be empty…"
                return

            self.saved_wordlist = cmd
            self.pending_wordlist = cmd
            self.input_mode = "COMMAND"
            self.input_widget.placeholder = "› type command…"
            self.refresh_info_panel()
            return

        if self.input_mode == "WORDLIST":
            if not cmd:
                self.input_widget.placeholder = "› wordlist path cannot be empty…"
                return
    
            self.saved_wordlist = cmd
            self.pending_wordlist = cmd
    
            start_func = self.state.get("start_crack")
            if start_func:
                start_func(self.pending_wordlist)
    
            self.input_mode = "TARGET_ID"
            self.input_widget.placeholder = "› enter target network ID…"
    
            self.refresh_info_panel()
            return
    
        if self.input_mode == "TARGET_ID":
            if not cmd:
                self.input_widget.placeholder = "› target id cannot be empty…"
                return
    
            self.pending_target_id = cmd
    
            send_id_func = self.state.get("send_crack_id")
            if send_id_func:
                send_id_func(self.pending_target_id)
    
            self.reset_command_mode()
            return
    
        if low == "crack":
            if self.saved_wordlist:
                self.pending_wordlist = self.saved_wordlist
    
                start_func = self.state.get("start_crack")
                if start_func:
                    start_func(self.pending_wordlist)
    
                self.input_mode = "TARGET_ID"
                self.input_widget.placeholder = "› enter target network ID…"
                self.refresh_info_panel()
                return
    
            self.input_mode = "WORDLIST"
            self.pending_wordlist = None
            self.pending_target_id = None
            self.input_widget.placeholder = "› enter wordlist path…"
            self.refresh_info_panel()
            return
    
        self.refresh_networks()

    def action_quit_app(self):
        try:
            self.quit_callback()
        finally:
            self.exit()


# ─────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────

def run_tui(state, iface, is_filter, is_monitor, quit_callback):
    app = WifiTUI(
        state=state,
        iface=iface,
        is_filter=is_filter,
        is_monitor=is_monitor,
        quit_callback=quit_callback,
    )

    state["app"] = TextualAppHandle(app)

    try:
        app.run()
    finally:
        state["app"] = None