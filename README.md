# CentrAlign Agent — Vendor Bills worker

A Python task worker that takes a natural-language request, chooses tools, controls a local browser, and verifies the saved outcome.

The sandbox app and browser run on the laptop. Language-model requests use Groq over the internet.

**Demo video:** [Watch the captioned demonstration](https://youtu.be/Yt18Zs27Rl4)

## What it does

Example task:

> Find the latest invoice from Globex Logistics, enter it into the Vendor Bills system, and tell me when it is done.

The worker can:

- Read synthetic invoice PDFs and enter bills through the browser.

- Convert date formats and calculate dates from explicit payment terms.

- Ask the human for missing information.

- Request approval before submitting or saving.

- Recover from app errors, including an injected one-time HTTP 503.

- Check persisted records independently of its own completion claim.

- Save JSON traces and screenshots.

The same worker also updated Acme Supplies' payment terms to `net 45` through the browser, with approval and independent verification. This different task used the existing loop and tools without a task-specific code change.

## Setup and run

Developed with Python 3.13 on Windows and VS Code.

Run these PowerShell commands individually:

```powershell
git clone https://github.com/Manasjyoti-99/centralign-agent.git
cd centralign-agent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
Copy-Item .env.example .env
```

[constraints-tested.txt](constraints-tested.txt) records the direct dependency versions from the working Windows Python 3.13.9 environment. To select those recorded versions instead of the unpinned defaults, use:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -c constraints-tested.txt
```

This is a record of tested direct versions, not a complete lockfile of transitive dependencies. The local regression checks below were also run on Python 3.12; the full Windows agent setup was developed on Python 3.13.

Edit `.env` and supply your own Groq API key. The recorded demo used the following model configuration:

```dotenv
LLM_API_KEY=replace_with_your_groq_api_key
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-120b
VERIFIER_MODEL=openai/gpt-oss-120b
APP_URL=http://localhost:5000
HEADLESS=0
```

For the manually selected quota fallback, set both model variables to `openai/gpt-oss-20b`. Results below identify which model each latest evaluation used.

Existing terminal environment variables take precedence over `.env`.

The client uses the official `groq` Python SDK and its default endpoint. `LLM_BASE_URL` is retained in configuration but is not passed to that SDK.

Generate the sample invoices and initialize the database:

```powershell
.\.venv\Scripts\python.exe -m data.generate_invoices
.\.venv\Scripts\python.exe -m app.seed
```

In terminal 1, start the app and leave it running:

```powershell
.\.venv\Scripts\python.exe -m app.server
```

In terminal 2, from the project folder:

```powershell
.\.venv\Scripts\python.exe -m agent.main "Find the latest invoice from Globex Logistics, enter it into the Vendor Bills system, and tell me when it is done."
```

A different task uses the same entry point:

```powershell
.\.venv\Scripts\python.exe -m agent.main "Update the payment terms for Acme Supplies to 45 days."
```

Chromium opens automatically. Inspect the displayed form values before entering `y` at an approval prompt. Pressing Enter without typing `y`, or entering `n`, denies approval and ends the run. Answer missing-information questions in the terminal.

`HEADLESS=1` hides Chromium; terminal approvals still apply.

The seeded database contains GLX-2201. A successful Globex run adds GLX-2305, amount 1920.00, due 2026-10-17.

To reset this sandbox, open the following URL in your ordinary browser:

```text
http://localhost:5000/admin/reset?flaky=0
```

Use `flaky=1` to make the first valid bill submission return HTTP 503. Resetting removes previous sandbox edits. The agent cannot access admin routes.

## Architecture

```mermaid
flowchart TD
    A["Natural-language goal"] --> B["Worker model and bounded loop"]
    B --> C["Validated tools and approval guard"]
    C --> D["PDFs and Playwright browser"]
    D --> E["Local Flask app and SQLite"]
    D --> B
    B --> F["Independent verifier"]
    E --> F
    F -->|"Mismatch feedback"| B
    F --> G["Verified result and trace"]
```

| Component | Responsibility |
|---|---|
| `agent/loop.py` | Up to 25 worker turns, tool execution, observations, and verification feedback. |
| `agent/llm.py` | Groq calls, function-call messages, bounded retries, and response handling. |
| `agent/prompts.py` | General instructions for tool use, source grounding, recovery, and verification. |
| `agent/browser.py` | Chromium control, text snapshots, dropdown selection, origin restrictions, and fresh-page reads. |
| `agent/tools.py` | Tool schemas, argument validation, restricted file access, PDF extraction, date arithmetic, clarification, and finish requests. |
| `agent/guard.py` | Approval tied to the inspected page, action and form values; changed approvals and repeated failures are blocked. |
| `agent/state.py` | Scratchpad, document evidence, human answers, approvals, and run status. |
| `agent/verifier.py` | Independent saved-record checks, source grounding, model judgment, and a deterministic denied-bill check. |
| `agent/trace.py` | JSON event logs, screenshots, final status, and configured-key redaction. |
| `app/` | Flask sandbox, SQLite database, validation, seeded data, and failure injection. |
| `evals/` | Scenario definitions, SQLite checks, trace audits, and attempt history. |
| `tests/` | Local regression tests for approval, source checks and fresh saved-record checks; no model calls. |
| `constraints-tested.txt` | Recorded direct dependency versions from the working Windows environment. |

## Design decisions

### Handwritten agent loop

No agent framework is used. The model chooses actions through a fixed tool interface; Python validates and executes them. This makes the control flow and safety boundaries easier to inspect and explain.

The worker receives general instructions about discovering information, grounding values, recovering from errors, and verifying outcomes. It does not receive a fixed sequence of invoice-processing steps.

### Text observations

The model receives page text, field values, selectors, buttons, and links. Screenshots are saved as evidence for humans.

This reduces prompt size but limits the prototype to interfaces that expose useful text and form structure.

### Persistent evidence and bounded execution

PDF text, file lists, a short action log, human answers, and scratchpad survive between turns. Older tool exchanges are trimmed to reduce repeated reads and context loss.

Runs are limited to 25 worker turns. Network and rate-limit retries are bounded. Repeated navigation triggers a temporary restriction on redundant navigation choices.

### Controls enforced outside the model

File access is restricted to `data/`. Browser navigation is restricted to the configured app origin, and admin routes are blocked.

The guard inspects click targets and asks for approval before write-like actions, including submit/save buttons. It records the page URL, target action and form values before asking. After `y`, it compares that snapshot with the current page, repeats source validation for a bill, then checks the snapshot again immediately before allowing the click. A change or inspection failure blocks the click and requires fresh approval; it is logged as `approval_invalidated`, not a human denial.

Bill source checks compare vendor, invoice number, amount and due date against original documents and relevant human answers. An explicit denial stops further worker execution and keeps writes blocked for the run.

### Independent verification

A final text reply or `finish` call requests verification; it does not declare success.

For completion checks, the verifier reloads visited URLs in fresh tabs, rereads original PDFs, and makes a separate model call without the worker's final claim. It checks the goal against saved records and source evidence. Verification failure returns feedback to the worker.

An additional source prerequisite rejects bill completion when a required due date has no supported source or human answer. Saved-bill checks use approved record identifiers and identifiers explicitly requested in the goal. A candidate rejected before approval stays in the audit but does not become an extra record that must exist. Approval itself is never proof that a row was saved or has correct values.

For a denied new-bill submission, verification is deterministic: it checks the actual guard event sequence and opens the saved Bills table in a fresh tab to confirm the invoice is absent. This produces `not_completed`, never task completion. Other completion and blocker checks continue through the model verifier.

## Local regression checks

Run from the project folder after installing dependencies:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

All **18 local regression tests passed** during the 22 October review. They exercise the real tools, guard, PDF source checks and saved-record verification with in-memory browser stubs. Cases include correcting a rejected invoice typo, changes during approval, source changes during the pause, explicit denial, missing due dates, and incorrect or absent saved records. They need no Flask server, browser installation, API key or model quota beyond the installed Python dependencies.

These local checks cover code behavior. They are separate from the historical browser-and-model evaluations below; no new live model evaluation was performed for the review fixes.

## Evaluation and results

Keep the app running. Run one case at a time:

```powershell
.\.venv\Scripts\python.exe -m evals.run_evals --list
.\.venv\Scripts\python.exe -m evals.run_evals globex_latest
```

Run the full suite with:

```powershell
.\.venv\Scripts\python.exe -m evals.run_evals --all
```

Each case resets the sandbox. Do not run another agent concurrently.

Approvals and clarification answers are scripted only by the evaluation harness. They still pass through the normal tools and guard.

The grader checks SQLite before and after each run: exact saved values, existing records, new-record count, and permitted vendor edits. It also checks approval events, clarification timing, retry evidence, fresh-page evidence, and final status.

### Development results

Latest results: **8/8 tested scenarios passed**, with **8/8 coverage**.

Across all recorded development attempts at the 21 October checkpoint: **16/24 passed (66.7%)**.

| Scenario | Latest result | Worker model |
|---|---|---|
| Globex latest invoice | PASS | `openai/gpt-oss-20b` |
| Acme date conversion | PASS | `openai/gpt-oss-20b` |
| Temporary HTTP 503 recovery | PASS | `openai/gpt-oss-20b` |
| Duplicate left unchanged | PASS | `openai/gpt-oss-20b` |
| Missing due date → human clarification | PASS | `openai/gpt-oss-20b` |
| Explicit net-45 calculation | PASS | `openai/gpt-oss-120b` |
| Approval denied → no bill created | PASS | `openai/gpt-oss-20b` |
| Vendor payment-term update | PASS | `openai/gpt-oss-20b` |

These outcomes span code revisions and models. They are not a single full-suite run on the final revision or a fixed-version reliability estimate.

See [evals/results.md](evals/results.md) and `evals/results.json` for attempt history, timings, models, and failed checks. Earlier failures are retained, including an unsupported date initially accepted by the model verifier and provider quota failures.

### Execution evidence

`runs/sample_run/trace.json` and its screenshots preserve an earlier successful Globex execution using `openai/gpt-oss-120b`.

New executions save their traces and screenshots locally under `runs/<UTC timestamp>/`.

To run the verifier check against the seeded bill:

```powershell
.\.venv\Scripts\python.exe -m agent.verifier
```

The latest check accepted saved GLX-2201 amount 1200.00 and rejected an explicit target amount of 9999.00.

This self-check compares an incorrect expected amount against a saved record. A separate historical manual tampering test, before the approval snapshot fix, also produced a saved amount of 9999.00 for GLX-2305; source-backed verification rejected it against the PDF amount of 1920.00. That run was then cancelled manually. Detection did not automatically repair or roll back the saved record. See the [manual tampering trace](runs/sample_run/tamper_check/trace.json). Current approval checks stop a changed form before the click; the historical trace is retained unchanged.

The [fresh-clone browser screenshot](runs/sample_run/fresh_clone/browser_check.png) records a Windows setup smoke check: separate virtual environment, database seeding, imports, Flask startup, and Chromium navigation/form filling passed. It was not a complete agent run.

## Assumptions and known limitations

- This is a narrow prototype using synthetic data and a controlled local app.

- Groq requires internet access and a user-provided API key. Free-tier quotas can prevent completion.

- Provider-requested waits above 60 seconds stop the request rather than hanging indefinitely.

- Development used `openai/gpt-oss-120b`; `openai/gpt-oss-20b` was used as a quota fallback. Results are labeled by model.

- Native text PDFs are supported. Scanned documents need OCR, which is not implemented.

- Documents and evidence have size limits.

- The worker loop is reusable, but selectors, snapshots, the bill date prerequisite, and the denied-bill rule assume this sandbox's structure.

- The model verifier is fallible. Source checks and independent database evaluations reduce errors without proving universal correctness.

- The guard checks the current snapshot before the click. It does not atomically bind an outgoing HTTP request against arbitrary page scripts or concurrent changes after the last check.

- Final verification happens after writes and does not roll them back. The app has no bill-edit workflow for automatic correction.

- The app has no production authentication, concurrent-user isolation, or accounting/currency precision model.

- Runs have a 25-step limit and no restart/resume support.

- Correct selection of the latest document is not guaranteed on every attempt.

## Models, APIs, and libraries

- Models: `openai/gpt-oss-120b` and `openai/gpt-oss-20b`, hosted by Groq.

- API client: official `groq` Python SDK with OpenAI-style function-call schemas.

- Browser: Playwright Chromium, synchronous API.

- App: Flask and Python's SQLite module.

- Documents: ReportLab and pypdf.

- Configuration: python-dotenv.

- Dependencies: [requirements.txt](requirements.txt); recorded direct versions: [constraints-tested.txt](constraints-tested.txt). The regression tests use Python's standard-library `unittest`, with pypdf for the existing fixtures.

- No LangChain or other agent framework is used.

## AI coding assistance

ChatGPT/Codex assisted with planning, code drafting, debugging, documentation, and demo preparation. The runtime uses the Python modules and libraries listed above; ChatGPT is not part of the running application.

## What I would build next

1. Repeated full-suite runs on a frozen revision and model.

2. Stronger structured comparisons between original sources and saved records.

3. A bill-correction workflow and validation of the outgoing write request.

4. Resumable execution and better recovery from provider limits.

5. OCR and adapters for additional apps, after improving reliability.
