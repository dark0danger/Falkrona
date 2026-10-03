# Provider Matrix

Verified on 2026-09-28 against the pinned Hermes source and current official docs.

| Mode | Provider | Text/tool calls | Image calls | Private data | Current status |
| --- | --- | --- | --- | --- | --- |
| `offline_test` | deterministic local fixture | allowed | local rendering only | local only | default |
| `gemini_free` | Gemini native API | explicit selection | disabled | rejected before transport | `blocked_no_key` |
| `paid_opt_in` | Gemini | explicit selection and budget | separate opt-in | policy-controlled | configured, unverified |
| `paid_opt_in` | OpenAI | explicit paid opt-in and budget | separate opt-in | policy-controlled | `blocked_cost_policy` |

Model identifiers are configuration, not source constants. A live verification must
record the exact model returned for the selected account at the time of the test.

## Phase 4 controls

- A run selects one configured provider and model. Quota, authorization, and
  transport errors do not trigger a fallback provider or paid escalation.
- Each run reserves model-call, input-token, and output-token allowances before a
  model call. The reservation records the resulting usage ledger entry atomically.
- Gemini free mode rejects classified secret, email, and phone-bearing prompts before
  any model transport. Other modes retain the redacted form rather than raw matches.
- Image capability remains disabled unless its separate opt-in flag is true, even
  when an OpenAI key or paid mode is otherwise configured.

## Creative output without an image API

- The baseline studio will create finished graphics with a local renderer from
  uploaded product photos/logos, confirmed brand colors and fonts, editable text,
  shapes, and reusable layout families. It can export real PNG/JPEG designs without
  an image-generation API.
- The text agent may propose concepts, captions, and structured layout data when an
  eligible text provider is enabled. A fixed trusted renderer turns that data into
  artwork; the agent does not supply arbitrary HTML or scripts.
- If no product photo is available, use typography, shapes, and locally rendered
  patterns, or request an owner-provided image. Do not invent product photography or
  a logo.
- AI-generated backgrounds or illustrations are optional. Enable them only after a
  provider's no-charge allowance is verified, or after explicit paid opt-in; never
  assume a hosted image API is free.

## Live verification procedure

1. The owner selects one provider mode and supplies its key through server-side secret
   storage, never source control or test output.
2. Verify project billing/free-tier eligibility, model access, terms, and quota in the
   provider console; record the date and model here without recording credentials.
3. Submit only public approved brand facts in `gemini_free`; reject private or
   identifying content before transport.
4. Run one bounded Hermes tool workflow, record returned model, usage, status, and
   estimated cost, then disable the key again unless continued use was approved.
5. Do not fall back to another provider or a paid mode after quota/auth failure.
