# Browser tests

End-to-end tests over both apps, driven through a real browser against a real API, a
real worker, and a throwaway database. They cover the things a unit test cannot: that
the screens render what the API returns, that a decision reaches the server, and that
the finalize gate refuses in the browser and not only in a test client.

Nothing here reaches a model. `LLM_PROVIDER=mock` and the scripted stand-in
(`scripts/synthetic_model.py`) answer every stage (ADR-003, ADR-014), and the fixtures
are synthetic.

## Running them

```bash
cd e2e
npm ci
npx playwright install chromium   # once, unless the environment already has one
npx playwright test
```

Playwright starts the API and both apps itself. `global-setup.ts` seeds a throwaway
database with `scripts/seed_demo.py` and starts the worker, which has no URL for
Playwright to poll; `global-teardown.ts` stops it.

Two environment variables matter:

| Variable       | What it is for                                                                                                      |
| -------------- | ------------------------------------------------------------------------------------------------------------------- |
| `E2E_PYTHON`   | The interpreter with the package installed. Defaults to the repo's `.venv`.                                         |
| `E2E_CHROMIUM` | A browser that already exists, so the run does not download one. Leave unset to use the browser Playwright manages. |

The database and uploaded files go to `.e2e-data/`, which is wiped at the start of every
run: these tests finalize runs and approve rules, and both are one-way.

## What they cover

| File                  | What it proves                                                                                                                                                                                                                                                          |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `user-review.spec.ts` | The runs list shows every lifecycle state; a run shows its matrix, coverage and findings; the three decisions exist; Not OK on a high finding is refused without a comment; the evidence drawer opens; a frozen report serves and says what was checked; drift appears. |
| `finalize.spec.ts`    | The whole gate (ADR-035): decide every finding, acknowledge every coverage gap, read the confirmation, freeze, and find the run frozen afterwards.                                                                                                                      |
| `admin.spec.ts`       | Every admin screen loads with no page error; the rules screen filters to active; a state change asks for the word to be typed; a setting says which layer it came from.                                                                                                 |
| `appearance.spec.ts`  | The four palettes apply; the runs and review screens have no horizontal scroll at phone width; the admin launcher points at the admin app.                                                                                                                              |

## Conventions worth keeping

- **One worker, in order.** Every test shares one seeded database, and freezing a run
  changes what the next test would see. Determinism beats the wall clock here.
- **`finalize.spec.ts` owns run 5 alone**, because finalizing is one-way.
- **Assert outcomes, not transient text.** A decision is confirmed by the card's
  `data-review-status`, not by a message that appears and clears. The production code
  carries `data-testid`, `data-severity`, `data-finding` and `data-review-status` on a
  finding card for exactly this.
- **The screens read their run when they mount.** They do not promise to live-update, so
  a test that changes state and then checks a screen reloads it rather than asserting
  something the app never claimed.
