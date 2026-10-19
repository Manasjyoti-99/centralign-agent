import json
import os
from pathlib import Path
import sys
import time

from dotenv import load_dotenv
from groq import APIConnectionError, APIStatusError, Groq

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / '.env')

MAX_ATTEMPTS = 4
MAX_OUTPUT_TOKENS = 2048


def assistant_message(message):
    """Keep only fields accepted in the next chat request."""
    result = {
        'role': 'assistant',
        'content': message.content or '',
    }

    if message.tool_calls:
        result['tool_calls'] = [
            {
                'id': call.id,
                'type': 'function',
                'function': {
                    'name': call.function.name,
                    'arguments': call.function.arguments,
                },
            }
            for call in message.tool_calls
        ]

    return result


class LLMClient:
    def __init__(self):
        api_key = os.getenv('LLM_API_KEY')

        if not api_key:
            raise ValueError('LLM_API_KEY is missing from .env.')

        self.model = os.getenv(
            'LLM_MODEL',
            'openai/gpt-oss-120b',
        )
        self.verifier_model = os.getenv(
            'VERIFIER_MODEL',
            self.model,
        )

        self.client = Groq(
            api_key=api_key,
            timeout=30.0,
            max_retries=0,
        )

    def chat(
        self,
        messages,
        tools=None,
        model=None,
        tool_choice='auto',
        temperature=0,
    ):
        selected_model = model or self.model

        options = {
            'model': selected_model,
            'messages': messages,
            'temperature': temperature,
            'max_completion_tokens': MAX_OUTPUT_TOKENS,
        }

        if selected_model.startswith('openai/gpt-oss-'):
            options['reasoning_effort'] = 'low'

        if tools:
            options['tools'] = tools
            options['tool_choice'] = tool_choice
            options['parallel_tool_calls'] = False

        tool_repaired = False

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self.client.chat.completions.create(
                    **options
                )

                if not response.choices:
                    raise RuntimeError(
                        'The model returned no choices.'
                    )

                choice = response.choices[0]

                if choice.finish_reason == 'length':
                    raise RuntimeError(
                        'Model output reached MAX_OUTPUT_TOKENS.'
                    )

                return choice.message

            except (APIConnectionError, APIStatusError) as error:
                status = getattr(error, 'status_code', None)

                body = getattr(error, 'body', None)
                detail = (
                    body.get('error', body)
                    if isinstance(body, dict)
                    else {}
                )

                if not isinstance(detail, dict):
                    detail = {}

                missing_tool = (
                    status == 400
                    and detail.get('code') == 'tool_use_failed'
                    and 'did not call a tool' in str(
                        detail.get('message', '')
                    ).lower()
                )

                can_repair = (
                    missing_tool
                    and tools
                    and not tool_repaired
                    and attempt < MAX_ATTEMPTS - 1
                )

                if can_repair:
                    names = [
                        item['function']['name']
                        for item in tools
                    ]

                    if 'finish' in names:
                        target = 'finish'
                    elif len(names) == 1:
                        target = names[0]
                    else:
                        target = None

                    if target:
                        options['tool_choice'] = {
                            'type': 'function',
                            'function': {'name': target},
                        }

                        instruction = (
                            'The previous response was rejected '
                            'before tool execution. '
                            f'Return exactly one {target} tool call '
                            'with its required arguments. '
                            'Do not repeat earlier actions or '
                            'return a normal text reply.'
                        )

                        repaired = [
                            dict(item)
                            for item in messages
                        ]

                        if (
                            repaired
                            and repaired[0].get('role') == 'system'
                        ):
                            repaired[0]['content'] = (
                                (repaired[0].get('content') or '')
                                + '\n\n'
                                + instruction
                            )
                        else:
                            repaired.insert(0, {
                                'role': 'system',
                                'content': instruction,
                            })

                        options['messages'] = repaired
                        tool_repaired = True

                        print(
                            '[llm] Missing tool call; '
                            f'retrying with {target}.'
                        )
                        continue

                # Other invalid requests need an actual fix.
                if (
                    status is not None
                    and status < 500
                    and status not in (408, 429)
                ):
                    raise

                if attempt == MAX_ATTEMPTS - 1:
                    raise

                delay = (
                    20 * (attempt + 1)
                    if status == 429
                    else 2 ** (attempt + 1)
                )

                response = getattr(error, 'response', None)
                headers = getattr(response, 'headers', {})

                try:
                    delay = max(
                        0.0,
                        float(headers.get('retry-after', delay)),
                    )
                except (TypeError, ValueError):
                    pass

                if delay > 60:
                    raise RuntimeError(
                        f'Provider requested a {delay:.0f}s wait. '
                        'Retry later or change the model in .env.'
                    ) from error

                print(
                    f'[llm] {type(error).__name__}: '
                    f'retry {attempt + 1}/{MAX_ATTEMPTS - 1} '
                    f'in {delay:.1f}s'
                )

                time.sleep(delay)

        raise RuntimeError('LLM unavailable after retries.')

    def complete(self, messages, temperature=0.2):
        return self.chat(
            messages,
            temperature=temperature,
        ).content or ''


def test_tool_roundtrip(llm):
    tools = [{
        'type': 'function',
        'function': {
            'name': 'add_numbers',
            'description': 'Add two integers.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'a': {'type': 'integer'},
                    'b': {'type': 'integer'},
                },
                'required': ['a', 'b'],
                'additionalProperties': False,
            },
        },
    }]

    messages = [
        {
            'role': 'system',
            'content': (
                'Use exactly one tool call for the calculation. '
                'After receiving its result, reply with only '
                'the number.'
            ),
        },
        {
            'role': 'user',
            'content': 'Add 7 and 5 using add_numbers.',
        },
    ]

    message = llm.chat(
        messages,
        tools=tools,
        tool_choice='required',
    )
    calls = message.tool_calls or []

    if (
        len(calls) != 1
        or calls[0].function.name != 'add_numbers'
    ):
        raise RuntimeError(
            'Expected exactly one add_numbers tool call.'
        )

    call = calls[0]
    arguments = json.loads(call.function.arguments)

    if (
        not isinstance(arguments, dict)
        or set(arguments) != {'a', 'b'}
    ):
        raise RuntimeError(
            'Tool arguments must contain a and b.'
        )

    if any(
        type(value) is not int
        for value in arguments.values()
    ):
        raise RuntimeError('Tool arguments must be integers.')

    if sorted(arguments.values()) != [5, 7]:
        raise RuntimeError(
            'The model requested the wrong numbers.'
        )

    total = arguments['a'] + arguments['b']

    print('Requested tool:', call.function.name)
    print('Arguments:', arguments)
    print('Python tool result:', total)

    messages.append(assistant_message(message))
    messages.append({
        'role': 'tool',
        'tool_call_id': call.id,
        'content': str(total),
    })

    reply = llm.complete(
        messages,
        temperature=0,
    ).strip()

    print('Model reply:', reply)

    if reply != '12':
        raise RuntimeError(
            'Expected the final model reply to be 12.'
        )

    print('Tool round-trip passed.')


if __name__ == '__main__':
    llm = LLMClient()
    print('Model:', llm.model)

    if '--test-tools' in sys.argv:
        test_tool_roundtrip(llm)
    else:
        print(llm.complete([
            {
                'role': 'user',
                'content': 'Say hello briefly.',
            },
        ]))