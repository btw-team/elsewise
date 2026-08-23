import queue
import threading
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from elsewise.external_links import load_external_links, manifest_path
from elsewise.launcher.app import (
    _DEFAULT_WINDOW_GEOMETRY,
    _MAX_EVENTS_PER_TICK,
    _MINIMUM_WINDOW_SIZE,
    LauncherApplication,
)
from elsewise.launcher.assets import asset_path
from elsewise.launcher.i18n import CATALOGS, Translator
from elsewise.launcher.overview import OverviewFrame
from elsewise.launcher.settings_view import SettingsFrame
from elsewise.launcher.single_instance import LauncherSingleInstance
from elsewise.launcher.theme import THEMES, TOKENS, set_theme
from elsewise.settings.config import SettingsStore
from elsewise.settings.pairing import PairingManager


def test_launcher_catalogs_have_baseline_parity_and_english_fallback() -> None:
    expected = set(CATALOGS["en"])
    assert set(CATALOGS) == {"en", "ru", "fr", "es", "de", "pt-BR"}
    assert all(set(catalog) == expected for catalog in CATALOGS.values())
    assert Translator("unsupported").text("overview") == "Overview"
    assert Translator("fr").text("details") == "Détails"
    assert Translator("de").text("settings") == "Einstellungen"


def test_launcher_theme_contains_required_semantic_tokens() -> None:
    set_theme("dark")
    assert TOKENS.canvas == "#1b2229"
    assert TOKENS.accent == "#03b8e9"
    assert TOKENS.accent_strong == "#17d3cf"
    assert TOKENS.danger == "#ff858d"
    assert TOKENS.success == "#70d89d"
    set_theme("light")
    assert TOKENS.canvas == "#f7fafb"
    assert TOKENS.accent == "#038ab3"
    assert TOKENS.accent_strong == "#09bfbd"
    assert set(THEMES["dark"]) == set(THEMES["light"])
    set_theme("dark")


def test_launcher_opens_at_its_supported_minimum_size() -> None:
    assert _DEFAULT_WINDOW_GEOMETRY == "1024x640"
    assert _MINIMUM_WINDOW_SIZE == (1024, 640)


def test_settings_helpers_do_not_shadow_customtkinter_widget_attributes() -> None:
    assert "_label" not in SettingsFrame.__dict__
    assert "_add_field_label" in SettingsFrame.__dict__


def test_launcher_pairing_actions_share_and_persist_one_token(tmp_path: Path) -> None:
    class Variable:
        def __init__(self, value: str) -> None:
            self.value = value

        def get(self) -> str:
            return self.value

        def set(self, value: str) -> None:
            self.value = value

    class Feedback:
        def __init__(self) -> None:
            self.changes: dict[str, object] = {}

        def configure(self, **changes: object) -> None:
            self.changes.update(changes)

    manager = PairingManager(tmp_path / "pairing.json")
    manager.ensure()
    initial = manager.token()
    frame: Any = object.__new__(SettingsFrame)
    frame.translator = Translator("en")
    frame.pairing = manager
    frame.pairing_token_var = Variable("manual-launcher-pairing-token")
    frame.feedback = Feedback()
    frame.after = lambda _delay, _callback: None
    clipboard: list[str] = []
    frame.clipboard_clear = clipboard.clear
    frame.clipboard_append = clipboard.append

    frame._save_pairing_token()
    assert manager.token() == "manual-launcher-pairing-token"
    assert frame.feedback.changes["text"] == "Pairing token saved."

    frame._copy_pairing_token()
    assert clipboard == ["manual-launcher-pairing-token"]

    frame._regenerate_pairing_token()
    assert manager.token() == frame.pairing_token_var.get()
    assert manager.token() not in {initial, "manual-launcher-pairing-token"}


def test_launcher_rejects_an_invalid_manual_pairing_token(tmp_path: Path) -> None:
    class Variable:
        def get(self) -> str:
            return "short"

    class Feedback:
        def __init__(self) -> None:
            self.changes: dict[str, object] = {}

        def configure(self, **changes: object) -> None:
            self.changes.update(changes)

    manager = PairingManager(tmp_path / "pairing.json")
    manager.ensure()
    original = manager.token()
    frame: Any = object.__new__(SettingsFrame)
    frame.translator = Translator("en")
    frame.pairing = manager
    frame.pairing_token_var = Variable()
    frame.feedback = Feedback()
    frame.after = lambda _delay, _callback: None

    frame._save_pairing_token()

    assert manager.token() == original
    assert frame.feedback.changes == {
        "text": "Enter a token containing 16 to 4096 characters.",
        "text_color": TOKENS.danger,
    }


def test_tab_navigation_maps_only_the_selected_frame() -> None:
    class Frame:
        def __init__(self) -> None:
            self.visible = False

        def grid(self) -> None:
            self.visible = True

        def grid_remove(self) -> None:
            self.visible = False

    class Button:
        def configure(self, **_changes: object) -> None:
            pass

    application = object.__new__(LauncherApplication)
    application._tabs = {name: Frame() for name in ("overview", "details", "settings", "about")}
    application._tab_buttons = {name: Button() for name in application._tabs}
    application._loading_frame = Frame()
    application._active_tab = "overview"

    application.show_tab("settings")

    assert application._active_tab == "settings"
    assert [name for name, frame in application._tabs.items() if frame.visible] == ["settings"]


def test_unbuilt_launcher_tab_is_created_only_after_it_is_selected() -> None:
    class Frame:
        def __init__(self) -> None:
            self.visible = False

        def grid(self) -> None:
            self.visible = True

        def grid_remove(self) -> None:
            self.visible = False

    class Widget:
        def configure(self, **_changes: object) -> None:
            pass

    application: Any = object.__new__(LauncherApplication)
    overview = Frame()
    loading = Frame()
    application._tabs = {"overview": overview}
    application._tab_buttons = {
        name: Widget() for name in ("overview", "details", "settings", "about")
    }
    application._loading_frame = loading
    application._loading_title = Widget()
    application._loading_message = Widget()
    application._tab_build_pending = set()
    application._build_generation = 3
    application._active_tab = "overview"
    application.translator = Translator("en")
    application.closed = False
    scheduled: list[tuple[int, Any]] = []
    application.after = lambda delay, callback: scheduled.append((delay, callback))
    details = Frame()

    def create(key: str) -> Frame:
        assert key == "details"
        application._tabs[key] = details
        return details

    application._create_lazy_tab = create

    application.show_tab("details")

    assert overview.visible is False
    assert loading.visible is True
    assert application._tab_build_pending == {"details"}
    assert len(scheduled) == 1
    scheduled[0][1]()
    assert details.visible is True
    assert loading.visible is False
    assert application._tab_build_pending == set()


def test_disabled_primary_button_uses_muted_readable_style() -> None:
    class Button:
        def __init__(self) -> None:
            self.changes: dict[str, object] = {}

        def configure(self, **changes: object) -> None:
            self.changes.update(changes)

    button: Any = Button()

    OverviewFrame._set_button_state(button, enabled=False, primary=True)

    assert button.changes["state"] == "disabled"
    assert button.changes["fg_color"] == TOKENS.surface
    assert button.changes["text_color_disabled"] == TOKENS.text_faint


def test_agent_health_labels_are_localized_next_to_provider_names() -> None:
    overview: Any = object.__new__(OverviewFrame)
    overview.translator = Translator("ru")

    assert overview._agent_status_text("ready") == "Готов"
    assert overview._agent_status_text("unavailable") == "Недоступен"
    assert overview._agent_status_text("starting") == "Starting"


def test_card_button_row_has_equal_columns_and_sixteen_pixel_gaps() -> None:
    class Master:
        def __init__(self) -> None:
            self.columns: dict[int, int] = {}

        def grid_columnconfigure(self, column: int, *, weight: int) -> None:
            self.columns[column] = weight

    class Button:
        def __init__(self) -> None:
            self.grid_options: dict[str, object] = {}

        def grid(self, **options: object) -> None:
            self.grid_options = options

    master: Any = Master()
    buttons: Any = (Button(), Button(), Button())

    OverviewFrame._grid_button_row(master, buttons)

    assert master.columns == {0: 1, 1: 1, 2: 1}
    assert [button.grid_options["padx"] for button in buttons] == [
        (0, 8),
        (8, 8),
        (8, 0),
    ]
    assert all(button.grid_options["sticky"] == "ew" for button in buttons)


def test_mouse_wheel_scrolls_and_repaints_only_the_active_scrollable_tab() -> None:
    class Canvas:
        def __init__(self) -> None:
            self.scrolls: list[tuple[int, str]] = []
            self.repainted = False

        def yview_scroll(self, units: int, mode: str) -> None:
            self.scrolls.append((units, mode))

        def update_idletasks(self) -> None:
            self.repainted = True

        def after_idle(self, callback: Any) -> None:
            callback()

    class Frame:
        def __init__(self) -> None:
            self._parent_canvas = Canvas()

        @staticmethod
        def check_if_master_is_canvas(widget: object) -> bool:
            return widget == "active-content"

    class Event:
        widget = "active-content"
        num = 5
        delta = 0

    application = object.__new__(LauncherApplication)
    application._active_tab = "overview"
    application._tabs = {"overview": Frame(), "details": object()}

    result = application._scroll_active_tab(Event())

    canvas = application._tabs["overview"]._parent_canvas
    assert result == "break"
    assert canvas.scrolls == [(3, "units")]
    assert canvas.repainted is True


def test_launcher_event_drain_yields_to_tk_when_a_producer_floods() -> None:
    application: Any = object.__new__(LauncherApplication)
    application.event_queue = queue.SimpleQueue()
    for _ in range(_MAX_EVENTS_PER_TICK + 25):
        application.event_queue.put({"kind": "noop"})
    scheduled: list[int] = []
    application.after = lambda delay, _callback: scheduled.append(delay)

    application._drain_event_queue()

    assert application.event_queue.qsize() == 25
    assert scheduled == [10]


def test_launcher_theme_change_uses_locked_settings_file_when_server_is_stopped(
    tmp_path: Path,
) -> None:
    application: Any = object.__new__(LauncherApplication)
    application.paths = SimpleNamespace(config=tmp_path)
    application.current_status = SimpleNamespace(state="stopped", url=None)

    application._save_global_settings({"ui_theme": "light"})

    assert SettingsStore(tmp_path / "settings.json").load().ui_theme == "light"


def test_launcher_runtime_theme_update_uses_the_shared_interface_rebuild() -> None:
    class Overview:
        def set_runtime(self, _payload: dict[str, object]) -> None:
            pass

    application: Any = object.__new__(LauncherApplication)
    application.event_queue = queue.SimpleQueue()
    application.event_queue.put(
        {
            "kind": "runtime",
            "payload": {"settings": {"ui_language": "en", "ui_theme": "light"}},
        }
    )
    application.runtime_payload = {}
    application.overview = Overview()
    application.translator = Translator("en")
    application.ui_theme = "dark"
    applied: list[tuple[str, str]] = []
    application._apply_interface_settings = lambda language, theme: applied.append(
        (language, theme)
    )
    application.after = lambda _delay, _callback: None

    application._drain_event_queue()

    assert applied == [("en", "light")]


def test_log_events_are_buffered_until_details_tab_is_built() -> None:
    application: Any = object.__new__(LauncherApplication)
    application.event_queue = queue.SimpleQueue()
    application.event_queue.put({"kind": "log", "lines": ["first\n", "second\n"], "reset": True})
    application.details = None
    application._deferred_log_lines = deque(maxlen=1000)
    application.after = lambda _delay, _callback: None

    application._drain_event_queue()

    assert list(application._deferred_log_lines) == ["first\n", "second\n"]


def test_launcher_final_close_is_bounded_and_idempotent() -> None:
    class Stoppable:
        def __init__(self) -> None:
            self.calls = 0

        def stop(self) -> None:
            self.calls += 1

    class Instance:
        def __init__(self) -> None:
            self.calls = 0

        def close(self) -> None:
            self.calls += 1

    application: Any = object.__new__(LauncherApplication)
    application.closed = False
    application.closing = False
    application.restart_waiting = False
    application.restart_cancel = threading.Event()
    application.monitor = Stoppable()
    application.log_worker = Stoppable()
    application.instance = Instance()
    quit_calls: list[bool] = []
    application.quit = lambda: quit_calls.append(True)

    application._final_close()
    application._final_close()

    assert application.closed is True
    assert application.closing is True
    assert application.monitor.calls == 1
    assert application.log_worker.calls == 1
    assert application.instance.calls == 1
    assert quit_calls == [True]


def test_launcher_logo_uses_project_asset() -> None:
    for name in ("elsewise-logo-dark.png", "elsewise-logo-light.png"):
        logo = asset_path(name)
        assert logo is not None
        assert "extra" not in logo.parts


def test_external_link_manifest_is_shared_project_data() -> None:
    links = load_external_links()
    assert manifest_path().parts[-2:] == ("shared", "external-links.json")
    assert links["project"] == "https://github.com/btw-team/elsewise"
    assert links["chrome_store"].startswith("https://")


def test_second_launcher_signals_existing_instance(tmp_path: Path) -> None:
    activated = threading.Event()
    first = LauncherSingleInstance(tmp_path)
    second = LauncherSingleInstance(tmp_path)
    third = LauncherSingleInstance(tmp_path)
    assert first.acquire() is True
    first.start_listener(activated.set)
    try:
        assert second.acquire() is False
        assert second.notify_existing() is True
        assert activated.wait(timeout=2)
    finally:
        first.close()
    try:
        assert third.acquire() is True
    finally:
        third.close()
