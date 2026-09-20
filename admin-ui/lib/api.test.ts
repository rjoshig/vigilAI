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

  it("adds an artifact sample as multipart, with its label", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1 }, 201));
    const file = new File(["x"], "billing.xlsx");
    await api.addSample("billing", file, "2026 layout");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/artifact-types/billing/samples");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
    expect((init.body as FormData).get("label")).toBe("2026 layout");
  });

  it("refuses a fourth sample as a 409", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "already has 3 samples; remove one before adding another" }, 409)
    );
    await expect(api.addSample("billing", new File(["x"], "b.xlsx"))).rejects.toMatchObject({
      status: 409,
    });
  });

  it("builds a plain download URL rather than fetching the workbook", async () => {
    expect(api.sampleDownloadUrl("billing", 7)).toBe(
      "/api/v1/admin/artifact-types/billing/samples/7/download"
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("previews one sample by its own id", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ sample_id: 7, sheets: [] }));
    await api.previewSample("billing", 7);
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/admin/artifact-types/billing/samples/7/preview"
    );
  });

  it("returns nothing when a sample is deleted", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api.deleteSample("billing", 7, "delete")).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE");
    expect(String(fetchMock.mock.calls[0][0])).toContain("confirm=delete");
  });

  it("deletes a scope by its code", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await api.deleteScope("ARCHIVE", "delete");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/scopes/ARCHIVE?confirm=delete");
    expect(init.method).toBe("DELETE");
  });

  it("sends a check as JSON", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1, version: 1 }));
    await api.saveCheck({
      name: "billing_not_above_delivered",
      kind: "expression",
      expression: "billing_count <= delivered_count",
      instruction: "",
      value_names: [],
      reasoning: "Billing must not exceed delivered.",
      severity: "high",
      scope: "all",
      is_active: true,
    });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body).expression).toBe("billing_count <= delivered_count");
  });

  it("sends a worked example, answer and all", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1, stage: "s2_extract" }));
    await api.saveExample({
      stage: "s2_extract",
      scope: "everywhere",
      given: { section: "9 Channel\nDeliver by SFTP only." },
      answer: { requirements: [{ req_type: "other" }] },
      note: "",
      is_active: true,
      sort_order: 0,
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/examples");
    expect(JSON.parse(init.body).answer.requirements[0].req_type).toBe("other");
  });

  it("promotes a decision somebody already confirmed", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 2, stage: "s4_trace" }));
    await api.promoteExample({ source: "meaning", id: 7 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/examples/promote");
    expect(JSON.parse(init.body)).toEqual({ source: "meaning", id: 7 });
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
    await expect(api.deleteAlias(1, "delete")).resolves.toBeUndefined();
  });

  it("raises an ApiError carrying the conflict detail", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ detail: "billing_count is used by two checks" }, 409))
    );
    await expect(api.deleteNamedValue(1, "delete")).rejects.toBeInstanceOf(ApiError);
    await expect(api.deleteNamedValue(1, "delete")).rejects.toMatchObject({ status: 409 });
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
      jsonResponse({ detail: "GREENLIGHT_AI_SECRET_KEY is not set on the server" }, 409)
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

  it("reads observations from the shared prefix, because users file them", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listObservations();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/observations?status=new");
  });

  it("passes the kind filter through only when one is given", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listObservations("new", "config_note");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/observations?status=new&kind=config_note");
  });

  it("reads the Train AI switch from the shared prefix, like the user app", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ enabled: true }));
    const config = await api.getTrainingConfig();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/training/config");
    expect(config.enabled).toBe(true);
  });

  it("switches a configuration note off with a query parameter and no body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 9, is_active: false }));
    await api.setConfigNoteActive(9, false);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/config-notes/9/active?is_active=false");
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
  });

  it("surfaces Train AI mode being off as a 404 rather than swallowing it", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Train AI mode is off" }, 404));
    await expect(api.listObservations()).rejects.toMatchObject({ status: 404 });
  });

  it("rejects an observation with the reason its author will read", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 4, status: "rejected" }));
    await api.rejectObservation(4, "already covered by an existing check");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/observations/4/reject");
    expect(JSON.parse(init.body)).toEqual({ reason: "already covered by an existing check" });
  });

  it("synthesizes from the selected observation ids", async () => {
    fetchMock.mockResolvedValue(jsonResponse([{ id: 1 }], 201));
    await api.synthesize([3, 4]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/candidates");
    expect(JSON.parse(init.body)).toEqual({ observation_ids: [3, 4] });
  });

  it("raises an already-synthesized observation as a 409", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "observation 3 is already synthesized" }, 409)
    );
    await expect(api.synthesize([3])).rejects.toMatchObject({ status: 409 });
  });

  it("sends one statement and its scope to the front door", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ surface: "check", candidate: null }));
    await api.tellTheTool("Billing count must never exceed the delivered count.", "everywhere");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/front-door");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      statement: "Billing count must never exceed the delivered count.",
      scope: "everywhere",
    });
  });

  it("lists draft candidates by default", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listCandidates();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/admin/candidates?status=draft");
  });

  it("replays a candidate with a POST and no body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1, replay: { runs_examined: 12 } }));
    await api.replayCandidate(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/candidates/1/replay");
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
  });

  it("approves into shadow unless activation is asked for explicitly", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ id: 1, status: "approved" }))
    );
    await api.approveCandidate(1);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({});
    await api.approveCandidate(1, { activate_now: true, scope: "AM" });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      activate_now: true,
      scope: "AM",
    });
  });

  it("rejects a candidate with its reason", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1, status: "rejected" }));
    await api.rejectCandidate(1, "too broad");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/candidates/1/reject");
    expect(JSON.parse(init.body)).toEqual({ reason: "too broad" });
  });

  it("lists active rules by default and passes the search through", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse([])));
    await api.listRules();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/admin/rules?state=active&search=");
    await api.listRules("all", "billing count");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/admin/rules?state=all&search=billing%20count");
  });

  it("sends the typed word with a rule action", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 5, state: "disabled" }));
    await api.actOnRule("check", 5, "disable", "disable", "too noisy");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/rules/check/5/action");
    expect(JSON.parse(init.body)).toEqual({
      action: "disable",
      confirm: "disable",
      note: "too noisy",
    });
  });

  it("raises a mistyped confirmation as a 400 from the API", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "type 'delete' to confirm" }, 400));
    await expect(api.actOnRule("check", 5, "delete", "")).rejects.toMatchObject({ status: 400 });
  });

  it("raises an expired restore window as a 409", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "the restore window has passed" }, 409));
    await expect(api.actOnRule("check", 5, "restore", "restore")).rejects.toMatchObject({
      status: 409,
    });
  });

  it("reads a rule's history on its own path", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.ruleHistory("field_constraint", 9);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/admin/rules/field_constraint/9/history");
  });

  it("lists every programme's rules when no programme is named", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listProgrammeRules();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/admin/programme-rules");
  });

  it("passes the programme code through only when one is given", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await api.listProgrammeRules("AS");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/admin/programme-rules?scope_code=AS");
  });

  it("creates a programme rule with a POST body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 3, state: "active" }, 201));
    await api.createProgrammeRule({
      scope_code: "AS",
      title: "Opt-out honoured",
      text: "Every delivery excludes opted-out consumers.",
      strictness: "must",
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/programme-rules");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      scope_code: "AS",
      title: "Opt-out honoured",
      text: "Every delivery excludes opted-out consumers.",
      strictness: "must",
    });
  });

  it("edits a programme rule with a PATCH on its own path", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 3, strictness: "should" }));
    await api.updateProgrammeRule(3, {
      scope_code: "AS",
      title: "Opt-out honoured",
      text: "Every delivery excludes opted-out consumers.",
      strictness: "should",
      sort_order: 10,
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/programme-rules/3");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toMatchObject({ strictness: "should", sort_order: 10 });
  });

  it("raises an unknown programme as a 404 when creating a rule", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "unknown programme" }, 404));
    await expect(
      api.createProgrammeRule({ scope_code: "NOPE", title: "x", text: "y", strictness: "advisory" })
    ).rejects.toMatchObject({ status: 404 });
  });

  it("changes a programme rule's state through the rules action endpoint", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 3, state: "disabled" }));
    await api.actOnRule("programme_rule", 3, "disable", "disable");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/admin/rules/programme_rule/3/action");
  });

  it("reads the first message out of a validation error body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: [{ msg: "field required" }] }, 422));
    await expect(api.testExpression("")).rejects.toMatchObject({ detail: "field required" });
  });
});

describe("typed deletes and bulk actions (ADR-032)", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the ids and the word to the bulk endpoint", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ deleted: 2, missing: [] }));
    const result = await api.bulkDelete("aliases", [1, 2], "delete");
    expect(result.deleted).toBe(2);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/aliases/bulk-delete");
    expect(JSON.parse(String(init.body))).toEqual({ ids: [1, 2], confirm: "delete" });
  });

  it("sends a bulk rule action with the action word", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ changed: 1, failed: [] }));
    await api.actOnRules([{ rule_kind: "check", id: 3 }], "disable", "disable");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/rules/bulk");
    expect(JSON.parse(String(init.body)).action).toBe("disable");
  });
});
