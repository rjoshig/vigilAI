/**
 * The colour theme, chosen by the deployment.
 *
 * Read from `GREENLIGHT_AI_UI_THEME` on the server at request time, so a change in `.env`
 * shows up on the next page load with no rebuild. It is deliberately not a
 * `NEXT_PUBLIC_*` variable: those are inlined into the client bundle at build time,
 * which would make the theme a build decision rather than a configuration one.
 *
 * Each palette has a light and a dark variant; the sun/moon toggle in the sidebar still
 * switches between them. Adding a palette is one block of tokens in `globals.css` and
 * one entry here. The palettes and their token values come from `compare-file/ui2`, so
 * the two tools read the same way.
 */

export const PALETTES = [
  "default",
  "light-blue-yellow",
  "classic-teal",
  "classic-teal-navy",
] as const;

export type Palette = (typeof PALETTES)[number];

/** The palette a deployment gets when it says nothing: the brand one, chosen 2026-09-19. */
export const DEFAULT_PALETTE: Palette = "classic-teal-navy";

/** Narrow an environment value to a known palette, falling back to the brand one. */
export function pickPalette(value: string | undefined): Palette {
  const trimmed = (value ?? "").trim().toLowerCase();
  return (PALETTES as readonly string[]).includes(trimmed) ? (trimmed as Palette) : DEFAULT_PALETTE;
}

/** The palette this process was configured with. */
export function configuredPalette(): Palette {
  return pickPalette(process.env.GREENLIGHT_AI_UI_THEME);
}
