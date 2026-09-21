"use client";

/**
 * Try this setup against the samples, before a real delivery does (Phase 6.21f).
 *
 * Until this, the only way to find out whether an artifact type, a guide, a meaning
 * entry or a check actually fired was for somebody else to submit a real delivery. The
 * feedback loop ran through another person's working day, which is why setups drift.
 *
 * Three questions, in the order somebody setting up would ask them: can the tool read
 * these files, do the pointers point at anything, and would the checks run. The answer
 * to the third is never a verdict about a delivery — a check that fails against a
 * *sample* has found nothing wrong with anything, and wording it as a failure would
 * teach an administrator to distrust the whole screen.
 *
 * It calls no model and stores nothing, which is what makes it safe to press while
 * editing, and the card says so rather than leaving it to be assumed.
 */

import { AlertTriangle, Check, FlaskConical, Minus, X } from "lucide-react";
import * as React from "react";

import { ScopePicker } from "@/components/scope-picker";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { Rehearsal, Scope } from "@/lib/types";

export function RehearsalCard({ onError }: { onError?: (message: string) => void }) {
  const [result, setResult] = React.useState<Rehearsal | null>(null);
  const [programmes, setProgrammes] = React.useState<Scope[] | null>(null);
  const [scope, setScope] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    api
      .listScopes()
      .then(setProgrammes)
      .catch(() => setProgrammes([]));
  }, []);

  async function run() {
    setBusy(true);
    try {
      setResult(await api.rehearse(scope));
    } catch (caught) {
      onError?.(
        caught instanceof ApiError ? caught.detail : "Could not try the setup against the samples."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card data-testid="rehearsal-card">
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4" />
          Try this setup
        </CardTitle>
        <div className="flex items-center gap-2">
          <ScopePicker
            idPrefix="rehearse-scope"
            programmes={programmes}
            value={scope}
            onChange={setScope}
            disabled={busy}
          />
          <Button size="xs" onClick={() => void run()} disabled={busy}>
            {busy ? "Trying…" : "Try it"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="pt-3 text-xs">
        <p className="mb-3 text-muted-foreground">
          Runs everything code can run against the sample workbooks already stored, and says what
          happened. <b>No AI is called and nothing is saved</b>, so press it as often as you like
          while you work.
        </p>

        {result === null ? (
          <p className="py-6 text-center text-muted-foreground">
            Nothing tried yet. Press <b>Try it</b> to see what this setup would do.
          </p>
        ) : (
          <div className="grid gap-4">
            <Section title="What it read">
              {result.artifacts.length === 0 ? (
                <Empty>No artifact type has a sample stored for this scope.</Empty>
              ) : (
                result.artifacts.map((artifact) => (
                  <div key={artifact.key} className="rounded-md border bg-card p-2">
                    <div className="flex flex-wrap items-center gap-2">
                      {artifact.error ? <Mark ok={false} /> : <Mark ok />}
                      <b>{artifact.label}</b>
                      <Badge tone="muted">
                        {artifact.sample_count} sample{artifact.sample_count === 1 ? "" : "s"}
                      </Badge>
                    </div>
                    {artifact.error ? (
                      <p className="mt-1 text-destructive">{artifact.error}</p>
                    ) : (
                      <>
                        <p className="mt-1 text-muted-foreground">
                          Sheets: {artifact.sheets.join(", ") || "none"}
                        </p>
                        {Object.entries(artifact.resolved).map(([wanted, found]) => (
                          <p key={wanted} className="mt-0.5">
                            The checks look for <b>{wanted}</b> and found <b>{found}</b>
                            {wanted === found ? "" : " — read by name, in code"}.
                          </p>
                        ))}
                        {artifact.unresolved.map((wanted) => (
                          <p key={wanted} className="mt-0.5 text-warn">
                            The checks look for <b>{wanted}</b> and nothing here matches it. On a
                            real delivery the AI would be asked which sheet was meant; recording the
                            answer on this type&rsquo;s Layout makes it certain.
                          </p>
                        ))}
                      </>
                    )}
                  </div>
                ))
              )}
            </Section>

            <Section title="What the pointers found">
              {result.named_values.length === 0 ? (
                <Empty>No named values defined yet.</Empty>
              ) : (
                result.named_values.map((pointer) => (
                  <div key={pointer.name} className="flex flex-wrap items-center gap-2">
                    <Mark ok={pointer.found} />
                    <span className="mono">{pointer.name}</span>
                    {pointer.found ? (
                      <b>{pointer.value}</b>
                    ) : (
                      <span className="text-warn">not found in the samples</span>
                    )}
                    {pointer.description ? (
                      <span className="text-muted-foreground">· {pointer.description}</span>
                    ) : null}
                  </div>
                ))
              )}
            </Section>

            <Section title="What the checks would do">
              {result.checks.length === 0 ? (
                <Empty>No checks defined yet.</Empty>
              ) : (
                result.checks.map((check) => (
                  <div key={check.name} className="rounded-md border bg-card p-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Mark ok={check.passed} />
                      <span className="mono">{check.name}</span>
                      {check.shadow ? <Badge tone="muted">in shadow</Badge> : null}
                      {check.expression ? (
                        <span className="text-muted-foreground">{check.expression}</span>
                      ) : null}
                    </div>
                    <p className="mt-1 text-muted-foreground">{check.detail}</p>
                  </div>
                ))
              )}
              <p className="mt-1 text-muted-foreground">
                A check that does not hold <b>against a sample</b> has found nothing wrong with
                anything — the samples are specimens, not deliveries. It tells you the check runs.
              </p>
            </Section>

            {result.notes.map((note) => (
              <p key={note} className="flex items-start gap-1.5 text-muted-foreground">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>{note}</span>
              </p>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <p className="text-xs font-semibold">{title}</p>
      {children}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-muted-foreground">{children}</p>;
}

/** Yes, no, or "the question did not arise" — which is never shown as a no. */
function Mark({ ok }: { ok: boolean | null }) {
  if (ok === null) return <Minus className="h-3.5 w-3.5 text-muted-foreground" />;
  return ok ? (
    <Check className="h-3.5 w-3.5 text-success" />
  ) : (
    <X className="h-3.5 w-3.5 text-warn" />
  );
}
