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

  it("uploads an artifact sample as multipart, to that type's own path", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1 }));
    const file = new File(["x"], "billing.xlsx");
    await api.uploadSample("billing", file);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/artifact-types/billing/sample");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
  });

  it("deletes a scope by its code", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await api.deleteScope("ARCHIVE");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/scopes/ARCHIVE");
    expect(init.method).toBe("DELETE");
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

  it("reads the auth switches from the auth prefix, not the admin one", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ admin_auth: false, user_auth: false }));
    await api.getAuthConfig();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/auth/config");
  });

  it("posts a sign-in as JSON", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1, name: "Ada" }));
    await api.login("ada", "a-long-enough-password");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/auth/login");
    expect(JSON.parse(init.body)).toEqual({
      username: "ada",
      password: "a-long-enough-password",
    });
  });

  it("surfaces a lockout as a 423 rather than a wrong-password 401", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "account is locked" }, 423));
    await expect(api.login("ada", "wrong")).rejects.toMatchObject({ status: 423 });
  });

  it("returns nothing for a 204 sign-out", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api.logout()).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
  });

  it("sends the username and both passwords when changing one", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1, must_change_password: false }));
    await api.changePassword("ada", "old-password", "new-password");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/auth/change-password");
    expect(JSON.parse(init.body)).toEqual({
      username: "ada",
      current_password: "old-password",
      new_password: "new-password",
    });
  });

  it("lists accounts under the admin prefix", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listUsers();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/admin/users");
  });

  it("creates an account with its role", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 2 }, 201));
    await api.createUser({
      username: "ada",
      name: "Ada Lovelace",
      email: "ada@example.com",
      password: "a-long-enough-password",
      role: "admin",
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/users");
    expect(JSON.parse(init.body).role).toBe("admin");
  });

  it("resets a password on that account's own path", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 2, must_change_password: true }));
    await api.resetUserPassword(2, "a-long-enough-password");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/users/2/password");
    expect(JSON.parse(init.body)).toEqual({ password: "a-long-enough-password" });
  });

  it("toggles an account with a query parameter", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 2, is_active: false }));
    await api.setUserActive(2, false);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/users/2/active?is_active=false");
    expect(init.method).toBe("POST");
  });

  it("raises the last-administrator refusal as a 409", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "last active administrator" }, 409));
    await expect(api.setUserActive(2, false)).rejects.toMatchObject({ status: 409 });
  });

  it("lists the settings under the admin prefix", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listSettings();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/admin/settings");
  });

  it("posts one setting as a key and a value", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ key: "llm.max_tokens", source: "admin" }));
    await api.saveSetting("llm.max_tokens", 4096);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/settings");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ key: "llm.max_tokens", value: 4096 });
  });

  it("reverts a setting by deleting its key", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ key: "llm.model", source: "env" }));
    await api.revertSetting("llm.model");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/settings/llm.model");
    expect(init.method).toBe("DELETE");
  });

  it("raises the missing-master-key refusal as a 409", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "VIGILAI_SECRET_KEY is not set on the server" }, 409)
    );
    await expect(api.saveSetting("llm.api_key", "sk-x")).rejects.toMatchObject({ status: 409 });
  });

  it("asks for the last hundred changes by default", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.settingsHistory();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/admin/settings/history?limit=100");
  });

  it("tests the model with a POST and no body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true, provider: "mock", latency_ms: 3 }));
    const result = await api.testModel();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/settings/test-model");
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
    expect(result.ok).toBe(true);
  });

  it("reads the first message out of a validation error body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: [{ msg: "field required" }] }, 422));
    await expect(api.testExpression("")).rejects.toMatchObject({ detail: "field required" });
  });
});
