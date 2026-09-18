"use client";

import { ThemeProvider as NextThemeProvider } from "next-themes";
import * as React from "react";

/** Dark mode via next-themes, with the class strategy Tailwind is configured for. */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
      {children}
    </NextThemeProvider>
  );
}
