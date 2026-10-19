from datetime import date as calendar_date, timedelta
import json
from pathlib import Path

from pypdf import PdfReader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = (PROJECT_ROOT / 'data').resolve()


def tool(name, description, fields, required=None):
    return {
        'type': 'function',
        'function': {
            'name': name,
            'description': description,
            'parameters': {
                'type': 'object',
                'properties': {
                    key: {'type': kind}
                    for key, kind in fields.items()
                },
                'required': (
                    list(fields) if required is None else required
                ),
                'additionalProperties': False,
            },
        },
    }


TOOL_DEFINITIONS = [
    tool(
        'list_files',
        'List files recursively under data. Default path: .',
        {'path': 'string'},
        required=[],
    ),
    tool(
        'read_pdf',
        'Read PDF text under data; use a path from list_files.',
        {'path': 'string'},
    ),
    tool(
        'open_url',
        'Open an app URL or relative path.',
        {'url': 'string'},
    ),
    tool(
        'get_page',
        'Read current page text, fields, buttons and links.',
        {},
    ),
    tool(
        'fill',
        'Fill a field; for dropdowns use the visible option label.',
        {'selector': 'string', 'value': 'string'},
    ),
    tool(
        'click',
        'Click one element; approval is enforced by Python.',
        {'selector': 'string'},
    ),
    tool(
        'remember',
        'Store a short fact in the persistent scratchpad.',
        {'key': 'string', 'value': 'string'},
    ),
    tool(
        'add_days',
        'Add integer days to a strict YYYY-MM-DD date.',
        {'date': 'string', 'days': 'integer'},
    ),
    tool(
        'ask_human',
        'Ask for essential missing information; do not guess.',
        {'question': 'string'},
    ),
    tool(
        'finish',
        'Request verification of a final report. Set completed '
        'false if blocked or unable to complete.',
        {'message': 'string', 'completed': 'boolean'},
    ),
]

TOOL_SCHEMAS = {
    item['function']['name']: item['function']['parameters']
    for item in TOOL_DEFINITIONS
}


def safe_data_path(path):
    candidate = Path(path)

    if not candidate.is_absolute():
        if candidate.parts and candidate.parts[0] == 'data':
            candidate = PROJECT_ROOT / candidate
        else:
            candidate = DATA_DIR / candidate

    candidate = candidate.resolve()

    if not candidate.is_relative_to(DATA_DIR):
        raise ValueError(
            'Access outside the data folder is blocked.'
        )

    return candidate


def list_files(path='.'):
    folder = safe_data_path(path)

    if not folder.is_dir():
        raise ValueError('The requested folder does not exist.')

    files = sorted(
        item.relative_to(DATA_DIR).as_posix()
        for item in folder.rglob('*')
        if item.is_file() and '__pycache__' not in item.parts
    )

    return {
        'files': files[:100],
        'truncated': len(files) > 100,
    }


def read_pdf_document(path):
    document = safe_data_path(path)

    if not document.is_file() or document.suffix.lower() != '.pdf':
        raise ValueError('Choose an existing PDF inside data.')

    if document.stat().st_size > 5_000_000:
        raise ValueError(
            'PDF exceeds this prototype\'s 5 MB limit.'
        )

    reader = PdfReader(document)

    if len(reader.pages) > 10:
        raise ValueError(
            'PDF exceeds this prototype\'s 10-page limit.'
        )

    text = '\n'.join(
        page.extract_text() or ''
        for page in reader.pages
    ).strip()

    if not text:
        raise ValueError(
            'No readable text. Scanned PDFs are unsupported.'
        )

    if len(text) > 12000:
        raise ValueError(
            'PDF text exceeds the 12000-character prompt limit.'
        )

    return {
        'path': document.relative_to(DATA_DIR).as_posix(),
        'text': text,
    }


class Tools:
    def __init__(
        self,
        browser,
        state,
        guard,
        trace,
        ask_human=None,
        finish=None,
    ):
        self.browser = browser
        self.state = state
        self.guard = guard
        self.trace = trace
        self.ask_human = (
            ask_human if ask_human is not None else input
        )
        self.finish = finish

    def _validate(self, name, arguments):
        if name not in TOOL_SCHEMAS:
            raise ValueError(f'Unknown tool: {name}')

        if not isinstance(arguments, dict):
            raise ValueError(
                'Tool arguments must be a JSON object.'
            )

        schema = TOOL_SCHEMAS[name]
        properties = schema['properties']

        missing = set(schema['required']) - set(arguments)
        extra = set(arguments) - set(properties)

        if missing or extra:
            raise ValueError(
                f'Missing arguments: {sorted(missing)}; '
                f'unexpected arguments: {sorted(extra)}'
            )

        types = {
            'string': str,
            'integer': int,
            'boolean': bool,
        }

        for key, value in arguments.items():
            expected = types[properties[key]['type']]

            if type(value) is not expected:
                raise ValueError(
                    f'{key} must be {properties[key]["type"]}.'
                )

    def execute(self, name, arguments):
        try:
            self._validate(name, arguments)

            blocked = self.guard.check(name, arguments)

            if blocked is not None:
                result = blocked
            else:
                result = self._run(name, arguments)

            if not isinstance(result, str):
                result = json.dumps(
                    result,
                    ensure_ascii=False,
                )

        except Exception as error:
            result = f'ERROR: {type(error).__name__}: {error}'

        self.guard.record_result(name, arguments, result)

        self.trace.log(
            'tool',
            tool=name,
            arguments=arguments,
            observation=result,
        )

        return result

    def _run(self, name, arguments):
        if name == 'list_files':
            return list_files(**arguments)

        if name == 'read_pdf':
            document = read_pdf_document(**arguments)
            self.state.documents[document['path']] = document['text']
            return document

        if name in ('open_url', 'get_page', 'fill', 'click'):
            return getattr(self.browser, name)(**arguments)

        if name == 'remember':
            return self.state.remember(**arguments)

        if name == 'add_days':
            day = calendar_date.fromisoformat(arguments['date'])

            if day.isoformat() != arguments['date']:
                raise ValueError(
                    'Date must use strict YYYY-MM-DD format.'
                )

            return (
                day + timedelta(days=arguments['days'])
            ).isoformat()

        if name == 'ask_human':
            question = arguments['question'].strip()

            if not question:
                raise ValueError('Question cannot be empty.')

            answer = self.ask_human(
                question + '\nYour answer: '
            ).strip()

            if not answer:
                raise ValueError(
                    'No answer supplied. Do not assume a value.'
                )

            record = {
                'question': question,
                'answer': answer,
            }

            self.state.human_answers.append(record)
            self.trace.log('human_answer', **record)

            return record

        if name == 'finish':
            if self.finish is None:
                raise RuntimeError(
                    'Independent verifier is not connected.'
                )

            return self.finish(**arguments)

        raise ValueError(f'Unknown tool: {name}')


if __name__ == '__main__':
    from agent.guard import Guard
    from agent.state import AgentState
    from agent.trace import Trace

    state = AgentState(
        'Check file tools, dates and required verification.'
    )
    trace = Trace(state.goal)
    guard = Guard(None, state, trace)
    tools = Tools(None, state, guard, trace)

    def checked(name, arguments):
        result = tools.execute(name, arguments)

        if result.startswith('ERROR'):
            raise RuntimeError(result)

        return result

    try:
        files = json.loads(
            checked('list_files', {'path': 'invoices'})
        )
        print('Invoice files found:', len(files['files']))

        document = json.loads(
            checked('read_pdf', {
                'path': 'invoices/globex_GLX-2305.pdf',
            })
        )

        if 'GLX-2305' not in document['text']:
            raise RuntimeError(
                'Expected invoice text was not extracted.'
            )

        print('PDF text extracted:', document['path'])

        print(checked('remember', {
            'key': 'test_fact',
            'value': 'hello',
        }))

        result = checked('add_days', {
            'date': '2026-10-05',
            'days': 45,
        })

        if result != '2026-11-19':
            raise RuntimeError('Date calculation check failed.')

        print('Date calculation:', result)

        blocked = tools.execute('read_pdf', {
            'path': '../outside.pdf',
        })

        if 'Access outside the data folder is blocked.' not in blocked:
            raise RuntimeError('File boundary check failed.')

        print('Outside-data access blocked.')

        blocked = tools.execute('finish', {
            'message': 'Test report',
            'completed': True,
        })

        if 'Independent verifier is not connected.' not in blocked:
            raise RuntimeError(
                'Verifier requirement check failed.'
            )

        print('Finish requires the verifier.')

        trace.finish('completed', 'Tools smoke check passed.')
        print('Trace saved:', trace.path)
        print('Tools check passed.')

    except Exception as error:
        trace.finish('failed', str(error))
        raise