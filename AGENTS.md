# AGENTS.md

## 1. Proportional Workflow and Agent Roles

Choose the workflow based on the task's scope and risk, not the number of changed lines. The primary agent may inspect implementation, edit code and documents, and run checks directly. Subagents are optional unless the user explicitly requests them; do not create a spec, branch, audit, or test solely to satisfy a fixed ceremony.

- **Small, low-risk tasks:** Implement directly and perform a proportionate check (for example, inspect the diff or run a focused test). A one-line change can still be high-risk if it affects critical behavior.
- **Moderate tasks:** Inspect relevant interfaces and implementation, state consequential assumptions, implement, and run focused tests or other appropriate checks. Delegate an independent review only when it materially helps.
- **Complex or high-risk tasks:** For cross-module contracts, distributed storage and recovery, data integrity, security, or changes whose correctness is difficult to verify, define verifiable acceptance criteria before implementation. Use an architect, independent review, or black-box testing when warranted by the risks and available tools. A written spec in `docs/specs/` is useful for substantial design changes, not mandatory for every task.

When delegating, an **architect** analyzes requirements and interfaces; a **coder** implements; a **white-box auditor** reviews implementation and diff; and a **black-box tester** checks observable behavior against requirements. Keep independent reviews independent when they are used. An isolated workspace is useful for parallel or conflicting work, but is not required for every edit.

Acceptance requires the checks appropriate to the chosen risk and any checks explicitly requested by the user. Report meaningful failures and unverified behavior; do not repeat a full agent sequence for a small correction unless the correction changes the risk or invalidates prior evidence.

## 2. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 3. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 4. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 5. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
