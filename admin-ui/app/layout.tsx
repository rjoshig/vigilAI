import type { Metadata } from "next";

import { AppShell } from "@/components/app-shell";
import { AuthGate } from "@/components/auth-gate";
import { PaletteProvider } from "@/components/palette-provider";
import { ThemeProvider } from "@/components/theme-provider";
import { fetchAppearance } from "@/lib/theme";

import "./globals.css";

export const metadata: Metadata = {
  title: "Greenlight AI — Admin",
  description:
    "Report templates, named values, cross-report checks, compliance rules, reference data, and usage.",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // The default and the lock come from the API (console over .env), read per request.
  const appearance = await fetchAppearance();
  return (
    // data-theme picks the palette; next-themes toggles .dark on top of it.
    <html lang="en" data-theme={appearance.theme} suppressHydrationWarning>
      <body>
        <ThemeProvider>
          <PaletteProvider initial={appearance}>
            <AuthGate>
              <AppShell>{children}</AppShell>
            </AuthGate>
          </PaletteProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
