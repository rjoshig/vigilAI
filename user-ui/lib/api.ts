/**
 * The typed client. Every backend call goes through here; components never call
 * `fetch` (standards/frontend.md).
 *
 * Requests are `no-store`: run and finding data changes while a reviewer is looking at
 * it, and a cached page showing a decided finding as undecided would be worse than a
 * slightly slower one.
 */

import type {
  CloneResult,
  ConfigDetail,
  ConfigSummary,
  CreateRunResult,
  Finding,
  RecheckResult,
  Requirements,
  ReviewStatus,
  RunDetail,
  RunStats,
  RunSummary,
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

  /**
   * Create a run from uploaded files.
   *
   * Returns a result whose `duplicate` is set when the same inputs were already run;
   * the caller then asks for a reason and submits again with `rerun_reason`.
   */
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

  /** Mark every undecided low-severity finding as confirmed. */
  bulkOkLow(runId: number): Promise<number> {
    return request<number>(`/runs/${runId}/findings/bulk-ok`, { method: "POST" });
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

  /** Read stage timings, calls, tokens, and cache hits. */
  getStats(runId: number): Promise<RunStats> {
    return request<RunStats>(`/runs/${runId}/stats`);
  },

  /** List captured configs. */
  listConfigs(latestOnly = false): Promise<ConfigSummary[]> {
    return request<ConfigSummary[]>(`/configs${latestOnly ? "?latest_only=true" : ""}`);
  },

  /** Read one captured config with its content. */
  getConfig(configId: number): Promise<ConfigDetail> {
    return request<ConfigDetail>(`/configs/${configId}`);
  },
};
