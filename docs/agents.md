# Codex and Claude Code

Elsewise supports locally installed Codex and Claude Code CLIs. Authentication,
model access, billing, and provider account limits remain the user's responsibility.

## Discovery and authentication

The launcher shows each discovered executable and its resolved path. Web GUI
Settings can override the command or absolute path. Useful checks are:

```bash
codex --version
codex login status
claude --version
claude auth status
```

Claude Desktop alone may not provide the separate `claude` terminal command.
Recording and export continue when either or both agents are unavailable.

## Provider, model, and effort

Global settings seed new sessions. The provider is locked after first start; model
and effort can be edited while the session is stopped. If no model is selected, the
CLI's own default applies. There is no automatic provider fallback because Codex
and Claude histories are not interchangeable.

## Initial warm-up and working directory

First start sends the session's initial prompt and asks the agent to inspect only
relevant text documentation and configuration in the working directory. It must not
scan dependencies, binaries, large directories, or potential secrets, and may not
change files during warm-up.

The directory can provide session-specific background such as information about
the user, project, other participants, reference documents, terminology, goals, and
constraints. Keep it focused and free of credentials or unrelated sensitive data.
The agent is instructed to treat anything it reads as context rather than as
unconditionally trusted instructions.

Elsewise validates and resolves the requested directory. A missing directory can
be created only after explicit confirmation. An absent or unusable optional path
falls back to a safe empty runtime directory, visibly marked in the Agent header.

## Permissions

Defaults are read-only workspace and no agent-tool network access. A session may
explicitly allow writes restricted to the resolved working directory and/or
network-capable tools and sandboxed command traffic.

The provider's own connection to its model service is required and is not disabled
by the session network flag. A mandatory sandbox failure stops the run instead of
weakening restrictions.

## Timeouts and cancellation

Provider inactivity is limited to five minutes. Total limits are fifteen minutes
for initial warm-up and ten minutes for actions/free prompts. A total timeout keeps
received partial output and marks it incomplete.
