import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Login } from "../src/components/Login.jsx";

describe("<Login />", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders sign-in form by default", () => {
    render(<Login onLoggedIn={() => {}} />);
    expect(screen.getByRole("heading", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("toggles to register mode and back", async () => {
    const user = userEvent.setup();
    render(<Login onLoggedIn={() => {}} />);
    await user.click(screen.getByRole("button", { name: /need an account/i }));
    expect(screen.getByRole("heading", { name: /create account/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /already have one/i }));
    expect(screen.getByRole("heading", { name: /sign in/i })).toBeInTheDocument();
  });

  it("calls onLoggedIn with token+username on success", async () => {
    fetch.mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ token: "tok-123", username: "alice" }),
    });
    const onLoggedIn = vi.fn();
    const user = userEvent.setup();

    render(<Login onLoggedIn={onLoggedIn} />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "long-enough-pw");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(onLoggedIn).toHaveBeenCalledWith({ token: "tok-123", username: "alice" });
  });

  it("shows error message on 401 and does NOT call onLoggedIn", async () => {
    fetch.mockResolvedValue({
      ok: false, status: 401,
      json: async () => ({ error: "invalid_credentials", message: "invalid username or password" }),
    });
    const onLoggedIn = vi.fn();
    const user = userEvent.setup();

    render(<Login onLoggedIn={onLoggedIn} />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(onLoggedIn).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid username or password/i);
  });
});
