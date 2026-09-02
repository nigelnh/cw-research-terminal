# Options, editable dates, and file preview — 2026-09-02

Branch: `codex/table-filter-fixes`, isolated worktree `/private/tmp/cw-terminal-ux`. Claude's original checkout is unchanged.

Implemented UI:
- OPTIONS ANALYTICS uses the same white Rousseau Deco heading and 19px metric rows as Financial Indicators. IV bid/trade/ask, moneyness ratio/category, and vega/rho are separate rows. Quant formulas are unchanged.
- Date inputs accept numeric typing/paste, insert `/` separators, validate real dates, retain incomplete drafts, and expose the calendar only through its icon. Clear also resets incomplete dates in both registry and news filters.
- Every empty assistant greeting is centered within the conversation body in Rousseau Deco, matching the 11px RESEARCH ASSISTANT header. The input stays 36px high (two 18px lines); additional text scrolls. The @ upload control sits above Send.

## File preview is implemented; AI file analysis needs approval

The automatic approval reviewer rejected a patch that would forward uploaded document excerpts to OpenRouter. Its stated reason was that files could contain sensitive data and the user had not specifically authorized those payloads going to that external destination. That patch was not applied. No alternative route forwards file content to an AI service.

The implemented route, `POST /api/ai/files/extract`, only parses uploads and returns a preview to the requesting client. It never invokes OpenRouter, a provider file API, or other external services. With attachments present, Send preserves the question and shows that AI file analysis awaits approval; it does not call the chat endpoint. Ordinary text chat is unchanged. The app's file bytes and extracted text are memory-only; Starlette upload spools are closed after the request. No files are saved to chat history or a database.

Limits: two files, 20 MiB combined. Supported: text-bearing PDF, TXT, Markdown, CSV/TSV, JSON, XLSX, DOCX. Invalid, empty, encrypted, unsupported or unreadable files produce explicit feedback. Scanned PDFs/images require OCR and are not silently treated as text. Extraction is capped at 200,000 characters / 2,000 sections per file, with PDF page, workbook row/sheet/column, and expanded ZIP limits. A disposable process bounds CPU time; Linux also bounds parser memory, and the parent enforces a 20-second timeout. Spreadsheets expose formula text without executing it. DOCX XML external entities are rejected. The existing AI rate tier also covers extraction, while only its upload endpoint gets the larger body limit.

OpenRouter currently exposes PDF file inputs through its chat completions API and can parse PDFs for text-only models: [official PDF input documentation](https://openrouter.ai/docs/guides/overview/multimodal/pdfs). That integration has not been enabled here. The existing application's read-only AI tools are `get_quote`, `get_order_book`, `get_quant`, `get_instrument`, `get_history`, `get_dashboard_snapshot`, `get_market_status`, `get_news`, `get_corporate_actions`, and `get_company_events`, with a four-call per-turn cap. Once forwarding is approved, excerpts can be grounded with those existing services and cited by file/page/sheet/row. No file grants access to extra APIs or execution privileges.

## Local review and checks

- App: http://localhost:3001/. The existing public-market GET helper remains on 8502.
- A separate loopback-only extraction app runs on 8503 from `/private/tmp/cw-file-preview-api.py`. It imports the real extractor, rate limiter and body guard, with no upstream client. `VITE_DOCUMENT_PREVIEW_URL=http://127.0.0.1:8503` is a dev-only override.
- Parser dependencies are installed in `/private/tmp/cw-upload-deps`, not Claude's environment. Their deployment dependencies are declared in `backend/requirements.txt`.
- Verification passed: 248 frontend tests, 25 focused backend tests, TypeScript and production build (existing bundle-size warning only). Frontend tests cover actual keyboard behavior, leap dates, incomplete-date clearing, file count/bytes/types, extraction preview, minimizing with attachments, and the absence of file egress. Backend tests exercise PDF/CSV/XLSX/DOCX extraction, formula handling, malicious XML, oversized expansion, unreadable inputs, the real subprocess endpoint, upload limits and unchanged AI routing.
- Browser checks confirmed the greeting's vertical center delta is 0px, two-line input is 36px with long content scrolling to 72px, CSV preview contains exact fixture values/row labels, and typing 09022026 produces 09/02/2026 without opening a calendar. Synthetic fixtures only; no user file was sent to an external service.

Pending user decision: authorize sending excerpts from files explicitly attached for analysis to OpenRouter and its selected model provider when Send is pressed. The implementation and live/model verification of that final step remain outstanding; production deployment is separate.
