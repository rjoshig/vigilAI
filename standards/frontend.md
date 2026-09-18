# Frontend Standards

Applies to the two Next.js apps, **`user-ui/`** (associates) and **`admin-ui/`** (operators,
its own URL and port), and to the static **`mock/`**. Stack, per ADR-011: the
`compare-file/ui2` toolchain (npm, Next.js 15 App Router, React 18, TypeScript strict,
Tailwind CSS 3, ESLint 8 `next/core-web-vitals`, Prettier with the Tailwind plugin) **plus
Vitest + Testing Library** for unit tests. Adapted from `compare-file/standards/frontend.md`.

> Both apps share one theme: the `compare-file/ui2` tokens (`config/theme.json`,
> `config/brand.json`, HSL CSS variables, `next-themes` dark mode). The final HTML report
> follows the compare-file report format. `docs/design.md` "UI and report" is the screen list.

## Tooling contract

All must be **clean before every commit** (run from the app directory):

```bash
npm run lint          # ESLint (next/core-web-vitals + TypeScript rules)
npm run typecheck     # tsc --noEmit
npm run format:check  # Prettier
npm test              # Vitest (run mode)
npm run build         # production build
```

- ESLint is enforced at build time; keep `eslint.ignoreDuringBuilds` off.
- `npm run format` auto-fixes formatting.
- Scripts every app must define: `dev`, `build`, `start`, `lint`, `typecheck`, `format`,
  `format:check`, `test`, `test:watch`.

## TypeScript

- **Keep `strict: true`.** Do not loosen compiler options.
- **No `any`.** Use `unknown` + narrowing, generics, or a precise type. A scoped
  `// @ts-expect-error` with a reason is acceptable in rare cases.
- **Explicit prop interfaces** for every component (`interface FooProps { ... }`).
- Use the **`@/*` path alias** for intra-app imports.
- Share domain types from **`lib/types.ts`**, mirroring the FastAPI Pydantic models (runs,
  findings, rules, traces, checks). Don't redefine the same shape twice.

## Next.js (App Router)

- **Server Components by default.** Add `"use client"` only for state, effects, refs,
  browser APIs, or event handlers, and push it to the leaf.
- Keep `reactStrictMode: true`.
- **Preserve the `/api/*` rewrite proxy** in `next.config.mjs` (target `VIGILAI_API_URL`,
  default `http://127.0.0.1:8000`) so the browser never hits CORS against FastAPI.
- `user-ui` serves on **:3000**, `admin-ui` on **:3001**. They never import each other.
  Shared code is duplicated deliberately (two small apps) until an ADR says otherwise.

## Components

- Functional components + hooks only. **Files are `kebab-case`**, components `PascalCase`.
  Pages use `default export`; shared components use **named exports**.
- Compose class names with the **`cn()` helper** (clsx + tailwind-merge).
- Keep components small; lift editor logic into `lib/*-editor.ts` as ui2 does.
- UI primitives under `components/ui/` are lightweight, shadcn-styled, dependency-free
  local components (copy from ui2).

## API layer

- **All backend calls go through the typed client in `lib/api.ts`.** No raw `fetch` in
  components.
- Run progress is **polling `GET /api/v1/runs/{id}` every 3 s** (`docs/design.md`), no
  WebSockets.
- Calls use `cache: "no-store"`; run/finding data is never cached client-side.

## Styling

- **Tailwind utility-first.** Theme tokens from `lib/theme.ts` and the HSL CSS variables;
  no hardcoded hex colors in components. Dark mode via `next-themes`.

## State & data

- Local component state and hooks; **no global state library** without an ADR.
- Review decisions (OK / Not OK + comment) are sent immediately via `PATCH
  /api/v1/findings/{id}`; the UI never batches them locally.

## PII on screen

- Sample rows shown in the review screen and the final report are **already masked by the
  backend** (ADR-003). The frontend never unmasks and never receives unmasked values.
  There is no unmask control in v1.

## Testing (Vitest)

- `vitest` + `@testing-library/react` + `happy-dom`; config in `vitest.config.ts`.
- One `*.test.tsx` per component or lib module with logic; pure render-only components
  may skip tests. Test the review flow, the traceability matrix filters, and the API client
  error handling at minimum.
- No network in tests: mock `lib/api.ts`.

## mock/

Same approach as `compare-file/ui-mock/`: **static HTML + one shared `styles.css` + one shared
`app.js`** under `mock/shared/`, with `mock/user-ui/` and `mock/admin-ui/` as separate apps (ADR-013),
opens from `file://`, no build, no backend. It mirrors the ui2 tokens so the mock and the
apps look the same. It is a throwaway artifact for stakeholder review (Phase 1) and is not
linted by the app toolchains.

## Accessibility & performance

- Semantic HTML; keyboard navigation and visible focus for dialogs, menus, and forms.
- `alt` text and accessible names for icon-only buttons (`lucide-react`).
- Keep heavy libs (charts) in client components loaded only where needed.
