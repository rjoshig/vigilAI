/**
 * The Greenlight AI mark: a traffic signal with the green lit.
 *
 * The shapes and colours are the brand's and are fixed here on purpose. They do not
 * follow the theme tokens, because the mark has to read the same in every palette
 * and in dark mode; the box behind it, not the mark, is what adapts.
 */

import * as React from "react";

//: The artwork's own proportions. Width follows from the height.
const VIEW_W = 130;
const VIEW_H = 330;

//: The lit light gets a glow only when the mark is shown large. At header size a
//: blur just muddies a 30px shape.
const GLOW_MIN_SIZE = 64;

export interface LogoProps {
  /** Rendered height in pixels. Header use is about 28 to 32. */
  size?: number;
  /** Soft green glow around the lit light. Ignored below 64px, where it only blurs. */
  glow?: boolean;
  /** An accessible name. Omit when a visible wordmark sits beside the mark. */
  title?: string;
  className?: string;
}

export function Logo({ size = 32, glow = false, title, className }: LogoProps) {
  const width = Math.round((size * VIEW_W) / VIEW_H);
  const showGlow = glow && size >= GLOW_MIN_SIZE;
  const filterId = React.useId();

  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      width={width}
      height={size}
      xmlns="http://www.w3.org/2000/svg"
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      className={className}
      focusable="false"
    >
      {title ? <title>{title}</title> : null}
      {showGlow ? (
        <defs>
          <filter id={filterId} x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="18" />
          </filter>
        </defs>
      ) : null}
      <rect
        x="2"
        y="2"
        width="126"
        height="326"
        rx="20"
        fill="#0A1A15"
        stroke="#2A4A3E"
        strokeWidth="4"
      />
      <circle cx="65" cy="65" r="40" fill="#5A2525" />
      <circle cx="65" cy="165" r="40" fill="#5C4520" />
      {showGlow ? (
        <circle cx="65" cy="265" r="40" fill="#1FA463" opacity="0.7" filter={`url(#${filterId})`} />
      ) : null}
      <circle cx="65" cy="265" r="40" fill="#1FA463" stroke="#7EE0AE" strokeWidth="5" />
    </svg>
  );
}
