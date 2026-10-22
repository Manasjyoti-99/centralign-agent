from datetime import date as calendar_date, timedelta
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

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


DATE_TOKEN = r'(?:\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]+\s+\d{4})'


def source_value(text, label):
    """Read a labelled value in the supplied synthetic invoice layout."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        key, separator, value = line.partition(':')
        if key.strip().casefold() == label.casefold():
            if separator and value.strip():
                return value.strip()
            if index + 1 < len(lines):
                return lines[index + 1]
    return None


def normalise_date(value):
    value = value.strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return calendar_date.fromisoformat(value).isoformat()
    match = re.fullmatch(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', value)
    months = (
        'january', 'february', 'march', 'april', 'may', 'june',
        'july', 'august', 'september', 'october', 'november', 'december',
    )
    if match and match[2].casefold() in months:
        return calendar_date(
            int(match[3]), months.index(match[2].casefold()) + 1,
            int(match[1]),
        ).isoformat()
    raise ValueError('Use an unambiguous date: YYYY-MM-DD or day Month year.')


def money_value(value):
    try:
        amount = Decimal(str(value).strip().replace(',', ''))
        if not amount.is_finite() or amount <= 0:
            raise ValueError('Amount must be positive and finite.')
        rounded = amount.quantize(Decimal('0.01'))
        if amount != rounded:
            raise ValueError('This invoice check supports at most two decimal places.')
        return format(rounded, 'f')
    except InvalidOperation as error:
        raise ValueError('Amount is not a readable decimal number.') from error


def expected_bill_values(number, documents, human_answers, goal):
    """Derive expectations from originals and actual answers, never a claim.

    This parser is deliberately limited to our supplied invoice layout.
    The model still finds documents, chooses actions and handles feedback.
    """
    sources = [document for document in documents
               if source_value(document['text'], 'Invoice number') == number]
    if len(sources) != 1:
        raise ValueError(
            f'Read one unambiguous original PDF for invoice {number} '
            'before submitting or verifying it.'
        )
    text = sources[0]['text']
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    index = next(i for i, line in enumerate(lines)
                 if line.partition(':')[0].strip().casefold() == 'invoice number')
    if index < 1:
        raise ValueError(f'Cannot read the supplier for invoice {number}.')
    vendor = lines[index - 1]
    amount = source_value(text, 'Amount due')
    if amount is None:
        raise ValueError(f'Cannot read the amount for invoice {number}.')

    # Explicit task values take priority over document defaults.
    task_amounts = re.findall(
        r'\bamount\s*(?:(?:is|of)\s+|[:=]\s*)?'
        r'([0-9][0-9,]*(?:\.[0-9]+)?)', goal, re.IGNORECASE,
    )
    if task_amounts:
        amounts = {money_value(value) for value in task_amounts}
        if len(amounts) != 1:
            raise ValueError('The task contains ambiguous amounts; ask the human.')
        amount = amounts.pop()

    task_dates = re.findall(
        r'\bdue(?:[\s_-]+date|\s+on)?\s*'
        r'(?:(?:is|of)\s+|[:=]\s*)?(' + DATE_TOKEN + r')\b',
        goal, re.IGNORECASE,
    )
    due = None
    basis = ''
    if task_dates:
        dates = {normalise_date(value) for value in task_dates}
        if len(dates) != 1:
            raise ValueError('The task contains ambiguous due dates; ask the human.')
        due, basis = dates.pop(), 'user task'

    known_numbers = {source_value(doc['text'], 'Invoice number')
                     for doc in documents}
    for answer in reversed(human_answers):
        if due is not None:
            break
        question = answer.get('question', '')
        if not re.search(r'\bdue\b', question, re.IGNORECASE):
            continue
        named = {item for item in known_numbers if item and re.search(
            r'(?<!\w)' + re.escape(item) + r'(?!\w)', question,
            re.IGNORECASE,
        )}
        if named and number not in named:
            continue
        reply = answer.get('answer', '').strip().rstrip('.')
        supplied = re.fullmatch(
            r'(?:(?:use|due|due date)\s*(?:(?:is)\s+|[:=]\s*)?)?('
            + DATE_TOKEN + r')', reply, re.IGNORECASE,
        )
        if supplied is None:
            raise ValueError(
                f'Ask the human for one clear due date for invoice {number}. '
                'Request a reply containing just YYYY-MM-DD.'
            )
        due, basis = normalise_date(supplied[1]), 'recorded human answer'

    if due is None:
        printed = source_value(text, 'Due date')
        terms = source_value(text, 'Payment terms') or ''
        net = re.fullmatch(r'net\s+(\d+)', terms, re.IGNORECASE)
        if printed:
            due, basis = normalise_date(printed), 'printed due date'
        elif net:
            issued = source_value(text, 'Invoice date')
            if not issued:
                raise ValueError(f'Cannot read the starting date for invoice {number}.')
            due = (calendar_date.fromisoformat(normalise_date(issued))
                   + timedelta(days=int(net[1]))).isoformat()
            basis = terms
        else:
            raise ValueError(
                f'Invoice {number} has no printed due date or net-N terms. '
                'Call ask_human for its due date before submitting. '
                'The invoice date is not evidence for the due date.'
            )

    return {
        'vendor': vendor, 'invoice_number': number,
        'amount': money_value(amount), 'due_date': due,
        'due_date_basis': basis,
    }


def bill_values_from_fields(fields):
    fields = {field.get('id'): field for field in fields}
    vendor = fields.get('vendor_id', {})
    selected = vendor.get('selected') or []
    return {
        'vendor': selected[0] if len(selected) == 1 else vendor.get('value', ''),
        **{name: fields.get(name, {}).get('value', '').strip()
           for name in ('invoice_number', 'amount', 'due_date')},
    }


def check_bill_values(values, documents, human_answers, goal):
    number = values.get('invoice_number', '').strip()
    if not number:
        raise ValueError('Fill the invoice number and read its original PDF first.')
    expected = expected_bill_values(number, documents, human_answers, goal)
    for key in ('vendor', 'invoice_number', 'amount', 'due_date'):
        actual = values.get(key, '').strip()
        if key == 'amount':
            actual = money_value(actual)
        if actual != expected[key]:
            basis = f" ({expected['due_date_basis']})" if key == 'due_date' else ''
            raise ValueError(
                f'Invoice {number}: {key} is {actual!r}; '
                f'expected {expected[key]!r}{basis}. '
                'Correct the form or saved record before claiming completion.'
            )
    return expected


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

            self._check_bill_submission(name, arguments)

            blocked = self.guard.check(
                name, arguments,
                before_click=lambda: self._check_bill_submission(
                    name, arguments, phase='before_click',
                ),
            )

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

    def _check_bill_submission(self, name, arguments, phase='before_approval'):
        if name != 'click' or self.browser is None:
            return
        if urlsplit(self.browser.page.url).path != '/bills/new':
            return
        # Inspect the actual element, so alternate selectors cannot skip this.
        info = self.browser.describe(arguments['selector'])
        if info.get('id') != 'submit-bill':
            return
        values = bill_values_from_fields(self.browser.form_values())
        if phase == 'before_approval':
            self.trace.log('bill_submission_request', observed=values)
        originals = [read_pdf_document(path) for path in self.state.documents]
        expected = check_bill_values(
            values, originals, self.state.human_answers, self.state.goal,
        )
        self.trace.log(
            'bill_preflight', phase=phase, expected=expected, observed=values,
        )

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
