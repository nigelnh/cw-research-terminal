// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, fireEvent, cleanup, screen, waitFor } from "@testing-library/react";

const signInWithGoogle = vi.fn(async () => {});
const signInWithEmail = vi.fn(async (_email: string) => ({ ok: true, message: "Check your email for a sign-in link." }));
const signUpWithPassword = vi.fn(async (_u: string, _e: string, _p: string) => ({ ok: true, message: "Account created." }));
const signInWithPassword = vi.fn(async (_e: string, _p: string) => ({ ok: true, message: "" }));

let googleEnabled = false;

vi.mock("@/data/auth", () => ({
  useAuth: () => ({
    signInWithGoogle, signInWithEmail, signUpWithPassword, signInWithPassword,
    user: null, status: "anonymous", isConfigured: true, signOut: vi.fn(),
  }),
  isGoogleAuthEnabled: () => googleEnabled,
}));

import { SignInDialog } from "@/features/auth/sign_in_dialog";

beforeEach(() => {
  googleEnabled = false;
  signInWithGoogle.mockClear();
  signInWithEmail.mockClear();
  signUpWithPassword.mockClear();
  signInWithPassword.mockClear();
});
afterEach(cleanup);

function renderDialog(onClose = vi.fn()) {
  render(<SignInDialog onClose={onClose} />);
  return { onClose };
}

describe("SignInDialog", () => {
  it("defaults to the Sign in tab: email + password, no username field", () => {
    renderDialog();
    expect(screen.getByPlaceholderText("you@example.com")).toBeTruthy();
    expect(screen.getByPlaceholderText("Password")).toBeTruthy();
    expect(screen.queryByPlaceholderText("Username")).toBeNull();
  });

  it("switching to Create account reveals the username field", () => {
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByPlaceholderText("Username")).toBeTruthy();
  });

  function submitButton(name: string): HTMLElement {
    // The tab button and the form's submit button can share the same accessible name
    // ("Sign in" on the Sign in tab, "Create account" on the Create account tab).
    const match = screen.getAllByRole("button", { name }).find((b) => b.getAttribute("type") === "submit");
    if (!match) throw new Error(`no submit button named "${name}"`);
    return match;
  }

  it("submitting Sign in calls signInWithPassword with the entered credentials", async () => {
    renderDialog();
    fireEvent.change(screen.getByPlaceholderText("you@example.com"), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByPlaceholderText("Password"), { target: { value: "hunter22" } });
    fireEvent.click(submitButton("Sign in"));
    await waitFor(() => expect(signInWithPassword).toHaveBeenCalledWith("a@b.com", "hunter22"));
    expect(signUpWithPassword).not.toHaveBeenCalled();
  });

  it("submitting Create account calls signUpWithPassword with username, email, password", async () => {
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    fireEvent.change(screen.getByPlaceholderText("Username"), { target: { value: "nigelnh" } });
    fireEvent.change(screen.getByPlaceholderText("you@example.com"), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByPlaceholderText("Password"), { target: { value: "hunter22" } });
    fireEvent.click(submitButton("Create account"));
    await waitFor(() => expect(signUpWithPassword).toHaveBeenCalledWith("nigelnh", "a@b.com", "hunter22"));
  });

  it("shows the resolved message after a submit", async () => {
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    fireEvent.change(screen.getByPlaceholderText("Username"), { target: { value: "nigelnh" } });
    fireEvent.change(screen.getByPlaceholderText("you@example.com"), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByPlaceholderText("Password"), { target: { value: "hunter22" } });
    fireEvent.click(submitButton("Create account"));
    await waitFor(() => expect(screen.getByText("Account created.")).toBeTruthy());
  });

  it("shows an error message from a rejected submit and keeps the entered email", async () => {
    signInWithPassword.mockResolvedValueOnce({ ok: false, message: "Invalid email or password." });
    renderDialog();
    fireEvent.change(screen.getByPlaceholderText("you@example.com"), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByPlaceholderText("Password"), { target: { value: "wrong" } });
    fireEvent.click(submitButton("Sign in"));
    await waitFor(() => expect(screen.getByText("Invalid email or password.")).toBeTruthy());
    expect((screen.getByPlaceholderText("you@example.com") as HTMLInputElement).value).toBe("a@b.com");
  });

  it("'Or email me a sign-in link' calls signInWithEmail with the typed email, only on the Sign in tab", async () => {
    renderDialog();
    fireEvent.change(screen.getByPlaceholderText("you@example.com"), { target: { value: "a@b.com" } });
    fireEvent.click(screen.getByText("Or email me a sign-in link"));
    await waitFor(() => expect(signInWithEmail).toHaveBeenCalledWith("a@b.com"));

    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.queryByText("Or email me a sign-in link")).toBeNull();
  });

  it("Continue as Guest closes the dialog without calling any auth method", () => {
    const { onClose } = renderDialog();
    fireEvent.click(screen.getByText("Continue as Guest →"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(signInWithPassword).not.toHaveBeenCalled();
    expect(signInWithGoogle).not.toHaveBeenCalled();
  });

  it("Escape closes the dialog", () => {
    const { onClose } = renderDialog();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Google button only renders when the provider is enabled", () => {
    googleEnabled = false;
    const { unmount } = render(<SignInDialog onClose={vi.fn()} />);
    expect(screen.queryByText("Continue with Google")).toBeNull();
    unmount();

    googleEnabled = true;
    render(<SignInDialog onClose={vi.fn()} />);
    fireEvent.click(screen.getByText("Continue with Google"));
    expect(signInWithGoogle).toHaveBeenCalledTimes(1);
  });

  it("clicking inside the dialog card does not close it (only the backdrop does)", () => {
    const { onClose } = renderDialog();
    fireEvent.click(screen.getByPlaceholderText("you@example.com"));
    expect(onClose).not.toHaveBeenCalled();
  });
});
