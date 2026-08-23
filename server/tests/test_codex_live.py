import os
from pathlib import Path

import pytest
from elsewise.agents.app_server import CodexAppServerProvider
from elsewise.agents.interface import PermissionConfig, RunConfig, ThreadConfig


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("ELSEWISE_RUN_CODEX_LIVE") != "1",
    reason="set ELSEWISE_RUN_CODEX_LIVE=1 for the authenticated Codex smoke",
)
async def test_live_codex_create_warm_and_resume_thread(tmp_path: Path) -> None:
    permissions = PermissionConfig(allow_workspace_write=False, allow_network=False)
    thread_config = ThreadConfig(cwd=str(tmp_path), permissions=permissions)
    run_config = RunConfig(
        cwd=str(tmp_path), permissions=permissions, inactivity_timeout_seconds=120
    )

    first_provider = CodexAppServerProvider(startup_timeout=20)
    await first_provider.start()
    thread_id = await first_provider.create_thread(thread_config)
    first_events = [
        event
        async for event in first_provider.run_turn(
            thread_id,
            "This is a transport smoke test. Reply with exactly: ELSEWISE_READY",
            run_config,
        )
    ]
    await first_provider.stop()

    assert thread_id
    assert first_events[-1].kind == "completed"
    assert "ELSEWISE_READY" in "".join(event.text for event in first_events)

    resumed_provider = CodexAppServerProvider(startup_timeout=20)
    await resumed_provider.start()
    await resumed_provider.resume_thread(thread_id, thread_config)
    resumed_events = [
        event
        async for event in resumed_provider.run_turn(
            thread_id,
            "Reply with exactly: ELSEWISE_RESUMED",
            run_config,
        )
    ]
    await resumed_provider.stop()

    assert resumed_events[-1].kind == "completed"
    assert "ELSEWISE_RESUMED" in "".join(event.text for event in resumed_events)
