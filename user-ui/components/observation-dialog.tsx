"use client";

/**
 * Train AI mode: the form a reviewer writes an observation in (ADR-021, 6.1e).
 *
 * An observation never runs. It is a sentence plus the thing it points at; an
 * administrator reviews it and the model drafts a rule they approve. The anchor is
 * prefilled from whatever the person was looking at, because a rule the model can
 * synthesize reliably needs a selection and not only prose.
 */

import { Lightbulb } from "lucide-react";
import { usePathname } from "next/navigation";
import * as React from "react";

import { TrainAiTag } from "@/components/train-ai-tag";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ErrorState,
  Input,
  Label,
  Select,
  Textarea,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type {
  Anchor,
  CoveringRule,
  Observation,
  ObservationInput,
  ObservationKind,
  ObservationScope,
  Severity,
} from "@/lib/types";

const KINDS: { value: ObservationKind; label: string }[] = [
  { value: "reconciliation", label: "Two things should agree" },
  { value: "field_constraint", label: "A field should always look like this" },
  { value: "correction", label: "The tool got something wrong" },
  { value: "note", label: "Something worth knowing" },
];

const SEVERITIES: { value: Severity; label: string }[] = [
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
  { value: "review", label: "Needs a person to look" },
];

const SCOPES: { value: ObservationScope; label: string }[] = [
  { value: "customer", label: "This customer" },
  { value: "programme", label: "This delivery programme" },
  { value: "global", label: "Every run" },
];

/** An empty anchor of a given kind, so the form always sends a complete shape. */
export function anchorOf(kind: Anchor["kind"], fields: Partial<Anchor> = {}): Anchor {
  return {
    kind,
    artifact: "",
    sheet: "",
    cell: "",
    field: "",
    reference: "",
    value: "",
    ...fields,
  };
}

/**
 * Whether Train AI mode is on.
 *
 * Returns false until the answer arrives, so nothing about training is drawn while the
 * switch is unknown and no other training endpoint is called when it is off. The
 * switch is re-read on every navigation, so an administrator flipping it is reflected
 * without a full reload; the server's settings cache means it lags a few seconds at most.
 */
export function useTrainingEnabled(): boolean {
  const [enabled, setEnabled] = React.useState(false);
  const pathname = usePathname();

  React.useEffect(() => {
    let live = true;
    api
      .getTrainingConfig()
      .then((config) => {
        if (live) setEnabled(config.enabled);
      })
      .catch(() => {
        // A deployment without the training endpoint behaves as one with it switched off.
      });
    return () => {
      live = false;
    };
  }, [pathname]);

  return enabled;
}

export interface ObservationDialogProps {
  /** What the person was looking at when they pressed the button. */
  anchors: Anchor[];
  runId?: number | null;
  findingId?: number | null;
  /** What the anchor refers to, in one line, so the person can see what they selected. */
  context?: string;
  /** Set when the form is correcting an observation rather than writing a new one. */
  existing?: Observation;
  onClose: () => void;
  onSaved?: (observation: Observation) => void;
}

export function ObservationDialog({
  anchors,
  runId,
  findingId,
  context,
  existing,
  onClose,
  onSaved,
}: ObservationDialogProps) {
  const [kind, setKind] = React.useState<ObservationKind>(existing?.kind ?? "reconciliation");
  const [statement, setStatement] = React.useState(existing?.statement ?? "");
  const [expectation, setExpectation] = React.useState(existing?.expectation ?? "");
  const [severity, setSeverity] = React.useState<Severity>(existing?.severity_hint ?? "medium");
  // The narrowest scope that fits is the safe default: the usual cause of a noisy rule
  // is an assumption that holds for most records and not all.
  const [scope, setScope] = React.useState<ObservationScope>(existing?.scope_hint ?? "customer");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState(false);
  // What already covers this, returned when it is saved. Shown straight away rather
  // than at the candidate stage, which would be weeks later through an administrator
  // (Phase 6.1e).
  const [coveredBy, setCoveredBy] = React.useState<CoveringRule[]>([]);
  // The row this form is now editing: the one passed in, or the one it just created.
  // Pressing Save a second time used to create a second observation (Phase 6.13a).
  const [current, setCurrent] = React.useState<Observation | undefined>(existing);
  // Anchors are state, because "say the existing rule is wrong" adds one.
  const [pointing, setPointing] = React.useState<Anchor[]>(existing ? existing.anchors : anchors);

  async function save() {
    setSaving(true);
    setError(null);
    const body: ObservationInput = {
      kind,
      anchors: pointing,
      statement: statement.trim(),
      expectation: expectation.trim(),
      severity_hint: severity,
      scope_hint: scope,
      run_id: current ? current.run_id : (runId ?? null),
      finding_id: current ? current.finding_id : (findingId ?? null),
    };
    try {
      const stored = current
        ? await api.updateObservation(current.id, body)
        : await api.createObservation(body);
      setCurrent(stored);
      setSaved(true);
      setCoveredBy(stored.covered_by ?? []);
      onSaved?.(stored);
    } catch (caught) {
      // The 422 text names what to take out before saving, so it is shown as written.
      setError(caught instanceof ApiError ? caught.detail : "Could not save that.");
    } finally {
      setSaving(false);
    }
  }

  /**
   * Start a fresh observation saying that a rule already running is wrong. The panel
   * used to ask for exactly this and offer no way to do it: the only button created a
   * duplicate of what had just been saved.
   */
  function disputeRule(rule: CoveringRule) {
    setCurrent(undefined);
    setSaved(false);
    setCoveredBy([]);
    setKind("correction");
    setStatement(`The rule "${rule.summary}" is wrong: `);
    setExpectation("");
    setPointing([
      ...pointing.filter((anchor) => anchor.kind !== "rule"),
      anchorOf("rule", { reference: `${rule.kind}:${rule.id}`, value: rule.summary }),
    ]);
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="observation-title"
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
    >
      <Card className="w-full max-w-2xl">
        <CardHeader className="border-b">
          <CardTitle id="observation-title" className="flex items-center gap-1.5">
            <Lightbulb className="h-4 w-4 text-primary" />
            {existing ? "Edit your observation" : "What should this check?"}
            <TrainAiTag />
          </CardTitle>
        </CardHeader>

        <CardContent className="flex flex-col gap-3 pt-4">
          <p className="text-xs text-muted-foreground">
            This never runs on its own. An administrator reviews what you write and the model drafts
            a rule they approve.
          </p>

          {context ? (
            <div className="rounded-md border bg-muted/40 px-2.5 py-2 text-[0.7rem]">
              <span className="font-semibold">Pointing at:</span> {context}
            </div>
          ) : null}

          {error ? <ErrorState message={error} /> : null}

          {saved ? (
            <p
              className="rounded-md border border-success/40 bg-success/10 px-2.5 py-2 text-xs"
              data-testid="observation-saved"
            >
              Saved. Change anything above and press Save again to reword it; follow what becomes of
              it on the Observations page.
            </p>
          ) : null}

          {saved && coveredBy.length > 0 ? (
            <div
              className="rounded-md border border-warn/40 bg-warn/10 px-2.5 py-2 text-xs"
              data-testid="covered-by"
            >
              <b>
                {coveredBy.some((rule) => rule.contradicts)
                  ? "A rule already running says the opposite."
                  : "A rule already covers this."}
              </b>{" "}
              Your observation is saved either way, and an administrator will see both. If the
              existing rule is wrong, say so — that is the most useful thing you can tell us.
              <ul className="mt-1 space-y-0.5">
                {coveredBy.map((rule) => (
                  <li key={`${rule.kind}-${rule.id}`} className="flex flex-wrap items-center gap-2">
                    <span className="mono">{rule.summary}</span>
                    {rule.contradicts ? <span>— this is what yours contradicts</span> : null}
                    <Button size="xs" variant="outline" onClick={() => disputeRule(rule)}>
                      Say this rule is wrong
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="observation-kind">What kind of thing is this?</Label>
              <Select
                id="observation-kind"
                value={kind}
                onChange={(event) => setKind(event.target.value as ObservationKind)}
              >
                {KINDS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="observation-severity">How serious is a breach?</Label>
              <Select
                id="observation-severity"
                value={severity}
                onChange={(event) => setSeverity(event.target.value as Severity)}
              >
                {SEVERITIES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="observation-scope">Where should it apply?</Label>
              <Select
                id="observation-scope"
                value={scope}
                onChange={(event) => setScope(event.target.value as ObservationScope)}
              >
                {SCOPES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="observation-statement">
              What should the tool check?<span className="text-destructive"> *</span>
            </Label>
            <Textarea
              id="observation-statement"
              value={statement}
              onChange={(event) => setStatement(event.target.value)}
              placeholder="In your own words. For example: this column is what clause 4.2 is actually asking for."
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="observation-expectation">What do you expect to see?</Label>
            <Input
              id="observation-expectation"
              value={expectation}
              onChange={(event) => setExpectation(event.target.value)}
              placeholder="For example: never blank for account review."
            />
            <span className="text-[0.7rem] text-muted-foreground">
              Write no account numbers, names, or other personal data. Saving is refused when the
              text looks like it carries any.
            </span>
          </div>
        </CardContent>

        <div className="flex justify-end gap-2 border-t p-4">
          <Button variant="ghost" onClick={onClose}>
            {saved ? "Close" : "Cancel"}
          </Button>
          <Button disabled={statement.trim().length < 3 || saving} onClick={() => void save()}>
            <Lightbulb className="h-4 w-4" />{" "}
            {saving ? "Saving…" : current ? "Save changes" : "Save observation"}
          </Button>
        </div>
      </Card>
    </div>
  );
}
