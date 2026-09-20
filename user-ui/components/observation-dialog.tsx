"use client";

/**
 * Train AI mode: the form a reviewer writes an observation in (ADR-021, 6.1e, 6.13b).
 *
 * An observation never runs. It is a sentence plus the thing it points at; an
 * administrator reviews it and the model drafts a rule they approve. The anchor is
 * prefilled from whatever the person was looking at, because a rule the model can
 * synthesize reliably needs a selection and not only prose.
 *
 * The people writing these are senior associates, so the form gets out of the way: the
 * sentence comes first and has focus, the expectation second, and the three settings sit
 * under "Details" with defaults that are right most of the time.
 */

import { ChevronDown, ChevronRight, Lightbulb, X } from "lucide-react";
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
import { SEVERITY_LABEL } from "@/lib/display";
import type {
  Anchor,
  CoveringRule,
  Observation,
  ObservationInput,
  ObservationKind,
  ObservationScope,
  Severity,
} from "@/lib/types";

/** The plain-English labels for the form's options, shared with the observations list. */
export const KINDS: { value: ObservationKind; label: string }[] = [
  { value: "reconciliation", label: "Two things should agree" },
  { value: "field_constraint", label: "A field should always look like this" },
  { value: "correction", label: "The tool got something wrong" },
  { value: "note", label: "Something worth knowing" },
];

export const SEVERITIES: { value: Severity; label: string }[] = (
  ["high", "medium", "low", "review"] as Severity[]
).map((value) => ({ value, label: SEVERITY_LABEL[value] }));

export const SCOPES: { value: ObservationScope; label: string }[] = [
  { value: "customer", label: "This customer" },
  { value: "programme", label: "This delivery programme" },
  { value: "global", label: "Every run" },
];

/** How an anchor reads as a chip. */
export function anchorLabel(anchor: Anchor): string {
  switch (anchor.kind) {
    case "report_cell":
      return `${anchor.artifact || "report"} ${anchor.sheet ? `${anchor.sheet}!` : ""}${anchor.cell}${anchor.field ? ` (${anchor.field})` : ""}`;
    case "report_field":
      return `${anchor.artifact || "report"} · ${anchor.field}`;
    case "osl_section":
      return `OSL · ${anchor.reference || "section"}`;
    case "config_path":
      return `config · ${anchor.reference || anchor.cell}`;
    case "finding":
      return `finding ${anchor.reference}`;
    case "rule":
      return `rule · ${anchor.value || anchor.reference}`;
    case "run":
      return `this run${anchor.value ? ` · ${anchor.value}` : ""}`;
    default:
      return anchor.reference || anchor.kind;
  }
}

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

const MIN_STATEMENT = 3;

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
  const [details, setDetails] = React.useState(Boolean(existing));
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
  // Feedback is submitted once. After that the form shows what was sent, greyed and
  // read-only: an observation an administrator has already read and drafted a rule
  // from should not change underneath them. A mistake is fixed by asking an
  // administrator to delete it, which frees the person to write a fresh one.
  const locked = Boolean(current);
  // Anchors are state: a chip can be removed, and "say this rule is wrong" adds one.
  const [pointing, setPointing] = React.useState<Anchor[]>(existing ? existing.anchors : anchors);
  const statementRef = React.useRef<HTMLTextAreaElement>(null);

  // Focus the sentence, and let Escape close from anywhere: the key handler used to sit
  // on the overlay and did nothing until the person had tabbed into the dialog.
  React.useEffect(() => {
    statementRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

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
    setDetails(true);
    statementRef.current?.focus();
  }

  const tooShort = statement.trim().length < MIN_STATEMENT;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="observation-title"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <Card className="w-full max-w-2xl">
        <CardHeader className="border-b">
          <CardTitle id="observation-title" className="flex items-center gap-1.5">
            <Lightbulb className="h-4 w-4 text-primary" />
            {locked ? "Your observation — submitted" : "What should this check?"}
            <TrainAiTag />
          </CardTitle>
        </CardHeader>

        <CardContent className="flex flex-col gap-3 pt-4">
          <p className="text-xs text-muted-foreground">
            {locked
              ? "Submitted, and locked so it cannot change while an administrator is reading it. If you need to correct something, ask an administrator to delete it and you can write a fresh one."
              : "This never runs on its own, and you submit it once. An administrator reviews what you write and the model drafts a rule they approve."}
          </p>

          {context ? (
            <div className="rounded-md border bg-muted/40 px-2.5 py-2 text-[0.7rem]">
              <span className="font-semibold">Pointing at:</span> {context}
            </div>
          ) : null}

          {pointing.length > 0 ? (
            <ul className="flex flex-wrap gap-1.5" aria-label="What this observation points at">
              {pointing.map((anchor, index) => (
                <li
                  key={`${anchor.kind}-${anchor.reference}-${anchor.cell}-${index}`}
                  className="mono inline-flex items-center gap-1 rounded-full border bg-muted/40 px-2 py-0.5 text-[0.68rem]"
                  data-testid="anchor-chip"
                >
                  {anchorLabel(anchor)}
                  {pointing.length > 1 ? (
                    <button
                      type="button"
                      className="rounded-full hover:bg-accent"
                      aria-label={`Remove ${anchorLabel(anchor)}`}
                      onClick={() => setPointing(pointing.filter((_, i) => i !== index))}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}

          {error ? <ErrorState message={error} /> : null}

          {saved ? (
            <p
              className="rounded-md border border-success/40 bg-success/10 px-2.5 py-2 text-xs"
              data-testid="observation-saved"
            >
              Saved. Change anything and press Save changes to reword it; follow what becomes of it
              on My observations.
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

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="observation-statement">
              What should the tool check?<span className="text-destructive"> *</span>
            </Label>
            <Textarea
              disabled={locked}
              id="observation-statement"
              ref={statementRef}
              value={statement}
              onChange={(event) => setStatement(event.target.value)}
              placeholder="In your own words. For example: this column is what clause 4.2 is actually asking for."
            />
            <span className="text-[0.7rem] text-muted-foreground">
              Write no account numbers, names, or other personal data, here or below. Saving is
              refused when the text looks like it carries any.
            </span>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="observation-expectation">What do you expect to see?</Label>
            <Input
              disabled={locked}
              id="observation-expectation"
              value={expectation}
              onChange={(event) => setExpectation(event.target.value)}
              placeholder="For example: never blank for account review."
            />
          </div>

          <button
            type="button"
            className="flex items-center gap-1 self-start text-xs text-muted-foreground hover:text-foreground"
            aria-expanded={details}
            onClick={() => setDetails(!details)}
          >
            {details ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
            Details
            {!details ? (
              <span className="text-[0.7rem]">
                {" "}
                · {KINDS.find((k) => k.value === kind)?.label} · {SEVERITY_LABEL[severity]} ·{" "}
                {SCOPES.find((s) => s.value === scope)?.label}
              </span>
            ) : null}
          </button>

          {details ? (
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="observation-kind">What kind of thing is this?</Label>
                <Select
                  disabled={locked}
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
                <Label htmlFor="observation-severity">If this is broken, how serious is it?</Label>
                <Select
                  disabled={locked}
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
                  disabled={locked}
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
          ) : null}
        </CardContent>

        <div className="flex items-center justify-end gap-2 border-t p-4">
          {tooShort ? (
            <span className="mr-auto text-[0.7rem] text-muted-foreground">
              Write at least a few words before submitting.
            </span>
          ) : null}
          <Button variant="ghost" onClick={onClose}>
            {locked ? "Close" : "Cancel"}
          </Button>
          {locked ? null : (
            <Button disabled={tooShort || saving} onClick={() => void save()}>
              <Lightbulb className="h-4 w-4" /> {saving ? "Submitting…" : "Submit observation"}
            </Button>
          )}
        </div>
      </Card>
    </div>
  );
}
