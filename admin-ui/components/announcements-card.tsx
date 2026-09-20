"use client";

/**
 * Scheduling what an app says at the top of the page (Phase 6.14g).
 *
 * "Maintenance starts at 11pm on the 6th." Written here, it reaches whoever is using
 * the app when it matters, and takes itself down afterwards.
 *
 * Three constraints the server enforces and this screen states plainly, because a
 * limit somebody only meets as an error message reads as a bug: every notice has an
 * end, at most five are scheduled at once, and none of them is dismissible.
 */

import { Plus } from "lucide-react";
import * as React from "react";

import { DeleteButton } from "@/components/confirm-delete";
import { Explain, FieldEffect } from "@/components/explain";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  Input,
  Label,
  Select,
  TD,
  TH,
  TR,
  Table,
  Textarea,
} from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { Announcement } from "@/lib/types";

/** The longest message the server accepts. Stated here so the counter is honest. */
const MAX_CHARS = 2000;

/** How many may be scheduled at once. A reading limit, not a storage one. */
const MAX_ACTIVE = 5;

const LEVELS = [
  { value: "info", label: "Info — something worth knowing" },
  { value: "warning", label: "Warning — something to plan around" },
  { value: "critical", label: "Critical — something happening now" },
];

const AUDIENCES = [
  { value: "user", label: "The user app only" },
  { value: "admin", label: "This console only" },
  { value: "both", label: "Both apps" },
];

/** An ISO string for a datetime-local input, or "" when there is nothing to show. */
function forInput(iso: string): string {
  if (!iso) return "";
  const at = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

export function AnnouncementsCard({ onError }: { onError: (message: string) => void }) {
  const [rows, setRows] = React.useState<Announcement[] | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [draft, setDraft] = React.useState({
    level: "info",
    audience: "user",
    message: "",
    starts_at: "",
    ends_at: "",
  });

  const load = React.useCallback(async () => {
    try {
      setRows(await api.listAnnouncements());
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.detail : "Could not read the notices.");
    }
  }, [onError]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function act(what: string, run: () => Promise<unknown>) {
    setBusy(true);
    try {
      await run();
      await load();
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.detail : `Could not ${what}.`);
    } finally {
      setBusy(false);
    }
  }

  const scheduled = (rows ?? []).filter(
    (row) => row.is_active && new Date(row.ends_at) > new Date()
  ).length;
  const ready = draft.message.trim() && draft.starts_at && draft.ends_at;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1">
          Notices at the top of an app
          <Explain label="What notices are for">
            A message for whoever is using the app while it matters — maintenance, a deadline, a
            change to how something is handled.
            <br />
            <br />
            Every notice needs an end date. A banner nobody remembers to take down becomes a stale
            warning, and a stale warning teaches people to stop reading banners.
            <br />
            <br />
            At most {MAX_ACTIVE} are scheduled at once, and none of them can be dismissed: a notice
            you scheduled is one you wanted read.
          </Explain>
        </CardTitle>
        <span className="text-[0.7rem] text-muted-foreground">
          {scheduled} of {MAX_ACTIVE} scheduled. Shown automatically between its start and end, then
          gone.
        </span>
      </CardHeader>
      <CardContent>
        <div className="mb-3 grid gap-2 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <Label htmlFor="an-level">How serious</Label>
            <Select
              id="an-level"
              value={draft.level}
              onChange={(event) => setDraft({ ...draft, level: event.target.value })}
            >
              {LEVELS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="an-audience">Who sees it</Label>
            <Select
              id="an-audience"
              value={draft.audience}
              onChange={(event) => setDraft({ ...draft, audience: event.target.value })}
            >
              {AUDIENCES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="an-from">Show from</Label>
            <Input
              id="an-from"
              type="datetime-local"
              value={draft.starts_at}
              onChange={(event) => setDraft({ ...draft, starts_at: event.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="an-to">Show until</Label>
            <Input
              id="an-to"
              type="datetime-local"
              value={draft.ends_at}
              onChange={(event) => setDraft({ ...draft, ends_at: event.target.value })}
            />
          </div>
        </div>

        <div className="mb-2 flex flex-col gap-1">
          <Label htmlFor="an-message">The message</Label>
          <Textarea
            id="an-message"
            rows={3}
            maxLength={MAX_CHARS}
            placeholder="Maintenance starts at 11pm on the 6th. Runs in progress will finish; new submissions are paused until 2am."
            value={draft.message}
            onChange={(event) => setDraft({ ...draft, message: event.target.value })}
          />
          <span className="text-[0.7rem] text-muted-foreground">
            {draft.message.length} of {MAX_CHARS} characters.
          </span>
        </div>

        <div className="mb-4 flex items-center gap-2">
          <Button
            disabled={busy || !ready}
            onClick={() =>
              void act("schedule the notice", async () => {
                await api.createAnnouncement({
                  level: draft.level,
                  audience: draft.audience,
                  message: draft.message.trim(),
                  starts_at: new Date(draft.starts_at).toISOString(),
                  ends_at: new Date(draft.ends_at).toISOString(),
                });
                setDraft({ ...draft, message: "", starts_at: "", ends_at: "" });
              })
            }
          >
            <Plus className="mr-1 h-4 w-4" aria-hidden />
            Schedule
          </Button>
          <FieldEffect
            kind="reviewer"
            note="Read by people using the app. It reaches no model and changes no finding."
          />
        </div>

        {(rows ?? []).length === 0 ? (
          <EmptyState
            title="Nothing scheduled"
            hint="Which is the normal state — a banner that is always there stops being read."
          />
        ) : (
          <Table>
            <thead>
              <TR>
                <TH>When</TH>
                <TH>Level</TH>
                <TH>Who</TH>
                <TH>Message</TH>
                <TH aria-label="Actions" />
              </TR>
            </thead>
            <tbody>
              {(rows ?? []).map((row) => (
                <TR key={row.id} className={row.is_active ? "" : "opacity-50"}>
                  <TD className="whitespace-nowrap text-xs">
                    {forInput(row.starts_at).replace("T", " ")}
                    <br />
                    to {forInput(row.ends_at).replace("T", " ")}
                    {row.showing_now ? (
                      <>
                        <br />
                        <Badge tone="success">showing now</Badge>
                      </>
                    ) : null}
                  </TD>
                  <TD>
                    <Badge
                      tone={
                        row.level === "critical"
                          ? "destructive"
                          : row.level === "warning"
                            ? "warn"
                            : "info"
                      }
                    >
                      {row.level}
                    </Badge>
                  </TD>
                  <TD className="text-xs">{row.audience}</TD>
                  <TD className="max-w-md text-xs">{row.message}</TD>
                  <TD className="flex items-center gap-1">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={() =>
                        void act("change the notice", () =>
                          api.setAnnouncementActive(row.id, !row.is_active)
                        )
                      }
                    >
                      {row.is_active ? "Switch off" : "Switch on"}
                    </Button>
                    <DeleteButton
                      compact
                      label={`the notice “${row.message.slice(0, 40)}”`}
                      busy={busy}
                      onDelete={async (confirm) => {
                        await api.deleteAnnouncement(row.id, confirm);
                        await load();
                      }}
                    />
                  </TD>
                </TR>
              ))}
            </tbody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
