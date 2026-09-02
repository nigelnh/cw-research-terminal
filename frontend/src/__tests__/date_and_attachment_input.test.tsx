// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { CalendarInput } from "@/components/common/calendar_input";
import { attachmentError, MAX_ATTACHMENT_BYTES } from "@/data/ai/use_file_attachments";
import { AiChatProvider } from "@/data/ai/ai_chat_provider";
import { AiAnchor } from "@/features/ai_assistant/ai_anchor";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.localStorage.clear(); });

function DateField() {
  const [value, setValue] = useState("");
  return <><CalendarInput value={value} onChange={setValue} ariaLabel="From date" /><output>{value}</output></>;
}

describe("Editable dates", () => {
  it("opens only from the icon; typing masks separators and validates actual calendar dates", () => {
    const page = render(<DateField />);
    const field = page.getByRole("textbox", { name: "From date" }) as HTMLInputElement;
    fireEvent.click(field);
    expect(page.queryByRole("dialog")).toBeNull();
    fireEvent.change(field, { target: { value: "02292028" } });
    expect(field.value).toBe("02/29/2028");
    expect(page.getByRole("status").textContent).toBe("2028-02-29");
    fireEvent.change(field, { target: { value: "02292027" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(page.getByRole("alert").textContent).toContain("valid date");
    expect(page.queryByRole("dialog")).toBeNull();
    expect(page.getByRole("status").textContent).toBe("2028-02-29");
    fireEvent.click(page.getByRole("button", { name: "From date — open calendar" }));
    expect(page.getByRole("dialog")).toBeTruthy();
    fireEvent.click(page.getByRole("button", { name: "2028-02-15" }));
    expect(field.value).toBe("02/15/2028");
    fireEvent.click(page.getByRole("button", { name: "From date — clear" }));
    expect(field.value).toBe("");
    expect(page.getByRole("status").textContent).toBe("");
  });

  it("retains partial dates and lets Backspace move across an inserted slash", () => {
    const page = render(<DateField />);
    const field = page.getByRole("textbox") as HTMLInputElement;
    fireEvent.change(field, { target: { value: "0902" } });
    expect(field.value).toBe("09/02");
    field.setSelectionRange(3, 3);
    fireEvent.keyDown(field, { key: "Backspace" });
    expect(field.selectionStart).toBe(2);
    fireEvent.blur(field);
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(page.getByRole("status").textContent).toBe("");
  });
});

describe("File attachment preview", () => {
  it("validates count, total bytes, empty files and supported types", () => {
    const a = new File(["x"], "a.csv");
    expect(attachmentError([a, new File(["y"], "b.pdf")])).toBeNull();
    expect(attachmentError([a, a, a])).toContain("2 files");
    const large = new File(["x"], "large.csv");
    Object.defineProperty(large, "size", { value: MAX_ATTACHMENT_BYTES });
    expect(attachmentError([large, a])).toContain("20 MB");
    expect(attachmentError([new File([], "a.csv")])).toContain("empty");
    expect(attachmentError([new File(["x"], "x.exe")])).toContain("Use PDF");
  });

  it("previews local extraction, preserves attachments on minimize, and blocks file egress to AI", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ files: [{ name: "a.csv", characters: 11, warnings: [], sections: [{ location: "row 1", text: "HPG | 12345" }] }], analysis_enabled: false }), { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    const page = render(<AiChatProvider><AiAnchor /></AiChatProvider>);
    fireEvent.keyDown(page.getByRole("button", { name: "Open research assistant" }), { key: "Enter" });
    const input = page.getByLabelText("Upload research files");
    fireEvent.change(input, { target: { files: [new File(["HPG,12345"], "a.csv", { type: "text/csv" })] } });
    await waitFor(() => expect(page.getByText(/Preview a.csv/)).toBeTruthy());
    expect(fetch.mock.calls[0][0]).toContain("/api/ai/files/extract");
    expect(fetch.mock.calls[0][1].body).toBeInstanceOf(FormData);
    expect(page.getByText(/row 1/).textContent).toContain("12345");
    fireEvent.click(page.getByRole("button", { name: "Minimize conversation" }));
    fireEvent.keyDown(page.getByRole("button", { name: "Open research assistant" }), { key: "Enter" });
    expect(page.getByRole("button", { name: "Remove a.csv" })).toBeTruthy();
    const field = page.getByRole("textbox", { name: "Ask the research assistant" }) as HTMLTextAreaElement;
    fireEvent.change(field, { target: { value: "Analyse this file" } });
    fireEvent.click(page.getByRole("button", { name: "Send" }));
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(field.value).toBe("Analyse this file");
    expect(within(page.getByRole("dialog")).getByRole("status").textContent).toContain("awaits approval");
    fireEvent.click(page.getByRole("button", { name: "Remove a.csv" }));
    expect(page.queryByText(/Preview a.csv/)).toBeNull();
  });
});
