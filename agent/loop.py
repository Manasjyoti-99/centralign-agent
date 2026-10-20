import json
import traceback

from groq import BadRequestError

from agent.browser import Browser
from agent.guard import Guard
from agent.llm import LLMClient, assistant_message
from agent.prompts import SYSTEM_PROMPT
from agent.state import AgentState
from agent.tools import TOOL_DEFINITIONS, TOOL_SCHEMAS, Tools
from agent.trace import Trace
from agent.verifier import Verifier

BROWSER_TOOLS = ('open_url', 'get_page', 'fill', 'click')


def clip(text, limit):
    if len(text) <= limit:
        return text
    return text[:limit] + '\n[Output truncated.]'


def current_page(browser):
    if browser.page.url == 'about:blank':
        return 'No page opened yet. Use app_url to open the app.'

    try:
        page = json.loads(browser.get_page())

        return {
            'url': page['url'],
            'text': clip(page['text'], 3000),
            'fields': [
                {
                    'selector': field['selector'],
                    'value': field['selected'] or field['value'],
                    **(
                        {'options': field['options']}
                        if field['options'] else {}
                    ),
                }
                for field in page['fields']
            ],
            'buttons': page['buttons'],
            'links': page['links'],
            'error': page['error'],
        }

    except Exception as error:
        return f'ERROR: Cannot read the current page: {error}'


def source_evidence(state):
    documents = []
    budget = 12000

    for path, text in state.documents.items():
        if budget <= 0:
            excerpt = '[Omitted for prompt size; use remembered facts.]'
        else:
            excerpt = clip(text, min(4000, budget))
            budget -= len(excerpt)

        documents.append({'path': path, 'text': excerpt})

    return documents


def recent_messages(exchanges):
    messages = []

    for assistant, observation in exchanges[-2:]:
        messages.extend([
            assistant,
            {
                **observation,
                'content': clip(observation['content'], 1500),
            },
        ])

    return messages


def tool_summary(name, result):
    if result.startswith('ERROR'):
        return clip(result.splitlines()[0], 1200)

    if name in BROWSER_TOOLS:
        return 'Action succeeded. See the CURRENT_STATE page.'

    if name == 'read_pdf':
        return (
            'PDF read. Its text is retained in '
            'CURRENT_STATE source_evidence.'
        )

    if name == 'list_files':
        return (
            'Files listed. Results are retained in '
            'CURRENT_STATE file_lists.'
        )

    return clip(result, 1200)


def run_agent(
    goal,
    max_steps=25,
    headless=None,
    approve=None,
    ask_human=None,
):
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError('Provide a non-empty task.')

    if not 1 <= max_steps <= 25:
        raise ValueError('max_steps must be between 1 and 25.')

    state = AgentState(goal.strip())
    trace = Trace(state.goal)
    browser = None
    step = 0

    try:
        llm = LLMClient()

        trace.data.update(
            model=llm.model,
            verifier_model=llm.verifier_model,
        )
        trace.log(
            'models',
            model=llm.model,
            verifier_model=llm.verifier_model,
        )

        browser = Browser(headless=headless)
        guard = Guard(browser, state, trace, approve=approve)
        verifier = Verifier(browser, state, llm, trace)

        tools = Tools(
            browser,
            state,
            guard,
            trace,
            ask_human=ask_human,
            finish=verifier.verify,
        )

        exchanges = []
        file_lists = {}
        action_log = []
        feedback = ''

        print('Worker model:', llm.model)
        print('Verifier model:', llm.verifier_model)
        print('Trace:', trace.path)

        for step in range(1, max_steps + 1):
            context = {
                'goal': state.goal,
                'app_url': browser.app_url,
                'step': step,
                'steps_remaining': max_steps - step + 1,
                'state': state.context(),
                'file_lists': file_lists,
                'source_evidence': source_evidence(state),
                'action_log': action_log[-12:],
                'page': current_page(browser),
                'feedback': feedback,
            }

            messages = [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': 'Task: ' + state.goal},
                *recent_messages(exchanges),
                {
                    'role': 'user',
                    'content': 'CURRENT_STATE\n' + json.dumps(
                        context,
                        ensure_ascii=False,
                    ),
                },
            ]

            print(
                f'\n[step {step}/{max_steps}] Waiting for model...',
                flush=True,
            )

            try:
                response = llm.chat(
                    messages,
                    tools=TOOL_DEFINITIONS,
                    tool_choice='auto',
                )

            except BadRequestError as error:
                body = error.body
                detail = (
                    body.get('error', body)
                    if isinstance(body, dict) else {}
                )

                if (
                    not isinstance(detail, dict)
                    or detail.get('code') != 'tool_use_failed'
                ):
                    raise

                feedback = (
                    'ERROR: The provider rejected the tool response. '
                    'No local tool was executed. Choose one available '
                    'tool using its exact name, or give a normal final '
                    'reply for verification.'
                )
                trace.log(
                    'model_protocol_error',
                    step=step,
                    error=str(error),
                )
                print(feedback)
                continue

            calls = response.tool_calls or []

            if not calls:
                reply = (response.content or '').strip()

                if not reply:
                    feedback = (
                        'ERROR: Empty response. '
                        'Use a tool or give a final reply.'
                    )
                    trace.log(
                        'model_protocol_error',
                        step=step,
                        error=feedback,
                    )
                    print(feedback)
                    continue

                # The harness requests verification of ordinary text.
                trace.log(
                    'text_completion_request',
                    step=step,
                    worker_report=reply,
                )
                print(
                    '[worker] Final reply received; '
                    'requesting independent verification.'
                )

                result = tools.execute(
                    'finish',
                    {'message': reply, 'completed': True},
                )

                trace.screenshot(browser)
                action_log.append({
                    'step': step,
                    'action': 'verify_final_reply',
                    'result': clip(result, 300),
                })
                print(clip(result, 500))

                if state.status != 'running':
                    break

                feedback = result
                continue

            try:
                if len(calls) != 1:
                    raise ValueError(
                        'Request exactly one tool call. '
                        'None were executed.'
                    )

                call = calls[0]
                name = call.function.name

                if name not in TOOL_SCHEMAS:
                    raise ValueError(f'Unknown tool: {name}')

                arguments = json.loads(call.function.arguments)

                if not isinstance(arguments, dict):
                    raise ValueError(
                        'Tool arguments must be a JSON object.'
                    )

            except (ValueError, TypeError) as error:
                feedback = f'ERROR: {error}'
                trace.log(
                    'model_protocol_error',
                    step=step,
                    error=feedback,
                    response=assistant_message(response),
                )
                print(feedback)
                continue

            feedback = ''
            print(name, json.dumps(arguments, ensure_ascii=False))
            trace.log('step', step=step, tool=name)

            result = tools.execute(name, arguments)

            if name == 'list_files' and not result.startswith('ERROR'):
                file_lists[arguments.get('path') or '.'] = json.loads(
                    result
                )

            summary = tool_summary(name, result)

            action_log.append({
                'step': step,
                'tool': name,
                'arguments': {
                    key: (
                        clip(value, 200)
                        if isinstance(value, str) else value
                    )
                    for key, value in arguments.items()
                },
                'result': clip(summary, 300),
            })

            if name in BROWSER_TOOLS or name == 'finish':
                trace.screenshot(browser)

            exchanges.append((
                assistant_message(response),
                {
                    'role': 'tool',
                    'tool_call_id': call.id,
                    'content': summary,
                },
            ))
            exchanges = exchanges[-2:]

            shown_result = (
                summary if name in BROWSER_TOOLS else result
            )
            print(clip(shown_result, 500))

            # A real denial ends worker execution.
            if any(
                item['approved'] is False
                for item in state.approvals
            ):
                trace.log('approval_denied_stop', step=step)

                print(
                    '[guard] Approval denied; stopping worker and '
                    'verifying the blocked outcome.'
                )

                blocked_result = tools.execute(
                    'finish',
                    {
                        'message': (
                            'Approval was denied. Stop this run and report '
                            'the blocked outcome without further actions.'
                        ),
                        'completed': False,
                    },
                )

                trace.screenshot(browser)
                print(clip(blocked_result, 500))

                if state.status == 'running':
                    state.status = 'failed'
                    state.final_message = (
                        'Approval was denied. The blocked outcome could '
                        'not be independently verified. '
                        + clip(blocked_result, 500)
                    )

                break

            # Only independent verification can confirm completion.
            if state.status != 'running':
                break

        else:
            state.status = 'failed'
            state.final_message = (
                'Step limit reached; task completion is unverified.'
            )

    except KeyboardInterrupt:
        state.status = 'cancelled'
        state.final_message = 'Run cancelled by the user.'

    except Exception as error:
        state.status = 'failed'
        state.final_message = f'{type(error).__name__}: {error}'
        trace.log(
            'fatal_error',
            error=state.final_message,
            traceback=traceback.format_exc(),
        )
        traceback.print_exc()

    finally:
        trace.finish(state.status, state.final_message)

        if browser is not None:
            try:
                browser.close()
            except Exception as error:
                trace.log('browser_cleanup_error', error=str(error))

    return {
        'status': state.status,
        'message': state.final_message,
        'steps': step,
        'trace_path': str(trace.path),
    }