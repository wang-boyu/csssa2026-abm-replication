---
name: qa-assisted-implementation-loop
description: Use when the user explicitly asks Codex to coordinate subagents for non-trivial implementation work with an implementation worker, QA worker, read-only reviewer, read-only verifier, inner loop, and parent final review.
metadata:
  maturity: "draft"
  version: "0.1.0"
  lifecycle: "superseded"
  superseded_by: "implement-with-independent-qa"
---

# QA-Assisted Implementation Loop

Use this skill for non-trivial code changes when the user explicitly asks for subagents, workers, or an inner/outer loop. Within explicit subagent coordination, QA-assisted mode is the default for implementation work that changes behavior.

## Roles

- Parent/orchestrator: decomposes scope, owns escalation, protects boundaries, integrates results, and performs final review.
- Implementation worker: edits production/source code in a narrow assigned scope.
- QA worker: writes or updates tests and test fixtures only. Any broader write scope requires user escalation before proceeding.
- Read-only reviewer: reviews source and tests for correctness, compatibility, and scope.
- Read-only verifier: runs focused and broader checks; reports commands, outputs, and failures.

Writable workers must have narrow ownership. Reviewers and verifiers must not edit files.

## Escalation

Stop and ask the user before any material assumption. Material assumptions include API semantics, compatibility behavior, public docs wording, scope expansion, destructive actions, migration strategy, test expectation changes, or conflicting instructions or reviewer guidance.

Subagents must not guess through material ambiguity. They report ambiguity to the parent. The parent escalates to the user when the decision affects behavior, public API, compatibility, scope, or risk.

Routine implementation mechanics that can be verified from code, tests, formatters, or task docs do not require escalation.

## Workflow

1. Parent states scope, forbidden work, ownership boundaries, and success criteria.
2. Implementation worker makes source changes only within its scope.
3. QA worker adds or updates tests for requested behavior and regressions.
4. Read-only reviewer inspects implementation and tests.
5. Read-only verifier runs focused checks first, then broader available checks if focused checks pass.
6. Parent sends review findings or test failures back to the appropriate writable worker.
7. Repeat until reviewer reports no findings and verifier reports passing checks or a clear external blocker.
8. Parent performs an independent final review after the inner loop is clean.
9. If parent finds issues, send them back through the loop.
10. Finish only when implementation worker, QA worker, reviewer, verifier, and parent are satisfied.

## Final Response

State whether the task is complete, summarize important changes, report checks and results, confirm scope boundaries and forbidden files, and mention remaining risks or deferred work. Do not commit unless the user explicitly asked for a commit.
