import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "@/lib/api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("the admin API client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls the admin prefix", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listChecks();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/admin/checks");
  });

  it("never caches admin data", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listNamedValues();
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ cache: "no-store" });
  });

  it("uploads a template as multipart", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1 }));
    const file = new File(["x"], "billing.xlsx");
    await api.uploadTemplate("billing", file);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/templates");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("report_type")).toBe("billing");
  });

  it("sends a check as JSON", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1, version: 1 }));
    await api.saveCheck({
      name: "billing_not_above_delivered",
      kind: "expression",
      expression: "billing_count <= delivered_count",
      instruction: "",
      reasoning: "Billing must not exceed delivered.",
      severity: "high",
      scope: "all",
      is_active: true,
    });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body).expression).toBe("billing_count <= delivered_count");
  });

  it("toggles a check with a query parameter", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 3, is_active: false }));
    await api.setCheckActive(3, false);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/checks/3/active?is_active=false");
    expect(init.method).toBe("PATCH");
  });

  it("sends a draft request with the description", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ named_values: [], expression: "" }));
    await api.draftCheck("Billing must not exceed delivered.");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/checks/draft");
    expect(JSON.parse(init.body).description).toBe("Billing must not exceed delivered.");
  });

  it("tests an expression without sending anything else", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ passed: true, detail: "", resolved: {} }));
    await api.testExpression("a <= b");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ expression: "a <= b" });
  });

  it("returns nothing for a 204 delete", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api.deleteAlias(1)).resolves.toBeUndefined();
  });

  it("raises an ApiError carrying the conflict detail", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ detail: "billing_count is used by two checks" }, 409))
    );
    await expect(api.deleteNamedValue(1)).rejects.toBeInstanceOf(ApiError);
    await expect(api.deleteNamedValue(1)).rejects.toMatchObject({ status: 409 });
  });

  it("reads the first message out of a validation error body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: [{ msg: "field required" }] }, 422));
    await expect(api.testExpression("")).rejects.toMatchObject({ detail: "field required" });
  });
});
