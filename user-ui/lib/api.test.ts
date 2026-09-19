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

describe("the auth endpoints", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads the switches without sending anything", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ admin_auth: false, user_auth: false }));
    const config = await api.getAuthConfig();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/auth/config");
    expect(config.user_auth).toBe(false);
  });

  it("asks who is signed in", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1, name: "John Doe" }));
    await api.getCurrentUser();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/auth/me");
  });

  it("posts the credentials as JSON", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1, name: "John Doe" }));
    await api.login("jdoe", "a-long-enough-password");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/auth/login");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      username: "jdoe",
      password: "a-long-enough-password",
    });
  });

  it("keeps a locked account distinguishable from wrong credentials", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "account temporarily locked" }, 423));
    await expect(api.login("jdoe", "wrong")).rejects.toMatchObject({ status: 423 });
  });

  it("tolerates the empty body a sign-out returns", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api.logout()).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/auth/logout");
  });

  it("sends the current and new passwords under the wire names", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1, must_change_password: false }));
    await api.changePassword("jdoe", "bootstrap-password", "a-new-long-password");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/auth/change-password");
    expect(JSON.parse(init.body)).toEqual({
      username: "jdoe",
      current_password: "bootstrap-password",
      new_password: "a-new-long-password",
    });
  });

  it("carries the server's wording when the new password is refused", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: [{ msg: "password must be at least 12 characters" }] }, 422)
    );
    await expect(api.changePassword("jdoe", "old", "short")).rejects.toMatchObject({
      detail: "password must be at least 12 characters",
    });
  });
});

describe("several files per report slot", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("carries repeated file entries and their labels in the same order", async () => {
    // The server pairs the nth label with the nth file, so order is the contract:
    // a swap here mislabels every finding that names a file.
    fetchMock.mockResolvedValue(jsonResponse({ run_id: 1 }));
    const form = new FormData();
    form.append("field_distribution", new File(["a"], "north.xlsx"));
    form.append("field_distribution", new File(["b"], "south.xlsx"));
    form.append("field_distribution__label", "north");
    form.append("field_distribution__label", "south");
    await api.createRun(form);

    const [, init] = fetchMock.mock.calls[0];
    const sent = init.body as FormData;
    expect(sent.getAll("field_distribution").map((f) => (f as File).name)).toEqual([
      "north.xlsx",
      "south.xlsx",
    ]);
    expect(sent.getAll("field_distribution__label")).toEqual(["north", "south"]);
  });

  it("still posts a single file per slot with no labels", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ run_id: 1 }));
    const form = new FormData();
    form.append("dirt", new File(["a"], "dirt.xlsx"));
    await api.createRun(form);
    const sent = fetchMock.mock.calls[0][1].body as FormData;
    expect(sent.getAll("dirt")).toHaveLength(1);
    expect(sent.getAll("dirt__label")).toEqual([]);
  });
});

describe("workbook type detection", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the workbook as multipart under the field the endpoint reads", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ verdict: "confident", key: "dirt", label: "DIRT", score: 0.9 })
    );
    const detection = await api.detectType(new File(["x"], "mystery.xlsx"));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/runs/detect-type");
    expect(init.method).toBe("POST");
    expect(((init.body as FormData).get("file") as File).name).toBe("mystery.xlsx");
    expect(detection.verdict).toBe("confident");
  });

  it("raises so the caller can fall back to the slot the user picked", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "could not read that file" }, 400));
    await expect(api.detectType(new File(["x"], "notes.txt"))).rejects.toMatchObject({
      status: 400,
    });
  });
});

describe("the training endpoints", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads the switch", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ enabled: false }));
    const config = await api.getTrainingConfig();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/training/config");
    expect(config.enabled).toBe(false);
  });

  it("posts an observation as JSON with its anchors", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 7 }, 201));
    await api.createObservation({
      kind: "field_constraint",
      anchors: [
        {
          kind: "finding",
          artifact: "",
          sheet: "",
          cell: "",
          field: "",
          reference: "F-003",
          value: "count mismatch",
        },
      ],
      statement: "this column is never blank for account review",
      expectation: "never blank",
      severity_hint: "medium",
      scope_hint: "customer",
      run_id: 4,
      finding_id: 12,
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/observations");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body);
    expect(body.scope_hint).toBe("customer");
    expect(body.anchors[0].reference).toBe("F-003");
  });

  it("carries the server's wording when the text looks like personal data", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { detail: "this looks like it contains personal data, so it was not saved" },
        422
      )
    );
    await expect(
      api.createObservation({
        kind: "note",
        anchors: [],
        statement: "account 1234 is wrong",
        expectation: "",
        severity_hint: "low",
        scope_hint: "customer",
      })
    ).rejects.toMatchObject({
      status: 422,
      detail: "this looks like it contains personal data, so it was not saved",
    });
  });

  it("asks only for the caller's own observations", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listMyObservations();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/observations?mine=true");
  });

  it("edits an observation with a PATCH and surfaces the 409 once it is locked", async () => {
    const body = {
      kind: "note" as const,
      anchors: [],
      statement: "a corrected sentence",
      expectation: "",
      severity_hint: "low" as const,
      scope_hint: "customer" as const,
    };
    fetchMock.mockResolvedValue(jsonResponse({ id: 7, version: 2 }));
    await api.updateObservation(7, body);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/observations/7");
    expect(init.method).toBe("PATCH");

    fetchMock.mockResolvedValue(jsonResponse({ detail: "already queued" }, 409));
    await expect(api.updateObservation(7, body)).rejects.toMatchObject({ status: 409 });
  });
});
