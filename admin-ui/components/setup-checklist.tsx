"use client";

/**
 * An order through the screens (Phase 6.21f).
 *
 * The console is fifteen screens and every one of them is good. What it has never had
 * is a *path*: somebody setting up a new delivery has to already know that an artifact
 * type comes before a sample, a sample before a named value, and a named value before
 * a check that refers to one. That knowledge lived in the training document and in
 * whoever set up the last one.
 *
 * This is a checklist, not a wizard. It hides nothing, forces no order, and every step
 * is a link to the screen that already does the job — because the screens are not the
 * problem. It reads what exists and says which steps are done, so somebody can see
 * where they are rather than remember.
 *
 * Each step says **why** it matters, not only what it is. "Upload a sample" is an
 * instruction; "without one the tool cannot tell which report is which, and no check
 * can be tested before a real delivery meets it" is a reason, and a reason is what
 * makes somebody do the step properly rather than tick it.
 */

import { ArrowRight, Check, Circle } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import type { ArtifactType } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Step {
  title: string;
  why: string;
  href: string;
  done: boolean;
  detail: string;
}

export function SetupChecklist({ types }: { types: ArtifactType[] }) {
  const [counts, setCounts] = React.useState<{
    programmes: number;
    checks: number;
    meaning: number;
  } | null>(null);

  React.useEffect(() => {
    // Each independently: a screen that cannot count its checks should still show the
    // rest of the path rather than nothing.
    void Promise.allSettled([api.listScopes(), api.listChecks(), api.listMeaning()]).then(
      ([programmes, checks, meaning]) =>
        setCounts({
          programmes: programmes.status === "fulfilled" ? programmes.value.length : 0,
          checks: checks.status === "fulfilled" ? checks.value.length : 0,
          meaning: meaning.status === "fulfilled" ? meaning.value.length : 0,
        })
    );
  }, []);

  const reports = types.filter((type) => type.kind === "report" && type.is_active);
  const withSamples = reports.filter((type) => type.samples.length > 0);
  const withGuide = reports.filter((type) => type.guide.length > 0);
  const withLayout = reports.filter((type) => type.layout.length > 0);

  const steps: Step[] = [
    {
      title: "Say which reports the delivery has",
      why: "Nothing can be checked in a file the tool does not know it should expect.",
      href: "/artifacts",
      done: reports.length > 0,
      detail: `${reports.length} report type${reports.length === 1 ? "" : "s"} switched on`,
    },
    {
      title: "Upload a sample of each",
      why:
        "Without one the tool cannot tell which uploaded workbook is which, and nothing " +
        "below this can be tried before a real delivery meets it.",
      href: "/artifacts",
      done: withSamples.length === reports.length && reports.length > 0,
      detail: `${withSamples.length} of ${reports.length} have a sample`,
    },
    {
      title: "Record what this delivery calls things",
      why:
        "Only where the words differ. Spelling, separators and plurals are already " +
        "handled, so most deliveries need nothing here — and the AI offers what it had " +
        "to read for you.",
      href: "/artifacts",
      done: true,
      detail:
        withLayout.length > 0
          ? `${withLayout.length} type${withLayout.length === 1 ? "" : "s"} have a layout recorded`
          : "nothing recorded, which is the ordinary state",
    },
    {
      title: "Explain what the numbers mean",
      why:
        "A guide entry tells the AI what a cell is for, and one with a configuration " +
        "path behind it becomes a check on its own.",
      href: "/artifacts",
      done: withGuide.length > 0,
      detail: `${withGuide.length} type${withGuide.length === 1 ? "" : "s"} have a guide`,
    },
    {
      title: "Map the requirements to the configuration",
      why:
        "The AI proposes the links, you confirm them, and code compiles the confirmed " +
        "ones into checks. This is the step that makes findings traceable.",
      href: "/meaning",
      done: (counts?.meaning ?? 0) > 0,
      detail: counts ? `${counts.meaning} entr${counts.meaning === 1 ? "y" : "ies"}` : "…",
    },
    {
      title: "Write the checks a formula can express",
      why: "They cost no AI call and run on every delivery, so they are the cheapest thing here.",
      href: "/checks",
      done: (counts?.checks ?? 0) > 0,
      detail: counts ? `${counts.checks} check${counts.checks === 1 ? "" : "s"}` : "…",
    },
    {
      title: "Set up the delivery programmes",
      why:
        "A programme carries the standing instructions the AI reads on every run in it, " +
        "and the rules code grades against.",
      href: "/scopes",
      done: (counts?.programmes ?? 0) > 0,
      detail: counts ? `${counts.programmes} programme${counts.programmes === 1 ? "" : "s"}` : "…",
    },
  ];

  const done = steps.filter((step) => step.done).length;

  return (
    <Card data-testid="setup-checklist">
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle>Setting up a new delivery</CardTitle>
        <Badge tone={done === steps.length ? "success" : "muted"}>
          {done} of {steps.length}
        </Badge>
      </CardHeader>
      <CardContent className="pt-3 text-xs">
        <p className="mb-3 text-muted-foreground">
          The order these are usually done in. Nothing here forces anything — every step is a screen
          you can go to whenever you like, and a step that says it is done can still be worth
          another look.
        </p>
        <ol className="grid gap-2">
          {steps.map((step, index) => (
            <li key={step.title} className="flex gap-2.5 rounded-md border bg-card p-2">
              <span className="mt-0.5 shrink-0">
                {step.done ? (
                  <Check className="h-4 w-4 text-success" />
                ) : (
                  <Circle className="h-4 w-4 text-muted-foreground" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <Link
                  href={step.href}
                  className={cn(
                    "flex items-center gap-1 font-medium hover:underline",
                    !step.done && "text-primary"
                  )}
                >
                  {index + 1}. {step.title}
                  <ArrowRight className="h-3 w-3" />
                </Link>
                <p className="text-muted-foreground">{step.why}</p>
                <p className="mt-0.5 text-muted-foreground">{step.detail}</p>
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
