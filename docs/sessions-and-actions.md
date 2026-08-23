# Sessions, actions, and presets

Elsewise is not tied to one meeting or note-taking workflow. A preset defines the
kind of help needed during a conversation and exposes a focused set of actions for
that role. The same transcript engine can therefore behave like an interview aid,
language-practice partner, negotiation coach, technical reviewer, or a workflow
designed by the user.

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

## Built-in presets

A clean database installs these presets as starting points:

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

## Design your own workflow

Actions and presets are editable in the web GUI whenever no session is actively
recording. A practical workflow can be built without changing application code:

1. Decide what help a person in this role needs during the conversation.
2. Create one action for each focused request. Give it a short label, precise prompt,
   context strategy, amount, and hard character cap.
3. Create a preset and add only the actions that should be visible together.
4. Select the preset for a new session and refine it after real use.

Prefer a small set of distinct actions over a large collection of overlapping
buttons. For example, an interviewee may need **Tech answer**, **My answer**, and
**Handle gap**, while an interviewer instead needs **Follow up**, **Go deeper**, and
**Next question**. A language learner can use the same engine through **Hint**,
**Words**, **Explain**, and **Rescue**.

Treat prompts as instructions for evidence and uncertainty, not just output format.
State whether the agent may infer, require it to distinguish transcript evidence
from suggestions, and choose the narrowest context window that still supports the
task. New built-in workflow proposals should follow the privacy and test-fixture
rules in [Contributing](../CONTRIBUTING.md).

## Free prompts and export

Settings control how much transcript context accompanies a free prompt. Enter sends
the request. Export Markdown atomically writes `captions.md` and `agent.md`.

Permanent deletion removes the selected session's database records and its
UUID-named export directory. It has no trash or undo step and cannot remove another
session's export directory.
