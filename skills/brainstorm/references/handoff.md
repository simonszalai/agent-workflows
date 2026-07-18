# Handoff

This content is loaded when Phase 4 begins — after the requirements document is written and
stored as the ticket's source artifact.

---

#### 4.1 Present Next-Step Options

Present next steps using the platform's blocking question tool when available (see Interaction
Rules in the main skill). Otherwise present numbered options in chat and end the turn.

If `Resolve Before Planning` contains any items:

- Ask the blocking questions now, one at a time, by default
- If the user explicitly wants to proceed anyway, first convert each remaining item into an
  explicit decision, assumption, or `Deferred to Planning` question
- If the user chooses to pause instead, present the handoff as paused or blocked rather than
  complete
- Do not offer `Proceed to planning` or `Proceed directly to work` while
  `Resolve Before Planning` remains non-empty

**Question when no blocking questions remain:** "Brainstorm complete. What would you like to
do next?"

**Question when blocking questions remain and user wants to pause:** "Brainstorm paused.
Planning is blocked until the remaining questions are resolved. What would you like to do
next?"

Present only the options that apply:

- **Proceed to planning (Recommended)** - Run `/ticket-plan {TICKET_ID}` for structured
  implementation planning
- **Proceed directly to work** - Only offer this when scope is lightweight, success criteria
  are clear, scope boundaries are clear, and no meaningful technical or research questions
  remain
- **Ask more questions** - Continue clarifying scope, preferences, or edge cases
- **Done for now** - Return later; the ticket holds the requirements

If the direct-to-work gate is not satisfied, omit that option entirely.

#### 4.2 Handle the Selected Option

**If user selects "Proceed to planning (Recommended)":**

Immediately run `/ticket-plan {TICKET_ID}` in the current session. The requirements live in the
ticket's source artifact. Do not print the closing summary first.

**If user selects "Proceed directly to work":**

Immediately run `/ticket-flow {TICKET_ID}` in the current session. Do not print the closing
summary first.

**If user selects "Ask more questions":** Return to Phase 1.3 (Collaborative Dialogue) and
continue asking the user questions one at a time to further refine the design. Probe deeper
into edge cases, constraints, preferences, or areas not yet explored. Continue until the user
is satisfied, update the ticket source artifact, then return to Phase 4. Do not show the
closing summary yet.

#### 4.3 Closing Summary

Use the closing summary only when this run of the workflow is ending or handing off, not when
returning to the Phase 4 options.

When complete and ready for planning, display:

```text
Brainstorm complete!

Ticket: {TICKET_ID} — requirements stored as the source artifact

Key decisions:
- [Decision 1]
- [Decision 2]

Recommended next step: /ticket-plan {TICKET_ID}
```

If the user pauses with `Resolve Before Planning` still populated, display:

```text
Brainstorm paused.

Ticket: {TICKET_ID} — requirements stored as the source artifact

Planning is blocked by:
- [Blocking question 1]
- [Blocking question 2]

Resume with /brainstorm when ready to resolve these before planning.
```
