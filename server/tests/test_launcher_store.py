from elsewise.launcher.store import LauncherStore
from elsewise.runtime.controller import ServerStatus


def test_launcher_store_projects_lanes_without_gui_toolkit() -> None:
    store = LauncherStore(ServerStatus("stopped", url="http://127.0.0.1:38473"))
    store.apply_lifecycle(ServerStatus("running", pid=42))

    notified = store.apply_runtime(
        {
            "sources": [
                {
                    "role": "remote",
                    "binding_state": "degraded",
                    "requested_mode": "auto",
                    "effective_mode": "captions",
                    "source_kind": "browser_captions",
                    "health_status": "degraded",
                    "connected": True,
                    "reason": "fallback_activated",
                },
                {
                    "role": "self",
                    "binding_state": "active",
                    "requested_mode": "auto",
                    "effective_mode": "native",
                    "source_kind": "native_microphone",
                    "health_status": "available",
                    "connected": True,
                },
            ]
        },
        observed_at=1.0,
    )

    assert notified is True
    assert store.state.lifecycle.state == "running"
    assert [lane.role for lane in store.state.lanes] == ["remote", "self"]
    assert store.state.lanes[0].reason == "fallback_activated"


def test_launcher_store_coalesces_metric_only_updates() -> None:
    store = LauncherStore(ServerStatus("running"), metric_notification_interval_seconds=1.0)
    assert store.apply_runtime(
        {"server": {"status": "running"}, "metrics": {"rtf": 0.2}}, observed_at=1.0
    )
    revision = store.state.revision
    assert not store.apply_runtime(
        {"server": {"status": "running"}, "metrics": {"rtf": 0.3}},
        observed_at=1.1,
    )
    assert store.state.runtime_payload["metrics"] == {"rtf": 0.3}
    assert store.state.revision == revision
    assert store.apply_runtime(
        {"server": {"status": "running"}, "metrics": {"rtf": 0.4}},
        observed_at=2.1,
    )


def test_launcher_store_tracks_action_state_independently_of_widgets() -> None:
    store = LauncherStore(ServerStatus("stopped"))
    store.begin_action("start")
    assert store.state.pending_action == "start"
    assert store.finish_action() == "start"
    assert store.state.pending_action == ""
