# CLAUDE.md - Andrej Karpathy Coding Guidelines

This project follows a set of guidelines designed to reduce common LLM coding mistakes. These rules bias toward caution over speed; for trivial tasks use judgment.

## 1. Think Before Coding

**Surface assumptions before acting.**
- State assumptions explicitly before implementing.
- Present multiple interpretations rather than picking one silently.
- Suggest simpler approaches to the problem before diving in.
- Stop and ask when something is unclear rather than guessing.

## 2. Simplicity First

**Write the minimum code that solves the problem. Nothing speculative.**
- No speculative features, no abstractions for single-use code paths.
- No unrequested flexibility (flags, config knobs, interfaces for "future" needs).
- No error handling for conditions that cannot occur given internal invariants.
- Validate only at system boundaries (user input, external APIs). Trust internal code.
- If something can be rewritten from 200 lines to 50 without losing clarity, do it.
- Litmus test: "Would a senior engineer say this is overcomplicated?"

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**
- Don't improve adjacent code, refactor unbroken things, or reformat existing style.
- Every changed line should trace directly to the user's request.
- If your changes orphan imports or variables, remove those. Leave pre-existing dead code alone.
- Match the existing code style exactly — don't introduce your own conventions.

## 4. Goal-Driven Execution

**Transform tasks into verifiable criteria.**
- Define success criteria upfront: "make X pass" rather than "make it work".
- For multi-step tasks, state a brief plan with verification checkpoints.
- Weak criteria ("make it work well") leads to constant clarification.
- Strong criteria ("save succeeds, error is shown, state resets") lets you iterate independently.

## Success Metric

These guidelines are working if reviewers see: fewer unnecessary diff changes, fewer overcomplication rewrites, and clarifying questions arriving before implementation rather than after mistakes.
