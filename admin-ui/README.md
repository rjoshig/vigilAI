# admin-ui

The operator-facing app: report templates, named values, cross-report checks, compliance
rules, reference data, and usage. Same toolchain and theme as `user-ui` (ADR-011), but a
**separate app on :3001** with its own URL. The two never import each other; shared code
is duplicated deliberately until an ADR says otherwise.

There is no login in v1 (ADR-008). The separation is the URL, and the API's single auth
dependency is the hook for adding one later.

## Screens

| Route         | What it does                                                                                                                     |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `/templates`  | Upload one sample workbook per report type; define named values and see what each resolves to on the sample                      |
| `/checks`     | Describe a check in plain English, correct the proposal, test it against the samples, activate it. Versioned, scoped, switchable |
| `/compliance` | Must-have compliance rules, and which config categories the reverse pass checks                                                  |
| `/reference`  | Attribute aliases and masked columns                                                                                             |
| `/usage`      | Runs, durations, tokens, cache hit rate, false-positive rate, findings by type                                                   |

## The one model call

`POST /admin/checks/draft` is the only LLM call in the admin flow, and it happens once
per check. After activation the check runs as code on every request at no token cost.
Testing a check never calls the model.

## Running it

```bash
npm install
npm run dev                 # http://localhost:3001
```

It talks to `/api/*`, rewritten to `GREENLIGHT_AI_API_URL` (default `http://127.0.0.1:8000`).

## Gates

```bash
npm run lint
npm run typecheck
npm run format:check
npm test
npm run build
```
