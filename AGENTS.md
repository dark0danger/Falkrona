# Falkrona Codex Instructions

## Model Budget Policy

The user is on ChatGPT Plus and wants to preserve weekly Codex usage.

Default behavior:
- Prefer the cheapest capable model for the task.
- Use a stronger model only when the task involves architecture, security, social OAuth, Hermes runtime behavior, data isolation, or hard debugging.
- Before using a stronger model for a long task, explain why it is needed.

Suggested routing:
- Use Luna / light model for routine implementation:
  - CRUD screens
  - simple React components
  - CSS/layout polish
  - copy changes
  - seed data
  - small unit tests
  - README/config updates

- Use Sol / medium model for normal serious work:
  - implementing a full phase
  - database schema changes
  - API design
  - Hermes integration
  - provider abstraction for Gemini/OpenAI
  - social import logic
  - test planning and phase gates

- Use Astra / strongest model only for:
  - architecture review
  - security review
  - tenant isolation review
  - OAuth/token handling review
  - difficult bugs after cheaper attempts fail
  - final pre-demo review

When unsure:
- Start with Sol for planning.
- Drop to Luna for repetitive implementation.
- Escalate only if blocked or if risk is high.