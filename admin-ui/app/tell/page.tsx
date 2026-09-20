"use client";

/**
 * Tell the tool: say what you want checked, in your own words (Phase 6.12b).
 *
 * There are sixteen places in this console where an administrator can tell the tool
 * something, and each is the right home for what it holds. Nobody new can be expected
 * to pick. So this page asks for a sentence and lets the model decide which of those
 * surfaces it belongs on; the drafting, the validation and the approval are the ones
 * the training queue already uses.
 *
 * This is not a replacement for those screens. They are the expert view and they stay:
 * what lands here is a candidate in the ordinary queue, one click away, and that is
 * where things are really managed.
 */

import { ArrowRight, Lightbulb } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EVERYWHERE, ScopePicker, scopeIsComplete } from "@/components/scope-picker";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ErrorState,
  Label,
  PageHeader,
  Textarea,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { FrontDoorResult, Scope } from "@/lib/types";

/** What each surface is called on the screens that own it. */
const SURFACE_LABEL: Record<string, string> = {
  field_constraint: "Field constraint",
  check: "Check",
  compliance_rule: "Compliance rule",
  background: "Background",
  unclear: "Not placed",
};

/** Where to go to see what it became, or where it should go instead. */
const SURFACE_HREF: Record<string, string> = {
  field_constraint: "/training",
  check: "/training",
  compliance_rule: "/training",
  background: "/artifacts",
};

const SURFACE_TONE: Record<string, "success" | "warn" | "info" | "muted"> = {
  field_constraint: "success",
  check: "success",
  compliance_rule: "success",
  background: "info",
  unclear: "warn",
};

const EXAMPLES = [
  "The account review file must never have a blank origination date.",
  "Billing count must never exceed the delivered count.",
  "Every configuration has to switch on the deceased suppression.",
];

export default function TellPage() {
  const [statement, setStatement] = React.useState("");
  const [scope, setScope] = React.useState(EVERYWHERE);
  const [programmes, setProgrammes] = React.useState<Scope[] | null>(null);
  const [result, setResult] = React.useState<FrontDoorResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    api
      .listScopes()
      .then(setProgrammes)
      .catch(() => {
        // Without the programme list the scope control still offers everywhere and one
        // customer, which is more useful than an error over something optional.
      });
  }, []);

  async function send() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.tellTheTool(statement.trim(), scope));
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.detail : "The tool could not read that statement."
      );
    } finally {
      setBusy(false);
    }
  }

  const ready = statement.trim().length > 0 && scopeIsComplete(scope) && !busy;

  return (
    <>
      <PageHeader
        title="Tell the tool"
        description="Write one thing you want checked, in your own words. The tool works out which of its existing surfaces it belongs on and drafts it there, in shadow, for you to confirm. Nothing runs until you approve it."
      />

      <Card className="mb-4">
        <CardHeader className="border-b">
          <CardTitle className="flex items-center gap-2">
            <Lightbulb className="h-4 w-4" /> What should the tool check?
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 pt-4">
          <div className="flex flex-col gap-1">
            <Label htmlFor="front-door-statement">One statement</Label>
            <Textarea
              id="front-door-statement"
              rows={3}
              value={statement}
              placeholder="The account review file must never have a blank origination date."
              onChange={(event) => setStatement(event.target.value)}
            />
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <span>Try:</span>
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                className="underline underline-offset-2 hover:text-foreground"
                onClick={() => setStatement(example)}
              >
                {example}
              </button>
            ))}
          </div>
          <ScopePicker
            value={scope}
            onChange={setScope}
            programmes={programmes}
            idPrefix="front-door"
          />
          <div>
            <Button disabled={!ready} onClick={() => void send()} data-testid="tell-the-tool">
              {busy ? "Reading…" : "Tell the tool"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {error ? <ErrorState message={error} /> : null}

      {result ? (
        <Card data-testid="front-door-result">
          <CardHeader className="border-b">
            <CardTitle className="flex flex-wrap items-center gap-2">
              <Badge tone={SURFACE_TONE[result.surface] ?? "muted"}>
                {SURFACE_LABEL[result.surface] ?? result.surface}
              </Badge>
              <span className="text-sm font-normal text-muted-foreground">{result.reason}</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 pt-4 text-sm">
            {result.question ? (
              <p data-testid="front-door-question">
                <span className="font-medium">The tool asks:</span> {result.question}
              </p>
            ) : null}
            {result.note ? <p className="text-muted-foreground">{result.note}</p> : null}
            {result.candidate ? (
              <div className="flex flex-col gap-1 rounded-md border p-3">
                <div className="font-medium">{result.candidate.name || "Draft rule"}</div>
                <div className="text-muted-foreground">{result.candidate.reasoning}</div>
                <div className="mono text-xs text-muted-foreground">
                  {String(result.candidate.body.expression || "")}
                </div>
              </div>
            ) : null}
            {SURFACE_HREF[result.surface] ? (
              <div>
                <Link href={SURFACE_HREF[result.surface]}>
                  <Button variant="ghost" size="sm">
                    {result.candidate ? "Review it in the queue" : "Go to the screen that holds it"}
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Button>
                </Link>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </>
  );
}
