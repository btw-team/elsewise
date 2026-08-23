# Stable API errors

REST failures use one envelope:

```json
{ "error": { "code": "session_not_found", "message": "Session not found." } }
```

Clients must branch on `code`, not the English diagnostic `message`. The canonical
machine-readable catalog is [`shared/api-errors.json`](../../shared/api-errors.json).
The web GUI maps every registered code to a catalog key present in EN, RU, FR, ES,
DE, and PT-BR; an unknown code appears in a localized fallback.

| HTTP | Code                             | Meaning                                                  |
| ---- | -------------------------------- | -------------------------------------------------------- |
| 409  | `action_limit_reached`           | The global action limit has been reached.                |
| 404  | `action_preset_not_found`        | The selected session action preset does not exist.       |
| 409  | `agent_cwd_missing`              | The requested agent working directory does not exist.    |
| 422  | `agent_cwd_not_directory`        | The requested agent working path is not a directory.     |
| 422  | `agent_cwd_unavailable`          | The requested agent working directory cannot be used.    |
| 409  | `agent_not_started`              | The session has no initialized agent thread.             |
| 409  | `agent_provider_busy`            | The provider has active or queued work.                  |
| 409  | `agent_provider_locked`          | The session provider is locked after the first start.    |
| 409  | `agent_queue_draining`           | The agent queue is draining during shutdown.             |
| 429  | `agent_queue_full`               | The per-session agent queue is full.                     |
| 422  | `agent_reasoning_requires_model` | Reasoning effort requires an explicit model.             |
| 404  | `agent_run_not_found`            | The requested agent run does not exist.                  |
| 409  | `another_session_running`        | A different session is already recording.                |
| 409  | `button_key_exists`              | The generated action key already exists.                 |
| 404  | `button_not_found`               | The requested action does not exist.                     |
| 400  | `confirmation_mismatch`          | A destructive-operation confirmation does not match.     |
| 409  | `default_preset_name_locked`     | The Default preset cannot be renamed.                    |
| 409  | `default_preset_protected`       | The Default preset cannot be deleted.                    |
| 422  | `invalid_agent_model`            | The selected model is not supported by the provider.     |
| 422  | `invalid_agent_provider`         | The selected agent provider is unknown.                  |
| 422  | `invalid_agent_reasoning_effort` | The selected effort is not supported by the model.       |
| 403  | `invalid_control_token`          | The private runtime control token is invalid.            |
| 422  | `invalid_cursor`                 | The pagination cursor is malformed.                      |
| 422  | `invalid_initial_prompt`         | The initial prompt is blank or invalid.                  |
| 403  | `invalid_origin`                 | The request violates the loopback origin policy.         |
| 422  | `invalid_session_id`             | The session identifier is malformed.                     |
| 404  | `not_found`                      | The requested API route or resource does not exist.      |
| 409  | `preset_action_duplicate`        | An action appears more than once in a preset.            |
| 409  | `preset_action_limit_reached`    | The preset action limit has been reached.                |
| 404  | `preset_action_not_found`        | A referenced preset action does not exist.               |
| 409  | `preset_limit_reached`           | The global preset limit has been reached.                |
| 422  | `preset_name_empty`              | The preset name is blank.                                |
| 409  | `preset_name_exists`             | A preset with this name already exists.                  |
| 404  | `preset_not_found`               | The requested preset does not exist.                     |
| 422  | `prompt_empty`                   | The free prompt is blank.                                |
| 500  | `request_failed`                 | An HTTP failure has no more specific stable code.        |
| 422  | `request_validation_error`       | Request path, query, or body validation failed.          |
| 500  | `segment_missing`                | A running session has no active capture segment.         |
| 409  | `session_already_started`        | First-start-only session fields are locked.              |
| 404  | `session_not_found`              | The requested session does not exist.                    |
| 409  | `session_not_running`            | The operation requires a running session.                |
| 409  | `session_running`                | The operation requires a stopped session.                |
| 503  | `shutdown_unavailable`           | The server runtime cannot currently accept shutdown.     |
| 409  | `ui_event_cursor_pruned`         | The requested UI event cursor predates retained history. |
| 500  | `unsafe_export_path`             | The resolved export path escaped its permitted root.     |

New REST codes must be added to the shared catalog and this table. Automated tests
fail when server source emits an unregistered code or a translation key is missing.
