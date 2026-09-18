import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "@/lib/api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("the API client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls the versioned prefix", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listRuns();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/runs");
  });

  it("never caches run data", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listRuns();
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ cache: "no-store" });
  });

  it("builds a query string from the filters it was given", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listRuns({ status: "queued", limit: 10 });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/runs?status=queued&limit=10");
  });

  it("omits the query string when there are no filters", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listRuns({});
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/runs");
  });

  it("sends a review decision as a PATCH with the note", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1 }));
    await api.reviewFinding(1, "confirmed", "raised with the ETL team");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/findings/1");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({
      review_status: "confirmed",
      review_note: "raised with the ETL team",
    });
  });

  it("posts a run as multipart without forcing a content type", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ run_id: 1 }));
    const form = new FormData();
    form.set("customer_name", "Acme");
    await api.createRun(form);
    const [, init] = fetchMock.mock.calls[0];
    expect(init.body).toBe(form);
    expect(init.headers).toBeUndefined();
  });

  it("raises an ApiError carrying the status and the detail", async () => {
    // A fresh Response per call: a body can only be read once, and asserting twice
    // against the same object would test the mock rather than the client.
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ detail: "run 9999 not found" }, 404))
    );
    await expect(api.getRun(9999)).rejects.toBeInstanceOf(ApiError);
    await expect(api.getRun(9999)).rejects.toMatchObject({
      status: 404,
      detail: "run 9999 not found",
    });
  });

  it("reads the first message out of a validation error body", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: [{ msg: "field required", loc: ["body", "customer_name"] }] }, 422)
    );
    await expect(api.createRun(new FormData())).rejects.toMatchObject({
      detail: "field required",
    });
  });

  it("falls back to the status text when the body is not JSON", async () => {
    fetchMock.mockResolvedValue(new Response("<html>502</html>", { status: 502 }));
    await expect(api.getRun(1)).rejects.toBeInstanceOf(ApiError);
  });

  it("sends edits as a PUT so the server can bump the version", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ run_id: 1, rules_version: 2, queued: true }));
    await api.editRequirements(1, [{ rule_id: "R-001", reason: "TX was agreed" }]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/runs/1/requirements");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body).edits).toHaveLength(1);
  });

  it("asks for the latest config version only when told to", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listConfigs(true);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/configs?latest_only=true");
  });
});

describe("downloading the PDF", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the bytes when the server sends a PDF", async () => {
    fetchMock.mockResolvedValue(
      new Response(new Blob([new Uint8Array([37, 80, 68, 70])], { type: "application/pdf" }), {
        status: 200,
      })
    );
    const blob = await api.fetchReportPdf(1);
    expect(blob.type).toBe("application/pdf");
  });

  it("raises rather than handing back an error body", async () => {
    // The bug this guards: a plain <a download> saved this JSON as "report.pdf".
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "playwright is not installed" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      })
    );
    await expect(api.fetchReportPdf(1)).rejects.toMatchObject({
      status: 503,
      detail: "playwright is not installed",
    });
  });

  it("raises when a 200 carries something that is not a PDF", async () => {
    fetchMock.mockResolvedValue(
      new Response(new Blob(["{}"], { type: "application/json" }), { status: 200 })
    );
    await expect(api.fetchReportPdf(1)).rejects.toThrow(/rather than a PDF/);
  });

  it("does not cache the download", async () => {
    fetchMock.mockResolvedValue(
      new Response(new Blob([""], { type: "application/pdf" }), { status: 200 })
    );
    await api.fetchReportPdf(1);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ cache: "no-store" });
  });
});
