from typing import TypedDict


class BuiltInAction(TypedDict):
    key: str
    label: str
    prompt_template: str
    context_strategy: str
    context_value: int | None
    hard_character_cap: int


class BuiltInPreset(TypedDict):
    name: str
    action_keys: tuple[str, ...]


def _action(
    key: str,
    label: str,
    prompt: str,
    *,
    strategy: str = "all",
    value: int | None = None,
    cap: int = 100_000,
) -> BuiltInAction:
    return {
        "key": key,
        "label": label,
        "prompt_template": prompt,
        "context_strategy": strategy,
        "context_value": value,
        "hard_character_cap": cap,
    }


BUILTIN_ACTIONS: tuple[BuiltInAction, ...] = (
    _action(
        "summary",
        "Summary",
        "Summarize the discussion, decisions, risks, and next steps. Use only "
        "information stated in the transcript, separate unresolved points from "
        "conclusions, and say when an owner or deadline was not specified.",
        strategy="since_previous_turn",
        value=3,
        cap=40_000,
    ),
    _action(
        "decisions",
        "Decisions",
        "List the decisions made in the selected discussion. For each decision, "
        "state the decision, its stated rationale, owner, and effective date when "
        "available. Do not treat suggestions or unresolved options as decisions.",
        strategy="since_previous_turn",
        value=3,
        cap=40_000,
    ),
    _action(
        "next_steps",
        "Next steps",
        "Extract concrete next steps from the selected discussion. For each item, "
        "give the action, owner, deadline, and dependencies when explicitly stated. "
        "Put unassigned or undated actions in separate sections instead of inventing "
        "missing details.",
        strategy="last_minutes",
        value=12,
        cap=35_000,
    ),
    _action(
        "open_questions",
        "Open questions",
        "Identify questions and issues that remain unresolved in the transcript. "
        "Group related items, include any proposed answer or responsible person, and "
        "omit questions that were clearly resolved later in the conversation.",
        cap=70_000,
    ),
    _action(
        "risks",
        "Risks",
        "Extract risks, blockers, dependencies, and concerns explicitly supported by "
        "the transcript. For each item, state its possible impact and any mitigation "
        "that was discussed. Clearly label reasonable inference as inference and do "
        "not invent probabilities or severity.",
        cap=70_000,
    ),
    _action(
        "catch_up",
        "Catch up",
        "Give me a concise catch-up on the latest part of the conversation: the "
        "current topic, important facts, decisions, disagreements, and anything that "
        "appears to require my attention next.",
        strategy="last_minutes",
        value=7,
        cap=25_000,
    ),
    _action(
        "project_status",
        "Project status",
        "Create a project status snapshot from the selected discussion. Organize it "
        "into completed, in progress, planned, changed, and unknown. Include owners "
        "and dates only when stated, and call out conflicting or ambiguous status "
        "reports.",
        strategy="since_previous_turn",
        value=5,
        cap=50_000,
    ),
    _action(
        "blockers",
        "Blockers",
        "Extract current blockers and dependencies from the selected discussion. For "
        "each one, state what is blocked, the cause, affected work, owner, needed "
        "external input, and next checkpoint when available. Separate active blockers "
        "from possible future risks.",
        strategy="last_minutes",
        value=15,
        cap=40_000,
    ),
    _action(
        "stakeholder_update",
        "Stakeholder update",
        "Draft a concise stakeholder update based only on the transcript. Include "
        "overall status, notable progress, decisions, risks or blockers, and the next "
        "milestones. Avoid internal conversational detail and explicitly mark "
        "information that is uncertain or was not agreed.",
        strategy="since_previous_turn",
        value=5,
        cap=50_000,
    ),
    _action(
        "needs_and_pains",
        "Needs & pains",
        "Extract the goals, pain points, jobs to be done, and current workarounds "
        "described in the transcript. For each item, include who experiences it, its "
        "context, impact, and frequency only when stated. Keep proposed solutions "
        "separate from underlying needs.",
        cap=70_000,
    ),
    _action(
        "requirements",
        "Requirements",
        "Turn the transcript into a structured list of candidate requirements. "
        "Classify each as functional, non-functional, data, integration, operational, "
        "or policy-related; include supporting evidence and acceptance signals when "
        "stated. Mark each item as agreed, proposed, or inferred, and do not invent "
        "details.",
        cap=90_000,
    ),
    _action(
        "constraints",
        "Constraints",
        "Identify constraints, dependencies, assumptions, exclusions, and boundary "
        "conditions in the transcript. Group them by technical, business, legal or "
        "policy, time, budget, data, and organizational concerns. Clearly separate "
        "explicit constraints from assumptions that still need validation.",
        cap=70_000,
    ),
    _action(
        "evidence",
        "Evidence",
        "Create an evidence log for the discovery. List the strongest "
        "transcript-supported observations, the speaker or stakeholder associated "
        "with each one, and a short faithful paraphrase or brief quote. Do not "
        "fabricate quotations, and label interpretations separately from direct "
        "evidence.",
        cap=80_000,
    ),
    _action(
        "discovery_brief",
        "Discovery brief",
        "Produce a concise discovery brief with sections for context, stakeholders, "
        "goals, current workflow, pain points, candidate requirements, constraints, "
        "success criteria, open questions, and recommended follow-ups. Use only "
        "transcript evidence and mark anything not yet validated.",
        cap=100_000,
    ),
    _action(
        "account_brief",
        "Account brief",
        "Create an account brief from the transcript. Include customer context, "
        "stated goals, current process or tools, pain points, stakeholders, desired "
        "outcomes, timing, constraints, and unresolved questions. Distinguish customer "
        "statements from our team's assumptions or claims.",
        cap=80_000,
    ),
    _action(
        "qualification",
        "Qualification",
        "Summarize the opportunity qualification using only explicit transcript "
        "evidence. Cover problem and impact, desired outcome, stakeholders and "
        "decision authority, decision process, budget or commercial constraints, "
        "timing, alternatives, and next step. Mark every unknown as unknown rather "
        "than inferring it.",
        cap=80_000,
    ),
    _action(
        "objections",
        "Objections",
        "List customer objections, concerns, doubts, and adoption risks. For each one, "
        "include the underlying issue, any response given during the call, whether the "
        "concern appears resolved, and the best evidence-based follow-up. Do not treat "
        "a neutral question as an objection unless the context supports it.",
        cap=70_000,
    ),
    _action(
        "commitments",
        "Commitments",
        "Extract commitments made by either side in the selected discussion. For each "
        "commitment, state who committed to what, by when, and any dependency or "
        "condition. Separate firm commitments from suggestions, possibilities, and "
        "requests awaiting confirmation.",
        strategy="since_previous_turn",
        value=5,
        cap=45_000,
    ),
    _action(
        "crm_note",
        "CRM note",
        "Create a compact CRM-ready note with sections for call purpose, customer "
        "situation, needs and impact, stakeholders, qualification facts, objections, "
        "discussed solution, commitments, next step, and open fields. Use short factual "
        "bullets and explicitly mark missing information.",
        cap=100_000,
    ),
    _action(
        "technical_brief",
        "Technical brief",
        "Create a technical brief from the transcript. Cover the problem, current "
        "behavior, desired behavior, relevant components and interfaces, constraints, "
        "assumptions, proposed changes, unresolved questions, and verification needs. "
        "Mark uncertain or conflicting statements explicitly.",
        cap=90_000,
    ),
    _action(
        "options_and_tradeoffs",
        "Options & trade-offs",
        "Compare the technical options discussed in the transcript. For each option, "
        "list the stated benefits, costs, risks, dependencies, reversibility, and "
        "evidence. Do not add options or trade-offs that were not discussed; identify "
        "evaluation criteria that remain missing.",
        cap=90_000,
    ),
    _action(
        "decision_record",
        "Decision record",
        "Draft an architecture or engineering decision record using only the "
        "transcript. Include context, decision status, considered options, chosen "
        "decision, rationale, consequences, risks, and follow-up work. If no final "
        "decision was reached, produce a pending decision record and state exactly "
        "what remains unresolved.",
        cap=100_000,
    ),
    _action(
        "failure_modes",
        "Failure modes",
        "Extract discussed failure modes, edge cases, operational risks, security or "
        "privacy concerns, and observability gaps. For each item, include trigger, "
        "impact, detection, mitigation, and test coverage when stated. Clearly "
        "separate explicit discussion from cautious inference.",
        cap=80_000,
    ),
    _action(
        "implementation_plan",
        "Implementation plan",
        "Turn the agreed technical discussion into an implementation plan. Organize "
        "work into ordered steps, dependencies, owners, validation, rollout, and "
        "rollback considerations. Include only agreed or strongly supported work, and "
        "place proposals or missing details in a separate open-items section.",
        cap=100_000,
    ),
    _action(
        "interview_summary",
        "Interview summary",
        "Summarize the interview using only job-related transcript evidence. Cover the "
        "candidate's relevant experience, examples, responsibilities, demonstrated "
        "skills, stated interests, constraints, and unanswered areas. Distinguish the "
        "candidate's claims, interviewer explanations, and observed evidence.",
        cap=80_000,
    ),
    _action(
        "competency_evidence",
        "Competency evidence",
        "Organize the interview evidence by the job-related competencies actually "
        "discussed. For each competency, list concrete examples, the candidate's role "
        "and actions, stated results, and missing verification. Do not create a "
        "numerical score, infer personal traits, or use protected or sensitive "
        "attributes.",
        cap=100_000,
    ),
    _action(
        "follow_up_questions",
        "Follow-up questions",
        "Suggest a short prioritized list of job-related follow-up questions based on "
        "gaps or ambiguities in the recent interview. Prefer behavioral questions "
        "that ask for a specific situation, the candidate's own actions, reasoning, "
        "and result. Do not ask about protected or sensitive personal information.",
        strategy="last_minutes",
        value=15,
        cap=40_000,
    ),
    _action(
        "evidence_gaps",
        "Evidence gaps",
        "Identify important job-related areas that were mentioned but remain "
        "unsupported, ambiguous, contradictory, or unexplored. Explain what evidence "
        "is missing and propose a neutral follow-up question. Do not interpret missing "
        "evidence as a negative conclusion.",
        cap=90_000,
    ),
    _action(
        "candidate_questions",
        "Candidate questions",
        "List the questions the candidate asked and summarize the answer given to each. "
        "Mark questions that were unanswered, only partially answered, or require a "
        "follow-up from the company. Preserve uncertainty and do not invent company "
        "policy or commitments.",
        cap=80_000,
    ),
    _action(
        "interview_debrief",
        "Interview debrief",
        "Draft an evidence-based interview debrief. Include role-relevant evidence, "
        "strengths supported by examples, concerns or gaps supported by examples, "
        "unanswered questions, and suggested areas for the next interviewer. Do not "
        "infer sensitive traits or make an autonomous hire or no-hire recommendation.",
        cap=100_000,
    ),
    _action(
        "employment_tech_answer",
        "Tech answer",
        "Identify the interviewer's latest technical question/questions from the recent "
        "transcript, reconstructing it when captions split a sentence or the speakers "
        "interrupt one another. Draft a correct, natural answer that I can say aloud. "
        "Lead with the direct answer, then add only the reasoning, steps, trade-offs, "
        "or compact example needed for this question. Use facts from the working "
        "directory when they provide relevant verified experience, but never invent "
        "experience, results, or knowledge. If the question is ambiguous, state the "
        "most likely interpretation and give one short clarification question. Aim "
        "for 30-60 seconds of speech unless the question clearly requires code or a "
        "longer explanation.",
        strategy="last_minutes",
        value=5,
        cap=20_000,
    ),
    _action(
        "employment_my_answer",
        "My answer",
        "Identify the current question about my background, skills, behavior, or a "
        "past project, reconstructing it from fragmented captions when necessary. "
        "Use the working-directory information to select the strongest truthful and "
        "role-relevant material. Write a first-person answer I can say aloud, tailored "
        "to the role and conversation. For a broad introduction, produce one focused "
        "45–60 second narrative; for a specific experience question, use a compact "
        "situation → responsibility → action → result structure lasting about 45–90 "
        "seconds. Include metrics only when supported by my files. Do not fabricate or "
        "inflate experience; if useful evidence is missing, keep the answer honest "
        "and concise.",
        strategy="last_minutes",
        value=7,
        cap=25_000,
    ),
    _action(
        "employment_role_check",
        "Role check",
        "Evaluate the role and employer using the whole interview plus relevant facts "
        "from my working directory. Briefly cover: fit with my goals and strengths; "
        "positive signals; evidence-backed yellow or red flags; important unknowns to "
        "clarify; and compensation or conditions worth negotiating. Clearly separate "
        "what was stated in the interview, what comes from my files, and your "
        "inference. Do not invent current market ranges: if reliable market evidence "
        "is unavailable, say so and suggest a negotiation position based on the "
        "information actually available. Finish with a pragmatic recommendation: "
        "continue, clarify, negotiate, or withdraw, with a short reason.",
        cap=70_000,
    ),
    _action(
        "employment_questions",
        "Questions",
        "Suggest 2–4 high-value questions I can ask the interviewer now or at the end. "
        "Use the whole conversation, the role, and relevant working-directory context. "
        "Do not repeat questions already answered. Prioritize the largest remaining "
        "unknowns about expectations, technical or product challenges, team and "
        "decision-making, success measures, growth, and working conditions. Phrase "
        "each question exactly as I can say it aloud; keep it concise, curious, and "
        "professional rather than adversarial. Add a very short note explaining what "
        "signal each question is intended to reveal.",
        cap=70_000,
    ),
    _action(
        "employment_handle_gap",
        "Handle gap",
        "Identify the latest question that exposes a gap in my knowledge or experience "
        "and check the working-directory information for truthful adjacent strengths. "
        "Draft one confident 30–60 second answer I can say aloud: acknowledge the exact "
        "gap briefly, state what I do understand, connect relevant transferable "
        "experience, and explain a concrete way I would close the gap. If the issue is "
        "only forgotten terminology or an academic detail, supply the missing concept "
        "without pretending I recalled it unaided. Never fabricate hands-on experience "
        "or credentials. Include one concise clarification question only when it would "
        "materially improve the answer.",
        strategy="last_minutes",
        value=5,
        cap=20_000,
    ),
    _action(
        "language_hint",
        "Hint",
        "Give me one compact hint that helps me find my own response to the latest "
        "question or language task. Point to a useful direction, rule, or distinction "
        "without supplying the complete answer. Use a learner level only when it is "
        "explicitly supported by the session instructions, transcript, or reliable "
        "working-directory material; otherwise adapt conservatively to my language "
        "in the transcript and do not assign me a CEFR level.",
        strategy="last_minutes",
        value=5,
        cap=20_000,
    ),
    _action(
        "language_words",
        "Words",
        "Suggest 3–7 words or short expressions that I can use for the current topic "
        "or question. Give a brief meaning or usage cue for each, but do not compose "
        "my full answer. Use a learner level only when it is explicitly supported by "
        "the session instructions, transcript, or reliable working-directory material; "
        "otherwise match my demonstrated language conservatively and avoid a large "
        "jump in difficulty.",
        strategy="last_minutes",
        value=5,
        cap=20_000,
    ),
    _action(
        "language_start",
        "Start",
        "Give me 2–3 short sentence starters for answering the latest question, leaving "
        "the important content for me to complete. Keep them natural and immediately "
        "speakable. Use a learner level only when it is explicitly supported by the "
        "session instructions, transcript, or reliable working-directory material; "
        "otherwise adapt conservatively to my language and do not label my level.",
        strategy="last_minutes",
        value=5,
        cap=20_000,
    ),
    _action(
        "language_natural",
        "Natural",
        "Rewrite my latest relevant utterance in one natural way while preserving its "
        "meaning, tone, and approximate difficulty. Then explain at most two small, "
        "useful changes. If my utterance cannot be identified reliably, say so instead "
        "of rewriting another speaker. Use a learner level only when explicitly "
        "supported by the session instructions, transcript, or reliable working-directory "
        "material; otherwise adapt conservatively and do not assign a CEFR level.",
        strategy="last_minutes",
        value=3,
        cap=15_000,
    ),
    _action(
        "language_missed",
        "Missed?",
        "Briefly restate the latest question or request addressed to me and identify "
        "what information or language task it asks for. Do not answer it for me. If the "
        "target question or speaker is uncertain, state the ambiguity. Keep the "
        "explanation appropriate to an explicitly supported learner level; otherwise "
        "adapt conservatively to my language without assigning a CEFR level.",
        strategy="last_minutes",
        value=5,
        cap=20_000,
    ),
    _action(
        "language_explain",
        "Explain",
        "Identify the latest word, expression, or grammar point that most plausibly "
        "needs explanation and explain it simply, followed by one example relevant to "
        "the conversation. Say when the intended item is ambiguous. Use a learner level "
        "only when explicitly supported by the session instructions, transcript, or "
        "reliable working-directory material; otherwise adapt conservatively to my "
        "language and do not assign a CEFR level.",
        strategy="last_minutes",
        value=5,
        cap=20_000,
    ),
    _action(
        "language_rescue",
        "Rescue",
        "Help me respond immediately with one nearly complete, natural sentence or "
        "compact answer structure, but leave one meaningful blank for the key content "
        "that I must supply. You may add one short cue for what belongs in the blank; "
        "do not complete it for me. Use a learner level only when explicitly supported "
        "by the session instructions, transcript, or reliable working-directory material; "
        "otherwise adapt conservatively and avoid a large jump in difficulty.",
        strategy="last_minutes",
        value=5,
        cap=20_000,
    ),
    _action(
        "social_read_room",
        "Read room",
        "Give a compact reading of the current interaction in three parts: observable "
        "signals from the transcript, one or two plausible interpretations, and what "
        "remains uncertain. Do not decide who is right, diagnose anyone, or present an "
        "inference about another person's feelings or motives as fact.",
        strategy="last_minutes",
        value=15,
        cap=40_000,
    ),
    _action(
        "social_pushing",
        "Pushing?",
        "Assess whether my latest relevant behavior could reasonably be experienced "
        "as pressure. Point to the transcript-supported signal, distinguish observation "
        "from interpretation, and offer one gentler alternative that preserves my "
        "intent. If my speaker identity is unclear, say so; do not diagnose or assign "
        "motives to either person.",
        strategy="last_minutes",
        value=10,
        cap=30_000,
    ),
    _action(
        "social_landed",
        "Landed?",
        "Assess how my latest relevant remark may have landed using only the other "
        "person's subsequent words and observable conversational signals. Give at most "
        "two plausible interpretations and clearly state the uncertainty. Do not claim "
        "to know their private feelings, intentions, or diagnosis.",
        strategy="last_minutes",
        value=8,
        cap=25_000,
    ),
    _action(
        "social_softer",
        "Softer",
        "Rewrite my latest relevant message in 1–2 softer, low-pressure ways while "
        "preserving its substantive intent. Do not add an apology, concession, or "
        "emotional claim unless the transcript makes it appropriate. If my message "
        "cannot be identified reliably, say so instead of rewriting another speaker.",
        strategy="last_minutes",
        value=5,
        cap=20_000,
    ),
    _action(
        "social_space",
        "Give space",
        "Suggest one low-pressure next step or short phrase that gives the other person "
        "room while keeping the conversation open. Base it on observable interaction "
        "signals, explain the intended effect in one sentence, and do not speculate "
        "confidently about their feelings or motives.",
        strategy="last_minutes",
        value=8,
        cap=25_000,
    ),
    _action(
        "social_missing",
        "Missing?",
        "Identify one important perspective, need, assumption, or contextual factor I "
        "may be overlooking in the current interaction. Separate transcript evidence "
        "from your interpretation and frame the point as a possibility, not a diagnosis "
        "or a judgment about who is right.",
        strategy="last_minutes",
        value=15,
        cap=40_000,
    ),
    _action(
        "social_next",
        "Next move",
        "Recommend one safe, constructive next move for me in the current interaction. "
        "Give the exact concise wording I could use and one short reason for choosing "
        "it. Prefer clarification, acknowledgement, or space over pressure, and keep "
        "uncertain interpretations explicitly tentative.",
        strategy="last_minutes",
        value=10,
        cap=30_000,
    ),
    _action(
        "negotiation_interests",
        "Interests",
        "Map the other side's explicit positions and the interests that may sit behind "
        "them. Keep stated facts separate from cautious inference, cite the supporting "
        "conversation context, and identify the most useful clarification question. Do "
        "not assume hidden motives or suggest manipulation.",
        cap=70_000,
    ),
    _action(
        "negotiation_leverage",
        "My leverage",
        "Identify my real sources of leverage in this negotiation and the limits or "
        "dependencies of each. Use only transcript-supported facts and reliable working-"
        "directory context, distinguish leverage from a wish or threat, and do not "
        "recommend bluffing, fabricated alternatives, or false urgency.",
        cap=70_000,
    ),
    _action(
        "negotiation_constraint",
        "Constraint",
        "Identify the explicit and likely constraints affecting each side. Separate "
        "confirmed constraints from inference, give a confidence cue for every inferred "
        "item, and suggest the single most useful question for testing the biggest "
        "uncertainty. Do not invent budgets, deadlines, authority, or alternatives.",
        cap=70_000,
    ),
    _action(
        "negotiation_timing",
        "Push/wait?",
        "Recommend whether I should press the current point, wait, or clarify first. "
        "Base the recommendation on the negotiation's stated interests, constraints, "
        "and current momentum; name the main risk and the condition that would change "
        "the recommendation. Do not suggest threats, deception, or artificial pressure.",
        cap=70_000,
    ),
    _action(
        "negotiation_counteroffer",
        "Counteroffer",
        "Draft one concise counteroffer I can say aloud based on the stated terms, "
        "interests, and constraints. Prefer conditional exchanges and trade-offs over "
        "unilateral demands, and briefly state the rationale. Never invent authority, "
        "alternatives, deadlines, commitments, or facts to strengthen the offer.",
        cap=70_000,
    ),
    _action(
        "negotiation_conceding",
        "Conceding?",
        "Compare my latest position or offer with my earlier position and the other "
        "side's movement. Identify any concession, what was received in return, and "
        "what remains unresolved. Do not call clarification or an unaccepted proposal "
        "a concession, and do not invent terms that were not stated.",
        cap=70_000,
    ),
    _action(
        "negotiation_status",
        "Status",
        "Give a compact negotiation status: each side's current position, confirmed "
        "agreements, remaining gaps, important constraints, and the next decision or "
        "clarification needed. Clearly separate explicit statements from inference and "
        "do not imply that tentative language is a commitment.",
        cap=80_000,
    ),
    _action(
        "interviewer_follow_up",
        "Follow up",
        "Write exactly one concise, natural follow-up question based on the latest "
        "substantive answer. Ask about a specific ambiguity, implication, or useful "
        "detail from that answer. Do not answer for the interviewee, repeat a resolved "
        "question, or add commentary around the question.",
        strategy="last_minutes",
        value=7,
        cap=25_000,
    ),
    _action(
        "interviewer_deeper",
        "Go deeper",
        "Write exactly one question that explores the reasoning, cause, process, or "
        "consequence behind the latest important answer. Keep it open, neutral, and "
        "grounded in what was actually said. Do not answer for the interviewee or add "
        "commentary around the question.",
        strategy="last_minutes",
        value=10,
        cap=30_000,
    ),
    _action(
        "interviewer_example",
        "Example",
        "Write exactly one concise question asking for a concrete example, event, or "
        "piece of evidence for the latest relevant claim. Tailor it to the conversation "
        "and avoid presuming that the claim is false. Output only the question.",
        strategy="last_minutes",
        value=7,
        cap=25_000,
    ),
    _action(
        "interviewer_challenge",
        "Challenge",
        "Write exactly one neutral question that gently tests an important recent claim "
        "by examining its premise, evidence, boundary, or a plausible exception. Do not "
        "argue, accuse, exaggerate uncertainty, or answer for the interviewee. Output "
        "only the question.",
        strategy="last_minutes",
        value=15,
        cap=40_000,
    ),
    _action(
        "interviewer_contradiction",
        "Mismatch?",
        "Check the whole transcript for a meaningful inconsistency involving the "
        "current topic. If one is well supported, briefly state the two conflicting or "
        "tension-filled points and give one neutral clarification question. If none is "
        "supported, say so plainly. Treat differences in wording, context, or evolving "
        "views cautiously rather than forcing a contradiction.",
        cap=80_000,
    ),
    _action(
        "interviewer_missing",
        "Missing?",
        "Identify 1–3 high-value aspects of the interview objective that remain "
        "unexplored or insufficiently supported. Prioritize them, explain each gap in "
        "one short phrase, and do not repeat questions already answered. Do not infer "
        "that missing information is evidence of a negative conclusion.",
        cap=80_000,
    ),
    _action(
        "interviewer_next",
        "Next question",
        "Choose exactly one strategically best next question using the whole transcript. "
        "It should advance the interview objective, address the most important remaining "
        "gap, and avoid repeating answered questions. Give the question first, followed "
        "by one short sentence explaining why it is the best next step; do not answer "
        "for the interviewee.",
        cap=80_000,
    ),
)


BUILTIN_PRESETS: tuple[BuiltInPreset, ...] = (
    {
        "name": "Default",
        "action_keys": (
            "summary",
            "decisions",
            "next_steps",
            "open_questions",
            "risks",
            "catch_up",
        ),
    },
    {
        "name": "Project Sync",
        "action_keys": (
            "project_status",
            "blockers",
            "decisions",
            "next_steps",
            "risks",
            "stakeholder_update",
        ),
    },
    {
        "name": "Discovery",
        "action_keys": (
            "needs_and_pains",
            "requirements",
            "constraints",
            "evidence",
            "open_questions",
            "discovery_brief",
        ),
    },
    {
        "name": "Sales Call",
        "action_keys": (
            "account_brief",
            "qualification",
            "objections",
            "commitments",
            "crm_note",
        ),
    },
    {
        "name": "Technical Review",
        "action_keys": (
            "technical_brief",
            "options_and_tradeoffs",
            "decision_record",
            "failure_modes",
            "open_questions",
            "implementation_plan",
        ),
    },
    {
        "name": "Hiring Interview",
        "action_keys": (
            "interview_summary",
            "competency_evidence",
            "follow_up_questions",
            "evidence_gaps",
            "candidate_questions",
            "interview_debrief",
        ),
    },
    {
        "name": "Employment Interview",
        "action_keys": (
            "employment_tech_answer",
            "employment_my_answer",
            "employment_role_check",
            "employment_questions",
            "employment_handle_gap",
        ),
    },
    {
        "name": "Language Practice",
        "action_keys": (
            "language_hint",
            "language_words",
            "language_start",
            "language_natural",
            "language_missed",
            "language_explain",
            "language_rescue",
        ),
    },
    {
        "name": "Social Compass",
        "action_keys": (
            "social_read_room",
            "social_pushing",
            "social_landed",
            "social_softer",
            "social_space",
            "social_missing",
            "social_next",
        ),
    },
    {
        "name": "Negotiation Coach",
        "action_keys": (
            "negotiation_interests",
            "negotiation_leverage",
            "negotiation_constraint",
            "negotiation_timing",
            "negotiation_counteroffer",
            "negotiation_conceding",
            "negotiation_status",
        ),
    },
    {
        "name": "Interviewer",
        "action_keys": (
            "interviewer_follow_up",
            "interviewer_deeper",
            "interviewer_example",
            "interviewer_challenge",
            "interviewer_contradiction",
            "interviewer_missing",
            "interviewer_next",
        ),
    },
)
