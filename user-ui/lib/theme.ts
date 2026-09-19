/**
 * The colour theme, chosen by the deployment.
 *
 * Read from `VIGILAI_UI_THEME` on the server at request time, so a change in `.env`
 * shows up on the next page load with no rebuild. It is deliberately not a
 * `NEXT_PUBLIC_*` variable: those are inlined into the client bundle at build time,
 * which would make the theme a build decision rather than a configuration one.
 *
 * Each palette has a light and a dark variant; the sun/moon toggle in the sidebar still
 * switches between them. Adding a palette is one block of tokens in `globals.css` and
 * one entry here. The palettes and their token values come from `compare-file/ui2`, so
 * the two tools read the same way.
 */

export const PALETTES = ["default", "light-blue-yellow", "classic-teal"] as const;

export type Palette = (typeof PALETTES)[number];

/** Narrow an environment value to a known palette, falling back to the default. */
export function pickPalette(value: string | undefined): Palette {
  const trimmed = (value ?? "").trim().toLowerCase();
  return (PALETTES as readonly string[]).includes(trimmed) ? (trimmed as Palette) : "default";
}

/** The palette this process was configured with. */
export function configuredPalette(): Palette {
  return pickPalette(process.env.VIGILAI_UI_THEME);
}
