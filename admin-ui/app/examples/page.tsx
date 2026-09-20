"use client";

/**
 * The administrator's library of worked examples (Phase 6.13d, ADR-038).
 *
 * Every prompt ships with worked examples, and they are the floor: they teach a
 * mid-size model the shape of a good answer. This screen is where an administrator
 * adds theirs — a section of a real requirements document and the requirement it
 * states, a statement and the surface it belongs on — drawn from the deliveries they
 * actually see.
 *
 * Two rules are visible on the screen because they are what keep this safe. An answer
 * is validated against the stage's own schema before it is stored, so an example the
 * pipeline could not parse is refused with the field named. And a stage carries at most
 * four, so what is stored active is exactly what the model is shown: there is no such
 * thing here as a row that looks live and reaches nothing.
 */

import { BookOpen, ChevronDown, ChevronRight, Plus } from "lucide-react";
import * as React from "react";

import { EVERYWHERE, ScopePicker, scopeIsComplete, scopeLabel } from "@/components/scope-picker";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Input,
  Label,
  PageHeader,
  Skeleton,
  Textarea,
} from "@/components/ui/primitives";
import { VersionsPanel } from "@/components/versions-panel";
import { api, ApiError } from "@/lib/api";
import type {
  Candidate,
  Correction,
  ExampleStage,
  PromoteExample,
  PromptExample,
  Scope,
} from "@/lib/types";

/** A blank draft for one stage, with every part the stage shows the model. */
function emptyDraft(stage: ExampleStage): { given: Record<string, string>; answer: string } {
  const given: Record<string, string> = {};
  for (const field of stage.fields) given[field.name] = "";
  return { given, answer: "" };
}

/** Where a promoted example came from, said in words rather than in its origin token. */
function originLabel(origin: string): string {
  if (origin.startsWith("promoted:meaning")) return "Promoted from a confirmed mapping";
  if (origin.startsWith("promoted:requirement")) return "Promoted from a corrected requirement";
  if (origin.startsWith("promoted:candidate")) return "Promoted from an approved rule";
  return "Written here";
}

function StageSection({
  stage,
  examples,
  programmes,
  onChanged,
}: {
  stage: ExampleStage;
  examples: PromptExample[];
  programmes: Scope[];
  onChanged: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [showBuiltIn, setShowBuiltIn] = React.useState(false);
  const [adding, setAdding] = React.useState(false);
  const [draft, setDraft] = React.useState(() => emptyDraft(stage));
  const [scope, setScope] = React.useState(EVERYWHERE);
  const [note, setNote] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const active = examples.filter((example) => example.is_active).length;
  const full = active >= stage.max_examples;

  function reset() {
    setDraft(emptyDraft(stage));
    setScope(EVERYWHERE);
    setNote("");
    setError(null);
    setAdding(false);
  }

  async function add() {
    let answer: Record<string, unknown>;
    try {
      answer = JSON.parse(draft.answer) as Record<string, unknown>;
    } catch {
      setError("The answer has to be the JSON this stage returns.");
      return;
    }
    setBusy(true);
    try {
      await api.saveExample({
        stage: stage.stage,
        scope,
        given: draft.given,
        answer,
        note: note.trim(),
        is_active: true,
        sort_order: 0,
      });
      reset();
      onChanged();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not store the example.");
    } finally {
      setBusy(false);
    }
  }

  async function setActive(example: PromptExample, isActive: boolean) {
    setBusy(true);
    try {
      await api.patchExample(example.id, { is_active: isActive });
      setError(null);
      onChanged();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not change the example.");
    } finally {
      setBusy(false);
    }
  }

  const canAdd =
    scopeIsComplete(scope) &&
    draft.answer.trim().length > 0 &&
    stage.fields.every((field) => (draft.given[field.name] ?? "").trim().length > 0);

  return (
    <Card data-testid={`stage-${stage.stage}`}>
      <CardHeader>
        <button
          type="button"
          className="flex w-full items-center gap-2 text-left"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          <CardTitle>{stage.label}</CardTitle>
          <span className="ml-auto text-xs text-muted-foreground" data-testid="stage-count">
            {active} of {stage.max_examples} in use
            {examples.length > active ? ` · ${examples.length - active} off` : ""}
          </span>
        </button>
        <p className="mt-1 text-xs text-muted-foreground">{stage.description}</p>
      </CardHeader>

      {open ? (
        <CardContent className="space-y-4">
          {error ? <p className="text-xs text-destructive">{error}</p> : null}

          <div>
            <button
              type="button"
              className="text-xs font-medium underline-offset-2 hover:underline"
              onClick={() => setShowBuiltIn(!showBuiltIn)}
            >
              {showBuiltIn ? "Hide" : "Show"} the {stage.built_in.length} examples that ship in the
              prompt
            </button>
            {showBuiltIn ? (
              <ul className="mt-2 space-y-2">
                {stage.built_in.map((example) => (
                  <li key={example.number} className="rounded border bg-muted/40 p-2 text-xs">
                    <p className="mb-1 font-medium">Example {example.number}</p>
                    <pre className="mono whitespace-pre-wrap">{example.shown}</pre>
                    <pre className="mono mt-1 whitespace-pre-wrap text-muted-foreground">
                      {example.answer}
                    </pre>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>

          {examples.length === 0 ? (
            <EmptyState
              title="No examples of your own yet"
              hint="The prompt's own examples still apply. Add one when the model reads something the way your deliveries do not."
            />
          ) : (
            <ul className="space-y-2">
              {examples.map((example) => (
                <li key={example.id} className="rounded border p-2 text-xs" data-testid="example">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <Badge tone={example.is_active ? "success" : "muted"}>
                      {example.is_active ? "In use" : "Off"}
                    </Badge>
                    <Badge tone="outline">{scopeLabel(example.scope, programmes)}</Badge>
                    <span className="text-muted-foreground">{originLabel(example.origin)}</span>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ml-auto"
                      disabled={busy || (!example.is_active && full)}
                      onClick={() => void setActive(example, !example.is_active)}
                    >
                      {example.is_active ? "Take out of use" : "Put in use"}
                    </Button>
                  </div>
                  {stage.fields.map((field) => (
                    <div key={field.name} className="mb-1">
                      <span className="text-muted-foreground">{field.label}: </span>
                      <span className="mono whitespace-pre-wrap">
                        {example.given[field.name] ?? ""}
                      </span>
                    </div>
                  ))}
                  <pre className="mono whitespace-pre-wrap text-muted-foreground">
                    {JSON.stringify(example.answer)}
                  </pre>
                  {example.note ? <p className="mt-1 italic">{example.note}</p> : null}
                </li>
              ))}
            </ul>
          )}

          {adding ? (
            <div className="space-y-3 rounded border p-3">
              {stage.fields.map((field) => (
                <div key={field.name}>
                  <Label htmlFor={`${stage.stage}-${field.name}`}>
                    {field.label} — what the model is shown
                  </Label>
                  <Textarea
                    id={`${stage.stage}-${field.name}`}
                    rows={field.shape === "line" ? 2 : 4}
                    value={draft.given[field.name] ?? ""}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        given: { ...draft.given, [field.name]: event.target.value },
                      })
                    }
                  />
                </div>
              ))}
              <div>
                <Label htmlFor={`${stage.stage}-answer`}>
                  A good answer, as the JSON this stage returns
                </Label>
                <Textarea
                  id={`${stage.stage}-answer`}
                  rows={4}
                  className="mono"
                  value={draft.answer}
                  onChange={(event) => setDraft({ ...draft, answer: event.target.value })}
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  It is checked against this stage&apos;s own schema before it is stored. An example
                  the pipeline could not parse is refused, with the field named.
                </p>
              </div>
              <div>
                <Label htmlFor={`${stage.stage}-note`}>Why it is here (for the next person)</Label>
                <Input
                  id={`${stage.stage}-note`}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
              </div>
              <ScopePicker
                value={scope}
                onChange={setScope}
                programmes={programmes}
                idPrefix={`${stage.stage}-scope`}
              />
              <div className="flex gap-2">
                <Button disabled={!canAdd || busy} onClick={() => void add()}>
                  Add the example
                </Button>
                <Button variant="ghost" onClick={reset}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <div>
              <Button size="sm" disabled={full} onClick={() => setAdding(true)}>
                <Plus className="mr-1 h-3.5 w-3.5" /> Add an example
              </Button>
              {full ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  This stage is carrying its {stage.max_examples}. Take one out of use to add
                  another, so what is stored is what the model sees.
                </p>
              ) : null}
            </div>
          )}

          <VersionsPanel kind="example" objectKey={stage.stage} onReverted={onChanged} />
        </CardContent>
      ) : null}
    </Card>
  );
}

/**
 * The two places somebody has already corrected the model, offered for teaching.
 *
 * A requirement a reviewer rewrote and a candidate an administrator approved are both
 * the model being told how this work actually reads. Promoting one turns it into a
 * worked example, and nothing is promoted without the click.
 */
function PromotionPanel({ onPromoted }: { onPromoted: () => void }) {
  const [corrections, setCorrections] = React.useState<Correction[]>([]);
  const [approved, setApproved] = React.useState<Candidate[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const [nextCorrections, nextApproved] = await Promise.all([
        api.listCorrections(),
        api.listCandidates("approved"),
      ]);
      setCorrections(nextCorrections);
      setApproved(nextApproved);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not read the corrections.");
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function promote(payload: PromoteExample) {
    setBusy(true);
    try {
      await api.promoteExample(payload);
      setError(null);
      await load();
      onPromoted();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not promote it.");
    } finally {
      setBusy(false);
    }
  }

  if (corrections.length === 0 && approved.length === 0 && !error) return null;

  return (
    <Card data-testid="promotion-panel">
      <CardHeader>
        <CardTitle>Teach from a correction somebody already made</CardTitle>
        <p className="mt-1 text-xs text-muted-foreground">
          A requirement a reviewer rewrote, and a rule an administrator approved. Each one is the
          model being told how this work reads. Nothing here is promoted on its own.
        </p>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">
        {error ? <p className="text-destructive">{error}</p> : null}

        {corrections.length > 0 ? (
          <div>
            <p className="mb-1 font-medium">Requirements reviewers rewrote</p>
            <ul className="space-y-1">
              {corrections.map((correction) => (
                <li
                  key={`${correction.run_id}-${correction.rule_id}`}
                  className="flex flex-wrap items-center gap-2 rounded border p-2"
                  data-testid="correction"
                >
                  <span className="mono">{correction.rule_id}</span>
                  <span>{correction.summary}</span>
                  <span className="text-muted-foreground">
                    run {correction.run_id}
                    {correction.edited_by ? ` · ${correction.edited_by}` : ""}
                  </span>
                  <Button
                    size="xs"
                    variant="outline"
                    className="ml-auto"
                    disabled={busy || correction.promoted || !correction.source_text}
                    title={
                      correction.source_text
                        ? "Add this as a worked example for reading the requirements document"
                        : "This requirement quotes no wording to learn from"
                    }
                    onClick={() =>
                      void promote({
                        source: "requirement",
                        id: correction.run_id,
                        rule_id: correction.rule_id,
                      })
                    }
                  >
                    {correction.promoted ? "Already an example" : "Use as example"}
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {approved.length > 0 ? (
          <div>
            <p className="mb-1 font-medium">Rules approved from what reviewers wrote</p>
            <ul className="space-y-1">
              {approved.map((candidate) => (
                <li
                  key={candidate.id}
                  className="flex flex-wrap items-center gap-2 rounded border p-2"
                  data-testid="approved-candidate"
                >
                  <span className="mono">{candidate.name || "unnamed"}</span>
                  <Badge tone="outline">{candidate.target_kind}</Badge>
                  <Button
                    size="xs"
                    variant="outline"
                    className="ml-auto"
                    disabled={busy}
                    title="Add this as a worked example for drafting a rule from observations"
                    onClick={() => void promote({ source: "candidate", id: candidate.id })}
                  >
                    Use as example
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

export default function ExamplesPage() {
  const [stages, setStages] = React.useState<ExampleStage[] | null>(null);
  const [examples, setExamples] = React.useState<PromptExample[]>([]);
  const [programmes, setProgrammes] = React.useState<Scope[]>([]);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      const [nextStages, nextExamples, nextProgrammes] = await Promise.all([
        api.listExampleStages(),
        api.listExamples(),
        api.listScopes(),
      ]);
      setStages(nextStages);
      setExamples(nextExamples);
      setProgrammes(nextProgrammes);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Worked examples"
        description="What a good answer looks like, in your own deliveries. Examples show the model the shape of an answer; they are never rules — a rule is a check, a compliance rule or a field constraint, and code evaluates it."
      />

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      {stages === null ? (
        <Skeleton className="h-40" />
      ) : (
        <div className="space-y-3">
          {stages.map((stage) => (
            <StageSection
              key={stage.stage}
              stage={stage}
              examples={examples.filter((example) => example.stage === stage.stage)}
              programmes={programmes}
              onChanged={() => void load()}
            />
          ))}
        </div>
      )}

      <PromotionPanel onPromoted={() => void load()} />

      <Card>
        <CardContent className="flex items-start gap-2 p-3 text-xs text-muted-foreground">
          <BookOpen className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            A confirmed mapping on the Meaning screen can be promoted there in the same way. An
            example is never a rule: it shows the model the shape of a good answer, and every
            comparison is still made by code.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
