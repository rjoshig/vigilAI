"use client";

/**
 * Ask the frozen report (Phase 8e).
 *
 * A launcher bottom-right on a finalized run's report page, and a panel that opens
 * above it. The report itself is a stored, self-contained HTML file served into an
 * iframe and never regenerated (ADR-005), so this is a **sibling overlay on the page**
 * rather than a change to the document. The frozen artifact stays byte-for-byte what
 * was attested to.
 *
 * **It says what it is before it is used.** Three sentences, from the server so they
 * cannot drift from the rule they describe: what it cannot see (rows and cell values),
 * what it changes (nothing), and that the conversation is not saved. Each prevents a
 * different wrong expectation, and the third is the one people are owed before they
 * type something they would want to keep.
 *
 * **The transcript is component state and nothing else.** Not `localStorage`, not a
 * store, not the server — so a shared machine does not hand the next person the last
 * one's questions, and closing the panel really does end the conversation. That is the
 * cost of the decision as much as the benefit: a question asked before a report was
 * shared cannot be recovered later. The Copy button exists because of it.
 *
 * **Citations are chips, never prose.** The server checks every identifier against the
 * context it built before it sends one, so a chip here is a claim that was verified.
 * When the model did not say what its answer rested on, the panel says the citations
 * could not be verified and shows none — the answer still stands, because pulling text
 * somebody is mid-way through reading looks like a malfunction even when it is right.
 */

import { Check, Copy, MessageSquare, Send, X } from "lucide-react";
import * as React from "react";

import { Button, Input } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { ChatOpening, ChatTurn } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How tall the panel opens, and the floor a drag may not go below. */
const DEFAULT_HEIGHT = 420;
const MIN_HEIGHT = 240;

export function ReportChat({ runId }: { runId: number }) {
  const [opening, setOpening] = React.useState<ChatOpening | null>(null);
  const [open, setOpen] = React.useState(false);
  const [turns, setTurns] = React.useState<ChatTurn[]>([]);
  const [draft, setDraft] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);
  const [height, setHeight] = React.useState(DEFAULT_HEIGHT);

  const panelRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const endRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    api
      .chatOpening(runId)
      // A chat that cannot be reached is not an error on the report page: the report
      // is what the person came for, and the launcher simply does not appear.
      .then(setOpening)
      .catch(() => setOpening(null));
  }, [runId]);

  // Everything the conversation was lives here and nowhere else, so unmounting the
  // panel is what clears it. Deliberate, and the reason Copy exists.
  React.useEffect(() => {
    if (!open) {
      setTurns([]);
      setDraft("");
      setError(null);
    }
  }, [open]);

  React.useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns]);

  // Escape closes, and focus is kept inside while it is open: a floating panel that
  // cannot be left from the keyboard is a defect in a tool people use all day.
  React.useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const focusable = panelRef.current.querySelectorAll<HTMLElement>(
        'button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  function startResize(event: React.PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = height;
    function onMove(move: PointerEvent) {
      // Dragging the top edge upward makes it taller, which is why the delta is
      // subtracted rather than added.
      setHeight(Math.max(MIN_HEIGHT, startHeight - (move.clientY - startY)));
    }
    function onUp() {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  async function ask(question: string) {
    const asked = question.trim();
    if (!asked || busy) return;
    setBusy(true);
    setError(null);
    setDraft("");

    const history = turns.map((turn) => ({ who: turn.who, text: turn.text }));
    setTurns((prev) => [...prev, { who: "You", text: asked }, { who: "Assistant", text: "" }]);

    try {
      const result = await api.askReport(runId, asked, history, (piece) => {
        // Appended to the last turn as it arrives, which is the whole point of the
        // streaming path: the person reads while the model is still writing.
        setTurns((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          next[next.length - 1] = { ...last, text: last.text + piece };
          return next;
        });
      });
      setTurns((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        next[next.length - 1] = {
          ...last,
          citations: result.citations,
          unverified: result.unverified,
        };
        return next;
      });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "The answer could not be read.");
      // The empty assistant turn is removed rather than left as a blank bubble.
      setTurns((prev) => prev.slice(0, -1));
    } finally {
      setBusy(false);
    }
  }

  async function copyConversation() {
    const text = turns.map((turn) => `${turn.who}: ${turn.text}`).join("\n\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("The conversation could not be copied to the clipboard.");
    }
  }

  if (!opening?.enabled) return null;

  if (!open) {
    return (
      <Button
        className="fixed bottom-4 right-4 z-40 shadow-lg"
        size="sm"
        data-testid="report-chat-launcher"
        onClick={() => setOpen(true)}
      >
        <MessageSquare className="h-4 w-4" /> Ask this report
      </Button>
    );
  }

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="false"
      aria-label="Ask this report"
      data-testid="report-chat-panel"
      style={{ height }}
      className="fixed bottom-4 right-4 z-40 flex w-[min(28rem,calc(100vw-2rem))] flex-col rounded-lg border border-border bg-background shadow-2xl"
    >
      <div
        role="separator"
        aria-label="Drag to resize"
        onPointerDown={startResize}
        className="h-1.5 cursor-ns-resize rounded-t-lg bg-muted"
      />
      <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
        <span className="text-sm font-semibold">Ask this report</span>
        <div className="flex items-center gap-1">
          {turns.length > 0 ? (
            <Button
              variant="ghost"
              size="xs"
              onClick={() => void copyConversation()}
              title="Nothing is stored by the tool, so keeping this is yours to do"
            >
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? "Copied" : "Copy"}
            </Button>
          ) : null}
          <Button variant="ghost" size="xs" aria-label="Close" onClick={() => setOpen(false)}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto px-3 py-3 text-xs">
        <p className="whitespace-pre-line text-muted-foreground">{opening.greeting}</p>
        <p className="rounded-md border border-border bg-muted/40 p-2 text-[0.7rem] text-muted-foreground">
          {opening.cannot_see} {opening.changes_nothing} {opening.not_saved}
        </p>
        {opening.trimmed.length > 0 ? (
          <p className="text-[0.7rem] text-warn" data-testid="report-chat-trimmed">
            Some of this run&rsquo;s context was too long to send in full:{" "}
            {opening.trimmed.join(" ")}
          </p>
        ) : null}

        {turns.length === 0 ? (
          <div className="flex flex-wrap gap-1.5" data-testid="report-chat-starters">
            {opening.starters.map((starter) => (
              <button
                key={starter}
                type="button"
                className="rounded-full border border-border px-2.5 py-1 text-[0.7rem] hover:bg-accent"
                onClick={() => void ask(starter)}
              >
                {starter}
              </button>
            ))}
          </div>
        ) : null}

        {turns.map((turn, index) => (
          <div
            key={index}
            className={cn(
              "rounded-md p-2",
              turn.who === "You" ? "bg-primary/10" : "border border-border bg-card"
            )}
          >
            <div className="mb-0.5 text-[0.65rem] font-semibold uppercase text-muted-foreground">
              {turn.who}
            </div>
            <p className="whitespace-pre-line leading-relaxed">{turn.text || (busy ? "…" : "")}</p>
            {turn.citations && turn.citations.length > 0 ? (
              <div className="mt-1.5 flex flex-wrap gap-1" data-testid="report-chat-citations">
                {turn.citations.map((citation) => (
                  <span
                    key={citation.id}
                    title={citation.label}
                    className="rounded-full bg-muted px-2 py-0.5 text-[0.65rem] font-semibold"
                  >
                    {citation.id}
                  </span>
                ))}
              </div>
            ) : null}
            {turn.unverified ? (
              <p className="mt-1.5 text-[0.65rem] text-warn" data-testid="report-chat-unverified">
                Citations could not be verified for this answer. Check it against the report before
                relying on it.
              </p>
            ) : null}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      {error ? (
        <p role="alert" className="border-t px-3 py-1.5 text-[0.7rem] text-destructive">
          {error}
        </p>
      ) : null}

      <form
        className="flex items-center gap-1.5 border-t px-3 py-2"
        onSubmit={(event) => {
          event.preventDefault();
          void ask(draft);
        }}
      >
        <Input
          ref={inputRef}
          aria-label="Your question about this report"
          placeholder="Ask about this report…"
          value={draft}
          disabled={busy}
          onChange={(event) => setDraft(event.target.value)}
        />
        <Button type="submit" size="sm" disabled={busy || !draft.trim()} aria-label="Send">
          <Send className="h-4 w-4" />
        </Button>
      </form>
    </div>
  );
}
