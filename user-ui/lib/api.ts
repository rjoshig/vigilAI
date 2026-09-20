/**
 * The typed client. Every backend call goes through here; components never call
 * `fetch` (standards/frontend.md).
 *
 * Requests are `no-store`: run and finding data changes while a reviewer is looking at
 * it, and a cached page showing a decided finding as undecided would be worse than a
 * slightly slower one.
 */

import type {
  AuthConfig,
  CloneResult,
  ConfigDetail,
  ConfigNoteInput,
  ConfigSummary,
  CreateRunResult,
  CurrentUser,
  FinalizeResult,
  Finding,
  NewRunOptions,
  Observation,
  ObservationInput,
  RecheckResult,
  Requirements,
  ReviewStatus,
  RunDetail,
  RunStats,
  RunSummary,
  TrainingConfig,
  TypeDetection,
  Coverage,
  Drift,
  ExploreArtifact,
  SamplePreview,
} from "@/lib/types";

/** Where the API lives. The Next rewrite proxies this to FastAPI, so there is no CORS. */
const BASE = "/api/v1";

/** An error carrying the status, so a caller can tell 404 from 409 from a timeout. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail || `request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** Read the error message out of a FastAPI response body. */
async function errorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail) && detail.length > 0) {
        const first: unknown = detail[0];
        if (first && typeof first === "object" && "msg" in first) {
          return String((first as { msg: unknown }).msg);
        }
      }
      return JSON.stringify(detail);
    }
  } catch {
    // A non-JSON body (a proxy error page, say) has no detail to read.
  }
  return response.statusText;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    throw new ApiError(response.status, await errorDetail(response));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface ListRunsParams {
  customer?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export const api = {
  /**
   * Which login switches are on. Safe to call unauthenticated, and the answer decides
   * whether any login prompt is drawn at all (ADR-022).
   */
  getAuthConfig(): Promise<AuthConfig> {
    return request<AuthConfig>("/auth/config");
  },

  /** Who is signed in. 401 when login is on and the session cookie is missing. */
  getCurrentUser(): Promise<CurrentUser> {
    return request<CurrentUser>("/auth/me");
  },

  /** Sign in. 401 is wrong credentials, 423 is an account locked after repeated failures. */
  login(username: string, password: string): Promise<CurrentUser> {
    return request<CurrentUser>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  },

  /** Sign out, which ends the server-side session rather than only dropping the cookie. */
  logout(): Promise<void> {
    return request<void>("/auth/logout", { method: "POST" });
  },

  /** Replace the password an administrator set. 422 carries the rule that was broken. */
  changePassword(
    username: string,
    currentPassword: string,
    newPassword: string
  ): Promise<CurrentUser> {
    return request<CurrentUser>("/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username,
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
  },

  /** List runs, newest first. */
  listRuns(params: ListRunsParams = {}): Promise<RunSummary[]> {
    const query = new URLSearchParams();
    if (params.customer) query.set("customer", params.customer);
    if (params.status) query.set("status", params.status);
    if (params.limit) query.set("limit", String(params.limit));
    if (params.offset) query.set("offset", String(params.offset));
    const suffix = query.toString() ? `?${query}` : "";
    return request<RunSummary[]>(`/runs${suffix}`);
  },

  /** Read one run. Polled every three seconds while it is queued or running. */
  getRun(runId: number): Promise<RunDetail> {
    return request<RunDetail>(`/runs/${runId}`);
  },

  /** What changed since the previous finalized run of the same configuration. */
  getDrift(runId: number): Promise<Drift> {
    return request<Drift>(`/runs/${runId}/drift`);
  },

  /**
   * Create a run from uploaded files.
   *
   * Returns a result whose `duplicate` is set when the same inputs were already run;
   * the caller then asks for a reason and submits again with `rerun_reason`.
   */
  /**
   * What the new-run form should offer: the active upload slots and the delivery
   * programmes. Generated from the admin catalog, so switching a report type off
   * removes its slot without a deploy.
   */
  getRunOptions(): Promise<NewRunOptions> {
    return request<NewRunOptions>("/runs/options");
  },

  createRun(form: FormData): Promise<CreateRunResult> {
    return request<CreateRunResult>("/runs", { method: "POST", body: form });
  },

  /** List a run's findings, worst first. */
  listFindings(runId: number): Promise<Finding[]> {
    return request<Finding[]>(`/runs/${runId}/findings`);
  },

  /** Record a decision on one finding. Sent immediately, never batched. */
  reviewFinding(findingId: number, reviewStatus: ReviewStatus, reviewNote = ""): Promise<Finding> {
    return request<Finding>(`/findings/${findingId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ review_status: reviewStatus, review_note: reviewNote }),
    });
  },

  /** Mark every undecided low-severity finding OK, as a false positive. */
  bulkOkLow(runId: number): Promise<number> {
    return request<number>(`/runs/${runId}/findings/bulk-ok`, { method: "POST" });
  },

  /** The samples a reviewer can explore, grouped by artifact type (Phase 6.1e). */
  listSamples(): Promise<ExploreArtifact[]> {
    return request<ExploreArtifact[]>("/samples");
  },

  /** What one sample contains: cells with their labels, sections, or JSON paths. */
  previewSample(sampleId: number): Promise<SamplePreview> {
    return request<SamplePreview>(`/samples/${sampleId}/preview`);
  },

  /** What the run checked and what it did not (Phase 6.11c). */
  getCoverage(runId: number): Promise<Coverage> {
    return request<Coverage>(`/runs/${runId}/coverage`);
  },

  /**
   * Record that a person has seen one or more coverage gaps.
   *
   * Not a decision that the delivery is fine: the record that the gap was in front of
   * somebody before the report was frozen, which is what the gate asks for.
   */
  acknowledgeCoverage(runId: number, targets: string[], note = ""): Promise<number> {
    return request<number>(`/runs/${runId}/coverage/acknowledge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targets, note }),
    });
  },

  /** Read the traceability matrix. */
  getRequirements(runId: number): Promise<Requirements> {
    return request<Requirements>(`/runs/${runId}/requirements`);
  },

  /** Edit requirements or trace links; the server bumps the version and re-checks. */
  editRequirements(
    runId: number,
    edits: {
      rule_id: string;
      rule?: Record<string, unknown>;
      element_id?: string | null;
      clear_link?: boolean;
      reason?: string;
    }[]
  ): Promise<RecheckResult> {
    return request<RecheckResult>(`/runs/${runId}/requirements`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ edits }),
    });
  },

  /** Queue a re-check without editing anything. */
  recheck(runId: number): Promise<RecheckResult> {
    return request<RecheckResult>(`/runs/${runId}/recheck`, { method: "POST" });
  },

  /** Create a draft run prefilled from an existing one. */
  cloneRun(runId: number): Promise<CloneResult> {
    return request<CloneResult>(`/runs/${runId}/clone`, { method: "POST" });
  },

  /**
   * Render and freeze the final report.
   *
   * Refused with 409 when the run is already finalized or when a high-severity finding
   * still has no decision (ADR-005, ADR-015).
   */
  finalize(runId: number): Promise<FinalizeResult> {
    return request<FinalizeResult>(`/runs/${runId}/finalize`, { method: "POST" });
  },

  /** Where the stored report is served. Used as an iframe source and a link. */
  reportUrl(runId: number): string {
    return `${BASE}/runs/${runId}/report`;
  },

  /** Where the PDF is served. Rendered from the stored HTML on first request. */
  reportPdfUrl(runId: number): string {
    return `${BASE}/runs/${runId}/report.pdf`;
  },

  /**
   * Fetch the PDF and hand the caller the bytes.
   *
   * A plain `<a href download>` cannot check a status: when the endpoint answers 503
   * because this deployment has no browser installed, the anchor happily saves the
   * JSON error body as a file called `report.pdf`. So the request goes through the
   * client, which raises on a non-2xx, and only a real PDF ever reaches the disk.
   */
  async fetchReportPdf(runId: number): Promise<Blob> {
    const response = await fetch(this.reportPdfUrl(runId), { cache: "no-store" });
    if (!response.ok) {
      throw new ApiError(response.status, await errorDetail(response));
    }
    const blob = await response.blob();
    if (blob.type && !blob.type.includes("pdf")) {
      throw new ApiError(
        response.status,
        `the server returned ${blob.type} rather than a PDF; the report is still available as HTML`
      );
    }
    return blob;
  },

  /** Read stage timings, calls, tokens, and cache hits. */
  getStats(runId: number): Promise<RunStats> {
    return request<RunStats>(`/runs/${runId}/stats`);
  },

  /**
   * Work out what an uploaded workbook is, before a run exists.
   *
   * The endpoint stores nothing, so this is safe to call as soon as a file is chosen.
   * A caller treats a failure as "no opinion": detection is a convenience and must
   * never stand between a person and a submission.
   */
  detectType(file: File): Promise<TypeDetection> {
    const form = new FormData();
    form.set("file", file);
    return request<TypeDetection>("/runs/detect-type", { method: "POST", body: form });
  },

  /**
   * Whether Train AI mode is on. When it is off, no other training endpoint is called
   * and nothing about training is drawn (ADR-021).
   */
  getTrainingConfig(): Promise<TrainingConfig> {
    return request<TrainingConfig>("/training/config");
  },

  /**
   * Record something a reviewer knows. 422 means the text looks like it contains
   * personal data; its detail is written for the person to read and act on, so a
   * caller shows it verbatim rather than replacing it with wording of its own.
   */
  createObservation(body: ObservationInput): Promise<Observation> {
    return request<Observation>("/observations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  /** The caller's own observations, so an author can follow what became of what they wrote. */
  listMyObservations(): Promise<Observation[]> {
    return request<Observation[]>("/observations?mine=true");
  },

  /** Correct an observation. 409 once an administrator has picked it up. */
  updateObservation(observationId: number, body: ObservationInput): Promise<Observation> {
    return request<Observation>(`/observations/${observationId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  /** List captured configs. */
  listConfigs(latestOnly = false): Promise<ConfigSummary[]> {
    return request<ConfigSummary[]>(`/configs${latestOnly ? "?latest_only=true" : ""}`);
  },

  /** Read one captured config with its content. */
  getConfig(configId: number): Promise<ConfigDetail> {
    return request<ConfigDetail>(`/configs/${configId}`);
  },

  /**
   * The standing notes on an ETL configuration (ADR-024). Only the notes in force
   * unless asked otherwise, because a switched-off note is history rather than
   * guidance. Available whether or not Train AI mode is on.
   */
  listConfigNotes(configurationId: string, includeInactive = false): Promise<Observation[]> {
    const suffix = includeInactive ? "?include_inactive=true" : "";
    return request<Observation[]>(`/configs/${encodeURIComponent(configurationId)}/notes${suffix}`);
  },

  /**
   * Write a note against a configuration. 422 means the text looks like personal
   * data; the detail is written for the person, so a caller shows it verbatim.
   */
  createConfigNote(configurationId: string, body: ConfigNoteInput): Promise<Observation> {
    return request<Observation>(`/configs/${encodeURIComponent(configurationId)}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  /** Reword a note. Always allowed; the server keeps the earlier wording in `revisions`. */
  updateConfigNote(noteId: number, body: ConfigNoteInput): Promise<Observation> {
    return request<Observation>(`/config-notes/${noteId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  /** Switch a note off or back on. Off stops it reaching the model on the next run. */
  setConfigNoteActive(noteId: number, isActive: boolean): Promise<Observation> {
    return request<Observation>(`/config-notes/${noteId}/active?is_active=${isActive}`, {
      method: "POST",
    });
  },
};
