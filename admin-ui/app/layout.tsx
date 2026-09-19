import type { Metadata } from "next";

import { AppShell } from "@/components/app-shell";
import { AuthGate } from "@/components/auth-gate";
import { ThemeProvider } from "@/components/theme-provider";
import { configuredPalette } from "@/lib/theme";

import "./globals.css";

export const metadata: Metadata = {
  title: "vigilAI — Admin",
  description:
    "Report templates, named values, cross-report checks, compliance rules, reference data, and usage.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // data-theme picks the palette; next-themes toggles .dark on top of it.
    <html lang="en" data-theme={configuredPalette()} suppressHydrationWarning>
      <body>
        <ThemeProvider>
          <AuthGate>
            <AppShell>{children}</AppShell>
          </AuthGate>
        </ThemeProvider>
      </body>
    </html>
  );
}
