"use client";

/**
 * Runtime settings (ADR-023). Precedence is admin console > `.env` > built-in default,
 * so every value carries a badge saying which layer supplied it: without that, a value
 * that disagrees with the deployment's `.env` looks like a bug rather than an override.
 */

import { PlugZap, SlidersHorizontal } from "lucide-react";
import * as React from "react";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ErrorState,
  Input,
  Label,
  PageHeader,
  Select,
  Skeleton,
  TD,
  TH,
  TR,
  Table,
} from "@/components/ui/primitives";
import { AnnouncementsCard } from "@/components/announcements-card";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  ConfigChange,
  ProviderTestResult,
  Setting,
  SettingGroup,
  SettingSource,
} from "@/lib/types";

const SOURCE_LABELS: Record<SettingSource, string> = {
  admin: "set here",
  env: "from .env",
  default: "default",
};

const SOURCE_TONES: Record<SettingSource, "info" | "warn" | "muted"> = {
  admin: "info",
  env: "warn",
  default: "muted",
};

function SourceBadge({ source }: { source: SettingSource }) {
  return <Badge tone={SOURCE_TONES[source]}>{SOURCE_LABELS[source]}</Badge>;
}

/** How a value reads on screen. Secrets never reach here; they have their own field. */
function display(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "on" : "off";
  return String(value);
}

function when(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

/** The editable form of a setting's current value, as the inputs hold it. */
function initialDraft(setting: Setting): string | boolean {
  if (setting.kind === "bool") return setting.value === true;
  if (setting.kind === "secret") return "";
  return setting.value === null || setting.value === undefined ? "" : String(setting.value);
}

/**
 * The warning a change deserves before it is applied. Each of these is something that
 * is unpleasant to discover afterwards rather than beforehand.
 */
function warningFor(setting: Setting, next: unknown): string | null {
  if (setting.key === "auth.admin") {
    return next === true
      ? "Everyone will need an account from now on, and the server refuses to serve a non-loopback deployment until the bootstrap password has been changed."
      : "The console becomes reachable by anyone who can reach its URL.";
  }
  if (setting.key === "retention.days" && typeof next === "number") {
    const current = typeof setting.value === "number" ? setting.value : null;
    if (current !== null && next < current) {
      return `The next retention sweep deletes anything already older than ${next} days.`;
    }
  }
  return null;
}

interface SettingRowProps {
  setting: Setting;
  onChanged: (updated: Setting) => void;
}

function SettingRow({ setting, onChanged }: SettingRowProps) {
  const [draft, setDraft] = React.useState<string | boolean>(() => initialDraft(setting));
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  // A second click confirms; there is no dialog primitive and none is worth a dependency.
  const [confirming, setConfirming] = React.useState<"save" | "revert" | null>(null);

  React.useEffect(() => {
    setDraft(initialDraft(setting));
    setConfirming(null);
  }, [setting]);

  const wire: unknown =
    setting.kind === "bool"
      ? draft === true
      : setting.kind === "int"
        ? Number(draft)
        : String(draft);

  const dirty =
    setting.kind === "secret"
      ? String(draft).length > 0
      : setting.kind === "bool"
        ? (draft === true) !== (setting.value === true)
        : String(draft) !== (setting.value === null ? "" : String(setting.value));

  const invalidNumber =
    setting.kind === "int" && (String(draft).trim() === "" || Number.isNaN(Number(draft)));

  const warning = dirty && !invalidNumber ? warningFor(setting, wire) : null;

  async function run(what: "save" | "revert") {
    setBusy(true);
    setError(null);
    try {
      const updated =
        what === "save"
          ? await api.saveSetting(setting.key, wire)
          : await api.revertSetting(setting.key);
      setConfirming(null);
      onChanged(updated);
    } catch (caught) {
      // The 422 and 409 details are written to be read, so they are shown verbatim and
      // beside the field that caused them rather than at the top of the page.
      setError(caught instanceof ApiError ? caught.detail : `Could not ${what} this setting.`);
    } finally {
      setBusy(false);
    }
  }

  function act(what: "save" | "revert") {
    const needsConfirm = what === "save" && warning !== null;
    if (needsConfirm && confirming !== "save") {
      setConfirming("save");
      return;
    }
    void run(what);
  }

  const inputId = `setting-${setting.key}`;
  const revertLabel =
    setting.kind === "secret"
      ? "Clear"
      : `Revert to ${setting.fallback_source === "env" ? ".env" : "default"} (${display(
          setting.fallback
        )})`;

  return (
    <div className="grid gap-2 border-b py-3 last:border-b-0 sm:grid-cols-[minmax(0,22rem)_1fr] sm:gap-4">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-1.5">
          <Label htmlFor={inputId} className="text-sm font-semibold">
            {setting.label}
          </Label>
          <SourceBadge source={setting.source} />
          {setting.restart ? <Badge tone="outline">restart needed</Badge> : null}
        </div>
        <div className="mono mt-0.5 text-[0.7rem] text-muted-foreground">{setting.key}</div>
        <p className="mt-1 text-xs text-muted-foreground">{setting.help}</p>
      </div>

      <div className="min-w-0">
        {!setting.editable ? (
          <div>
            <div className="mono text-sm">{display(setting.value)}</div>
            <p className="mt-1 text-xs text-muted-foreground">
              This one is set outside the console and is read-only here. {setting.help}
            </p>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            {setting.kind === "bool" ? (
              <label className="flex items-center gap-2 text-sm" htmlFor={inputId}>
                <input
                  id={inputId}
                  type="checkbox"
                  className="h-4 w-4 rounded border-input"
                  checked={draft === true}
                  onChange={(event) => setDraft(event.target.checked)}
                />
                {draft === true ? "on" : "off"}
              </label>
            ) : setting.kind === "enum" ? (
              <Select
                id={inputId}
                value={String(draft)}
                onChange={(event) => setDraft(event.target.value)}
              >
                {setting.choices.map((choice) => (
                  <option key={choice} value={choice}>
                    {choice}
                  </option>
                ))}
              </Select>
            ) : setting.kind === "int" ? (
              <Input
                id={inputId}
                type="number"
                className="w-40"
                min={setting.minimum ?? undefined}
                max={setting.maximum ?? undefined}
                value={String(draft)}
                onChange={(event) => setDraft(event.target.value)}
              />
            ) : setting.kind === "secret" ? (
              <div className="flex flex-wrap items-center gap-2">
                <span className="mono text-xs text-muted-foreground">
                  {setting.is_set ? `•••• ${setting.last4}` : "Not set"}
                </span>
                <Input
                  id={inputId}
                  type="password"
                  autoComplete="off"
                  className="w-72"
                  placeholder="leave blank to keep the current key"
                  value={String(draft)}
                  onChange={(event) => setDraft(event.target.value)}
                />
              </div>
            ) : (
              <Input
                id={inputId}
                className="mono w-72"
                value={String(draft)}
                onChange={(event) => setDraft(event.target.value)}
              />
            )}

            <Button
              size="xs"
              variant={confirming === "save" ? "destructive" : "default"}
              disabled={busy || !dirty || invalidNumber}
              onClick={() => act("save")}
            >
              {confirming === "save" ? "Confirm" : "Save"}
            </Button>

            {setting.source === "admin" ? (
              <Button
                size="xs"
                variant="outline"
                disabled={busy}
                onClick={() => act("revert")}
                title={revertLabel}
              >
                {revertLabel}
              </Button>
            ) : null}
          </div>
        )}

        {setting.kind === "secret" ? (
          <p className="mt-1 text-xs text-muted-foreground">
            The key itself is never shown. Saving a value replaces it; leaving the box empty changes
            nothing.
          </p>
        ) : null}
        {warning ? <p className="mt-1 text-xs text-warn">{warning}</p> : null}
        {error ? <p className="mt-1 text-xs text-destructive">{error}</p> : null}
      </div>
    </div>
  );
}

/** One real provider call, so the saved settings can be proved before a run needs them. */
function ConnectionTest() {
  const [result, setResult] = React.useState<ProviderTestResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function test() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.testModel());
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
      <Button size="xs" variant="outline" disabled={busy} onClick={() => void test()}>
        <PlugZap className="h-3.5 w-3.5" /> {busy ? "Testing…" : "Test connection"}
      </Button>
      <span className="text-xs text-muted-foreground">
        Tests the settings as they are saved now, not what is typed above.
      </span>
      {result ? (
        result.ok ? (
          <span className="text-xs text-success">
            Reached {result.provider} · {result.model} in {result.latency_ms} ms.
          </span>
        ) : (
          <span className="text-xs text-destructive">{result.detail}</span>
        )
      ) : null}
      {error ? <span className="text-xs text-destructive">{error}</span> : null}
    </div>
  );
}

function History({ changes }: { changes: ConfigChange[] }) {
  return (
    <Card className="mt-6">
      <CardHeader className="border-b">
        <CardTitle>Change history</CardTitle>
        <span className="text-xs text-muted-foreground">the last {changes.length} changes</span>
      </CardHeader>
      <CardContent className="p-0">
        {changes.length === 0 ? (
          <p className="p-4 text-xs text-muted-foreground">
            Nothing has been changed here yet, so every value comes from the environment or the
            built-in default.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <TH>Setting</TH>
                <TH>From</TH>
                <TH>To</TH>
                <TH>Who</TH>
                <TH>When</TH>
              </tr>
            </thead>
            <tbody>
              {changes.map((change) => (
                <TR key={change.id}>
                  <TD className="mono">{change.key}</TD>
                  <TD className="mono text-muted-foreground">{display(change.old_value)}</TD>
                  <TD className="mono">{display(change.new_value)}</TD>
                  <TD>{change.changed_by || "—"}</TD>
                  <TD className="text-muted-foreground">{when(change.changed_at)}</TD>
                </TR>
              ))}
            </tbody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

/** The tab that holds scheduled notices, which are rows rather than settings. */
const NOTICES_TAB = "Notices";

export default function SettingsPage() {
  const [groups, setGroups] = React.useState<SettingGroup[] | null>(null);
  const [tab, setTab] = React.useState<string>("");
  const [changes, setChanges] = React.useState<ConfigChange[]>([]);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      const [loadedGroups, loadedChanges] = await Promise.all([
        api.listSettings(),
        api.settingsHistory(100),
      ]);
      setGroups(loadedGroups);
      setChanges(loadedChanges);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the API.");
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  // A change is applied to the one setting it touched, then the history is re-read, so
  // the rest of the page keeps whatever is half-typed in it.
  const onChanged = React.useCallback(
    (updated: Setting) => {
      setGroups((current) =>
        current === null
          ? current
          : current.map((group) => ({
              ...group,
              settings: group.settings.map((setting) =>
                setting.key === updated.key ? updated : setting
              ),
            }))
      );
      void api
        .settingsHistory(100)
        .then(setChanges)
        .catch(() => undefined);
    },
    [setGroups]
  );

  // Notices are not a setting — they are rows with a schedule — but they belong where
  // an administrator already goes to change how the apps behave.
  const tabs = React.useMemo(
    () => [...(groups ?? []).map((group) => group.name), NOTICES_TAB],
    [groups]
  );
  React.useEffect(() => {
    if (!tab && tabs.length > 0) setTab(tabs[0]);
  }, [tab, tabs]);

  return (
    <>
      <PageHeader
        title="Settings"
        description="The tool's runtime configuration. A value set here wins over the same value in .env, which in turn wins over the built-in default; each setting says which of the three it is using."
      />

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={() => void load()} />
        </div>
      ) : null}

      {!groups ? (
        <Skeleton className="h-96" />
      ) : (
        <>
          {/* One tab per group rather than one long page. Eight groups down a single
              column meant the setting somebody wanted was almost always below the
              fold, and a settings screen is read by somebody who already knows which
              one they came for. */}
          <div
            role="tablist"
            aria-label="Settings groups"
            className="mb-4 flex flex-wrap gap-1 border-b border-border"
          >
            {tabs.map((name) => (
              <button
                key={name}
                role="tab"
                type="button"
                aria-selected={name === tab}
                className={cn(
                  "-mb-px border-b-2 px-3 py-2 text-sm",
                  name === tab
                    ? "border-primary font-medium text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
                onClick={() => setTab(name)}
              >
                {name}
              </button>
            ))}
          </div>

          {tab === NOTICES_TAB ? (
            <AnnouncementsCard onError={setError} />
          ) : (
            groups
              .filter((group) => group.name === tab)
              .map((group) => (
                <Card key={group.name}>
                  <CardHeader className="border-b">
                    <CardTitle className="flex items-center gap-2">
                      <SlidersHorizontal className="h-4 w-4 text-muted-foreground" />
                      {group.name}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0">
                    {group.settings.map((setting) => (
                      <SettingRow key={setting.key} setting={setting} onChanged={onChanged} />
                    ))}
                    {group.name === "Model" ? <ConnectionTest /> : null}
                  </CardContent>
                </Card>
              ))
          )}
        </>
      )}

      {tab === NOTICES_TAB ? null : <History changes={changes} />}
    </>
  );
}
