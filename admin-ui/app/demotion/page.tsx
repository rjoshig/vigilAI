"use client";

/**
 * What a reviewer has stopped needing to see (Phase 6.18a, ADR-043).
 *
 * The tool has recorded every verdict a reviewer gave since Phase 6.11 and acted on
 * none of them. This screen is what those verdicts add up to: which recurring findings
 * have been waved through often enough to have earned their way out of the review
 * queue, and which a person has upheld and so never can.
 *
 * **Nothing here changes what a reviewer sees, and the screen says so at the top.**
 * That is the whole of 6.18a: the first evidence about whether demotion is safe must
 * not be a reviewer failing to see something. The question this page exists to be
 * asked is on it in words — *it would have hidden these; was any of them real?* — and
 * the answer is what decides whether the rest of the phase gets built.
 */

import { EyeOff, ShieldAlert } from "lucide-react";
import * as React from "react";

import { Explain } from "@/components/explain";
import {
  Badge,
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
  Stat,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { DemotionReport, SignatureState } from "@/lib/types";

/** A signature's identity, said in words rather than as its digest. */
function describe(row: SignatureState): string {
  const what = row.element_ref || "the delivery";
  return `${row.finding_type} on ${what}`;
}

/** One signature, with the evidence behind it. */
function SignatureRow({ row }: { row: SignatureState }) {
  return (
    <div className="border-b py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{describe(row)}</span>
        <Badge tone="outline">{row.customer_name || "every customer"}</Badge>
        {row.scope ? <Badge tone="muted">{row.scope}</Badge> : null}
        {row.severities.map((severity) => (
          <Badge key={severity} tone={severity === "high" ? "destructive" : "muted"}>
            {severity}
          </Badge>
        ))}
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{row.reason}</p>
      <p className="mt-1 text-[0.7rem] text-muted-foreground">
        <span className="mono">{row.rule_ref}</span> · waved through {row.dismissed}, judged real{" "}
        {row.upheld} · evidence from{" "}
        {row.justified_by_run_ids.length > 0
          ? `runs ${row.justified_by_run_ids.join(", ")}`
          : "no runs yet"}
      </p>
    </div>
  );
}

export default function DemotionPage() {
  const [report, setReport] = React.useState<DemotionReport | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [customer, setCustomer] = React.useState("");
  const [scope, setScope] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      setReport(await api.getDemotionReport(customer.trim(), scope.trim()));
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, [customer, scope]);

  React.useEffect(() => {
    void load();
  }, [load]);

  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!report) return <Skeleton className="h-96" />;

  const watching = report.counts.watching ?? 0;
  const wouldDemote = report.counts.would_demote ?? 0;
  const blocked = report.counts.blocked ?? 0;

  return (
    <>
      <PageHeader
        title="What reviewers stop needing to see"
        description="Recurring findings, and what the people who saw them decided."
        explain={
          <Explain label="Reading this screen">
            A <strong>signature</strong> is the identity of &ldquo;this same finding again&rdquo;:
            one customer, one delivery programme, one rule, and one thing it fired on. A blank score
            column and a blank state column are two signatures, however much they share a rule.
            <br />
            <br />A signature waved through <strong>ten times with no exceptions</strong> has earned
            its way out of the review queue. A count rather than a rate: &ldquo;shown to a person
            ten times and never once mattered&rdquo; is a sentence that survives an auditor;
            &ldquo;nine times out of ten&rdquo; is not, because the tenth is the one that would have
            been hidden.
            <br />
            <br />
            <strong>One finding judged real blocks a signature permanently</strong>, and findings at
            high severity are never demoted at any level of evidence. The aim is a reviewer who
            reads only the serious findings, not one who reads none.
          </Explain>
        }
      />

      {report.shadow ? (
        <Card className="mb-5 border-l-4 border-l-info bg-info/5">
          <CardContent className="flex gap-3 p-4">
            <EyeOff className="mt-0.5 h-4 w-4 shrink-0 text-info" aria-hidden />
            <div className="text-sm">
              <p className="font-medium">Nothing on this screen is being acted on.</p>
              <p className="mt-1 text-muted-foreground">
                Every reviewer still sees every finding. This is what demotion <em>would</em> do,
                recorded so the question can be asked from evidence:{" "}
                <strong>it would have hidden these &mdash; was any of them real?</strong> That
                answer decides whether reviewers ever stop seeing them.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        <Stat label="Would be hidden" value={String(wouldDemote)} tone="info" />
        <Stat
          label="Still gathering evidence"
          value={String(watching)}
          hint="Fewer than ten clean verdicts"
        />
        <Stat
          label="Blocked"
          value={String(blocked)}
          hint="Judged real once, or too serious to hide"
          tone="muted"
        />
      </div>

      <div className="mb-5 flex flex-wrap gap-3">
        <div className="flex flex-col gap-1">
          <Label htmlFor="dm-customer">Customer</Label>
          <Input
            id="dm-customer"
            placeholder="Every customer"
            value={customer}
            onChange={(event) => setCustomer(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="dm-scope">Programme</Label>
          <Input
            id="dm-scope"
            placeholder="Every programme"
            value={scope}
            onChange={(event) => setScope(event.target.value)}
          />
        </div>
      </div>

      <Card className="mb-5">
        <CardHeader className="border-b">
          <CardTitle className="flex items-center gap-2">
            <EyeOff className="h-4 w-4" aria-hidden />
            Would be hidden from reviewers
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {report.would_demote.length === 0 ? (
            <EmptyState
              title="Nothing has earned its way out yet"
              hint="A finding needs ten occurrences, every one waved through, with none ever judged real."
            />
          ) : (
            report.would_demote.map((row) => <SignatureRow key={row.signature} row={row} />)
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b">
          <CardTitle className="flex items-center gap-2">
            <ShieldAlert className="h-4 w-4" aria-hidden />
            Blocked, and will stay blocked
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {report.blocked.length === 0 ? (
            <EmptyState
              title="Nothing is blocked"
              hint="A signature is blocked when a reviewer judged the finding real, or when it fires at a severity that is never hidden."
            />
          ) : (
            report.blocked.map((row) => <SignatureRow key={row.signature} row={row} />)
          )}
        </CardContent>
      </Card>
    </>
  );
}
