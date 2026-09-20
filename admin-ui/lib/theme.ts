/**
 * The colour theme: which palette a browser shows, and who decides (Phase 6.6, ADR-031).
 *
 * Three layers, narrowest first:
 *
 * 1. The administrator's **lock**. When the theme is locked, the default applies to
 *    every browser and the picker is hidden.
 * 2. The person's **own choice**, remembered per browser in `localStorage`.
 * 3. The deployment's **default**: the console's `ui.theme` over
 *    `GREENLIGHT_AI_UI_THEME` in `.env` over the brand palette (ADR-023).
 *
 * The server reads the default and the lock from the API at request time, so a change
 * in the console shows on the next page load with no rebuild, and falls back to the
 * environment when the API is unreachable. Each palette has a light and a dark
 * variant; the sun/moon toggle switches between them. Adding a palette is one block
 * of tokens in `globals.css` and one entry here, plus the same in the API registry.
 */

export const PALETTES = [
  "classic-teal-navy",
  "classic-teal",
  "light-blue-yellow",
  "default",
] as const;

export type Palette = (typeof PALETTES)[number];

/** What the picker calls each palette. */
export const PALETTE_LABELS: Record<Palette, string> = {
  "classic-teal-navy": "Teal · navy rail",
  "classic-teal": "Teal",
  "light-blue-yellow": "Blue · yellow",
  default: "Slate",
};

/** The palette a deployment gets when it says nothing: the brand one, chosen 2026-09-19. */
export const DEFAULT_PALETTE: Palette = "classic-teal-navy";

/** Where a browser remembers its own choice. */
export const PALETTE_STORAGE_KEY = "greenlight-ai-palette";

/** What the API says about appearance, and what the server passes the client. */
export interface Appearance {
  theme: Palette;
  locked: boolean;
}

/** Narrow a value to a known palette, falling back to the brand one. */
export function pickPalette(value: string | undefined): Palette {
  const trimmed = (value ?? "").trim().toLowerCase();
  return (PALETTES as readonly string[]).includes(trimmed) ? (trimmed as Palette) : DEFAULT_PALETTE;
}

/** The palette this process was configured with, from the environment alone. */
export function configuredPalette(): Palette {
  return pickPalette(process.env.GREENLIGHT_AI_UI_THEME);
}

/** The palette `step` places after `current`, wrapping at either end. */
export function nextPalette(current: Palette, step: 1 | -1): Palette {
  const index = PALETTES.indexOf(current);
  const count = PALETTES.length;
  return PALETTES[(index + step + count) % count];
}

/** Read one appearance answer, whatever shape the API sent. */
export function parseAppearance(body: unknown, fallback: Palette): Appearance {
  const record = body && typeof body === "object" ? (body as Record<string, unknown>) : {};
  const raw = typeof record.theme === "string" ? record.theme.trim().toLowerCase() : "";
  return {
    theme: (PALETTES as readonly string[]).includes(raw) ? (raw as Palette) : fallback,
    locked: record.locked === true,
  };
}

/**
 * The deployment's appearance, read on the server at request time.
 *
 * Falls back to the environment when the API does not answer within a moment, so a
 * page never waits on the API to choose its colours.
 */
export async function fetchAppearance(): Promise<Appearance> {
  const fallback: Appearance = { theme: configuredPalette(), locked: false };
  const base = process.env.GREENLIGHT_AI_API_URL ?? "http://127.0.0.1:8000";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 1500);
  try {
    const response = await fetch(`${base}/api/v1/appearance`, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) return fallback;
    return parseAppearance(await response.json(), fallback.theme);
  } catch {
    return fallback;
  } finally {
    clearTimeout(timer);
  }
}
