# INTENT-002 — Close the Mastery Loop

**Project:** Mastery Lab  
**Type:** Progressive Intent — Feature Enhancement  
**Priority:** High  
**Status:** Ready for implementation

## 1. Intent

Transform Mastery Lab from a challenge-and-submission application into an AI-assisted learning experience.

Today, a learner can create a learning goal, select a challenge, submit an answer, and see the submission history. However, the learner cannot easily obtain an AI-generated evaluation of their work.

The application currently tells the learner to obtain criterion-by-criterion feedback through a browser form or an MCP-connected assistant. This is an incomplete experience.

**Desired outcome:** After submitting an answer, the learner receives meaningful, evidence-grounded AI feedback against the challenge's evaluation criteria, understands what was demonstrated and what remains weak, and can improve through another attempt.

The application should function as a mastery coach, not merely an answer repository.

## 2. Inputs and Existing Context

Inspect the existing repository before implementing changes.

Preserve the current working capabilities:

- Learning goals and their associated domains.
- Challenges and their evaluation criteria.
- Submission creation and persistence.
- Submission history.
- Existing feedback records, if supported.
- Existing MCP capabilities and integrations.
- Current application styling and navigation.

The existing Calder Medical Distribution challenge provides an immediate acceptance scenario.

It includes six criteria:

- C1: System boundaries and components.
- C2: Access control for retrieval.
- C3: Governance of actions.
- C4: Auditability and provenance.
- C5: Failure behavior and safety.
- C6: Validation plan and evidence.

An existing Submission #1 contains an architecture response, but currently shows that no feedback has been recorded.

Use the actual repository contracts and persisted data rather than assuming particular API routes, database tables, model providers, or framework choices.

## 3. Required Learner Experience

### A. Submit and Evaluate

When the learner submits an answer, Mastery Lab should automatically initiate an AI evaluation using the challenge's existing criteria.

The system should visibly distinguish:

- Submitted.
- Evaluating.
- Evaluated.
- Evaluation unavailable or failed.

A successful evaluation must be persisted and linked to the submission.

Evaluation must not silently fail or disappear.

Do not create duplicate evaluations when the user refreshes or revisits the page.

### B. Evaluate Existing Submissions

Support evaluation of previously saved submissions that have no feedback.

This requirement is especially important because Submission #1 already exists.

When opening an unevaluated submission, provide an obvious **Evaluate Submission** action.

The user must not have to create another learning goal, paste the original architecture again, or submit duplicate content.

### C. Criterion-by-Criterion Feedback

The evaluation should assess the learner's submission against the actual criteria supplied with the challenge.

For each criterion, provide:

- Criterion name.
- Score or mastery level.
- What the learner demonstrated.
- Evidence from their submitted answer.
- What is missing, weak, or unproven.
- One concrete recommendation for improvement.

Feedback must distinguish between a capability the learner described and a capability the learner actually demonstrated with evidence.

Do not award full credit merely because the submission uses terminology such as orchestration, MCP, AgentCore, RAG, governance, or audit.

Evaluate architectural reasoning, correctness, tradeoffs, completeness, and supporting evidence.

The evaluator should be capable of recognizing a sound alternative architecture that differs from any expected reference