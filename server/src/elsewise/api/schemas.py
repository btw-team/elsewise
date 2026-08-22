from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from elsewise.settings.languages import SupportedLanguage


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=512)
    description: str = Field(default="", max_length=20_000)
    language: SupportedLanguage | None = None
    initial_prompt: str | None = Field(default=None, max_length=20_000)
    action_preset_id: str | None = Field(default=None, max_length=36)
    agent_provider: str | None = Field(default=None, max_length=32)
    agent_model: str | None = Field(default=None, max_length=128)
    agent_reasoning_effort: str | None = Field(default=None, max_length=32)
    requested_agent_cwd: str | None = Field(default=None, max_length=4096)
    create_agent_cwd: bool = False
    allow_workspace_write: bool | None = None
    allow_network: bool | None = None


class SessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)
    language: SupportedLanguage | None = None
    initial_prompt: str | None = Field(default=None, max_length=20_000)
    action_preset_id: str | None = Field(default=None, max_length=36)
    agent_provider: str | None = Field(default=None, max_length=32)
    agent_model: str | None = Field(default=None, max_length=128)
    agent_reasoning_effort: str | None = Field(default=None, max_length=32)
    requested_agent_cwd: str | None = Field(default=None, max_length=4096)
    create_agent_cwd: bool = False
    allow_workspace_write: bool | None = None
    allow_network: bool | None = None


class AgentActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    button_id: str | None = Field(default=None, min_length=1, max_length=64)
    prompt: str | None = Field(default=None, min_length=1, max_length=20_000)

    @model_validator(mode="after")
    def validate_action_source(self) -> "AgentActionCreate":
        if (self.button_id is None) == (self.prompt is None):
            raise ValueError("Provide exactly one of button_id or prompt.")
        if self.prompt is not None and not self.prompt.strip():
            raise ValueError("Prompt must not be blank.")
        return self


class ButtonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[a-z0-9_-]+$")
    enabled: bool = True
    label: str = Field(min_length=1, max_length=128)
    prompt_template: str = Field(min_length=1, max_length=20_000)
    context_strategy: Literal["since_previous_turn", "last_minutes", "last_utterances", "all"] = (
        "since_previous_turn"
    )
    context_value: int | None = Field(default=5, ge=1, le=100_000)
    hard_character_cap: int = Field(default=50_000, ge=1_000, le=200_000)


class ButtonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[a-z0-9_-]+$")
    enabled: bool | None = None
    label: str | None = Field(default=None, min_length=1, max_length=128)
    prompt_template: str | None = Field(default=None, min_length=1, max_length=20_000)
    context_strategy: (
        Literal["since_previous_turn", "last_minutes", "last_utterances", "all"] | None
    ) = None
    context_value: int | None = Field(default=None, ge=1, le=100_000)
    hard_character_cap: int | None = Field(default=None, ge=1_000, le=200_000)


class ActionPresetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    button_ids: list[str] = Field(default_factory=list, max_length=12)


class ActionPresetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    button_ids: list[str] | None = Field(default=None, max_length=12)


class GlobalSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ui_language: SupportedLanguage | None = None
    default_meeting_language: SupportedLanguage | None = None
    default_agent_provider: str | None = Field(default=None, max_length=32)
    default_agent_model: str | None = Field(default=None, max_length=128)
    default_agent_reasoning_effort: str | None = Field(default=None, max_length=32)
    codex_executable: str | None = Field(default=None, min_length=1, max_length=4096)
    claude_executable: str | None = Field(default=None, min_length=1, max_length=4096)
    initial_prompts: dict[str, str] | None = None
    free_prompt_context_strategy: (
        Literal["since_previous_turn", "last_minutes", "last_utterances", "all"] | None
    ) = None
    free_prompt_context_value: int | None = Field(default=None, ge=1, le=100_000)
    free_prompt_hard_character_cap: int | None = Field(default=None, ge=1_000, le=200_000)
    google_meet_own_name: str | None = Field(default=None, max_length=512)
    microsoft_teams_own_name: str | None = Field(default=None, max_length=512)
    zoom_own_name: str | None = Field(default=None, max_length=512)
    default_allow_workspace_write: bool | None = None
    default_allow_network: bool | None = None


class PairingTokenUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    token: str = Field(min_length=16, max_length=4096)
