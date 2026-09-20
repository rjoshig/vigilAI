/**
 * Every theme must keep text readable and the severity colours apart (Phase 6.6a).
 *
 * A finding's severity is carried by colour, so a palette that flattens it is a
 * defect, not a preference. The tokens are read straight from globals.css, so a new
 * palette is checked the moment it is added.
 *
 * Thresholds: body text 4.5:1 (WCAG AA). Brand surfaces 2.5:1, a floor beneath the
 * compare-file values the user chose (white on the teal-blue is 2.85:1), so a new
 * palette cannot go lower without this failing. Severity colours: each at least 2:1
 * against the page, and hues at least 30° apart from one another, because amber and
 * green share a luminance and are told apart by hue and by the label beside them.
 * Thirty degrees is the gap between the shipped red and amber (0° and 38°) with room
 * to spare, and far less than any two of the four share.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { PALETTES } from "./theme";

const css = readFileSync(resolve(__dirname, "../app/globals.css"), "utf8");

/** The tokens declared inside one selector block, as `--name: h s% l%`. */
function tokens(selector: string): Record<string, string> {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  const out: Record<string, string> = {};
  for (const line of (match?.[1] ?? "").split("\n")) {
    const pair = line.match(/--([a-z-]+):\s*([^;]+);/);
    if (pair) out[pair[1]] = pair[2].trim();
  }
  return out;
}

function luminance(hsl: string): number {
  const [h, s, l] = hsl.split(/\s+/).map((part) => parseFloat(part));
  const sat = s / 100;
  const light = l / 100;
  const c = (1 - Math.abs(2 * light - 1)) * sat;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = light - c / 2;
  const sector = Math.floor(h / 60) % 6;
  const [r1, g1, b1] = [
    [c, x, 0],
    [x, c, 0],
    [0, c, x],
    [0, x, c],
    [x, 0, c],
    [c, 0, x],
  ][sector];
  const channel = (v: number) => {
    const srgb = v + m;
    return srgb <= 0.03928 ? srgb / 12.92 : Math.pow((srgb + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * channel(r1) + 0.7152 * channel(g1) + 0.0722 * channel(b1);
}

function hue(hsl: string): number {
  return parseFloat(hsl.split(/\s+/)[0]);
}

function hueGap(a: string, b: string): number {
  const gap = Math.abs(hue(a) - hue(b)) % 360;
  return Math.min(gap, 360 - gap);
}

function contrast(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const base = { light: tokens(":root"), dark: tokens(".dark") };

function palette(name: string, mode: "light" | "dark"): Record<string, string> {
  const own =
    name === "default"
      ? {}
      : tokens(`[data-theme="${name}"]${mode === "dark" ? ".dark" : ":not(.dark)"}`);
  return { ...base[mode], ...own };
}

describe("every palette keeps text readable", () => {
  for (const name of PALETTES) {
    for (const mode of ["light", "dark"] as const) {
      const t = palette(name, mode);
      it(`${name} (${mode}): body text and the brand surfaces`, () => {
        expect(contrast(t.foreground, t.background)).toBeGreaterThanOrEqual(4.5);
        for (const surface of ["primary", "secondary", "tertiary", "accent"]) {
          expect(
            contrast(t[surface], t[`${surface}-foreground`]),
            `${surface}-foreground on ${surface}`
          ).toBeGreaterThanOrEqual(2.5);
        }
      });
      it(`${name} (${mode}): the severity colours stand out and apart`, () => {
        const severities = ["destructive", "warn", "info", "success"];
        for (const one of severities) {
          expect(contrast(t[one], t.background), `${one} on the page`).toBeGreaterThanOrEqual(2);
        }
        for (const [i, one] of severities.entries()) {
          for (const other of severities.slice(i + 1)) {
            expect(hueGap(t[one], t[other]), `${one} vs ${other}`).toBeGreaterThanOrEqual(30);
          }
        }
      });
    }
  }
});
