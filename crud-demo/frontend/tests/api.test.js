import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, tokenStore } from "../src/lib/api.js";

describe("api client", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("attaches Authorization header when token present", async () => {
    tokenStore.set("abc123");
    fetch.mockResolvedValue({ ok: true, status: 200, json: async () => [] });

    await api.listTasks();

    const [, opts] = fetch.mock.calls[0];
    expect(opts.headers.Authorization).toBe("Bearer abc123");
  });

  it("does NOT attach Authorization on register/login", async () => {
    tokenStore.set("should-not-be-used");
    fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ token: "x", username: "u" }) });

    await api.login("u", "p");

    const [, opts] = fetch.mock.calls[0];
    expect(opts.headers.Authorization).toBeUndefined();
  });

  it("throws ApiError with parsed body on 4xx/5xx", async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ error: "invalid_token", message: "bad token" }),
    });

    await expect(api.listTasks()).rejects.toBeInstanceOf(ApiError);
    try { await api.listTasks(); }
    catch (e) {
      expect(e.status).toBe(401);
      expect(e.body.error).toBe("invalid_token");
    }
  });

  it("returns null for 204 No Content", async () => {
    fetch.mockResolvedValue({ ok: true, status: 204, json: async () => null });
    const out = await api.deleteTask(7);
    expect(out).toBeNull();
  });

  it("tokenStore round-trips via localStorage", () => {
    tokenStore.set("xyz");
    expect(tokenStore.get()).toBe("xyz");
    expect(localStorage.getItem("aicicd:token")).toBe("xyz");
    tokenStore.clear();
    expect(tokenStore.get()).toBeNull();
  });
});
