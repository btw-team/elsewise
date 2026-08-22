# Sessions, actions, and presets

## Session state and history

Sessions persist transcript segments, utterances, agent runs, and messages in local
SQLite. A stopped session can be opened again and restarted. History is loaded in
bounded pages so long meetings do not enlarge the global live snapshot.

The action preset, provider, language, initial prompt, and working directory are
first-start settings. The provider remains locked because Codex and Claude histories
are not interchangeable.

## Actions

An action contains a button label, prompt, context strategy and amount, and hard
character limit. Actions are global definitions. The session's preset determines
which buttons are visible. Actions and presets can be edited whenever no session is
actively recording, including when no session is selected.

## Context strategies

- **Last utterances** selects the requested number of final utterances.
- **Last minutes** selects utterances after a transcript-time threshold.
- **Since previous turn** overlaps recent context around the prior completed agent
  boundary.
- **All** reads history backwards only until the hard character cap is filled.

The selected transcript is frozen at click time. Queue delays therefore do not
silently change the request's context.

## Factory presets

A clean database includes these factory presets:

- **Default** for general summaries, decisions, follow-ups, risks, and catch-up.
- **Project Sync** for status, blockers, decisions, next steps, risks, and stakeholder
  updates.
- **Discovery** for needs, requirements, constraints, evidence, open questions, and a
  discovery brief.
- **Sales Call** for account context, qualification, objections, commitments, and CRM
  notes.
- **Technical Review** for technical analysis, trade-offs, decisions, failure modes,
  open questions, and implementation planning.
- **Hiring Interview** for evidence-based interviewer notes and follow-ups.
- **Employment Interview** for real-time assistance to the interviewee.
- **Language Practice** for level-appropriate hints, vocabulary, phrasing, explanations,
  and emergency response scaffolding without answering for the learner.
- **Social Compass** for cautious readings of interpersonal signals and low-pressure
  next moves without mind-reading or diagnosis.
- **Negotiation Coach** for interests, constraints, leverage, trade-offs, and negotiation
  status without deceptive or coercive tactics.
- **Interviewer** for focused follow-ups, deeper questions, examples, gentle challenges,
  gaps, and the best next question.

Language Practice uses a learner level only when it is explicitly supported by the
session instructions, transcript, or reliable working-directory material. Otherwise,
it adapts conservatively to the learner's demonstrated language and does not assign a
CEFR level.

Default is the fallback when a referenced preset no longer exists.

## Free prompts and export

Settings control how much transcript context accompanies a free prompt. Enter sends
the request. Export Markdown atomically writes `captions.md` and `agent.md`.

Permanent deletion removes the selected session's database records and its
UUID-named export directory. It has no trash or undo step and cannot remove another
session's export directory.
