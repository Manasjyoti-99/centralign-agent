"""Exercise real controls with browser stubs; no server, API key or LLM calls."""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agent.guard import Guard
from agent.state import AgentState
from agent.tools import Tools, check_bill_values, read_pdf_document
from agent.verifier import Verifier


GOAL = (
    'Find the latest invoice from Globex Logistics, enter it into the '
    'Vendor Bills system, and tell me when it is done.'
)
SELECTOR = {'selector': '#submit-bill'}
DOCUMENT = read_pdf_document('invoices/globex_GLX-2305.pdf')


class AuditTrace:
    def __init__(self):
        self.data = {'events': []}

    def log(self, kind, **details):
        self.data['events'].append({
            'type': kind, 'details': deepcopy(details),
        })


class SavedPage:
    def __init__(self, browser):
        self.browser = browser
        self.url = ''
        self.closed = False

    def goto(self, url, **kwargs):
        self.url = url
        return SimpleNamespace(status=200)

    def locator(self, selector):
        if selector == 'body':
            return SimpleNamespace(inner_text=lambda: str(self.browser.rows))
        if selector != '#bills-table':
            raise AssertionError(selector)
        return SimpleNamespace(
            count=lambda: 1,
            evaluate=lambda code: {
                'headers': ['Vendor', 'Invoice number', 'Amount', 'Due date'],
                'rows': deepcopy(self.browser.rows),
            },
        )

    def close(self):
        self.closed = True


class BrowserStub:
    """Only the browser surface used by the guard and saved-record check."""
    def __init__(self):
        self.page = SimpleNamespace(url='http://localhost:5000/bills/new')
        self.vendor = 'Globex Logistics'
        self.values = {
            'invoice_number': 'GLX-2305',
            'amount': '1920.00',
            'due_date': '2026-10-17',
        }
        self.element = {
            'id': 'submit-bill', 'text': 'Submit bill', 'tag': 'button',
            'type': 'submit', 'href': '',
            'form_action': 'http://localhost:5000/bills/new',
            'form_method': 'post',
        }
        self.rows = [
            ['Globex Logistics', 'GLX-2201', '1200.00', '2026-09-30'],
        ]
        self.clicks = 0
        self.fresh_pages = []
        self.context = SimpleNamespace(new_page=self.new_page)

    def new_page(self):
        page = SavedPage(self)
        self.fresh_pages.append(page)
        return page

    def safe_url(self, url):
        return 'http://localhost:5000' + url if url.startswith('/') else url

    def describe(self, selector):
        return deepcopy(self.element)

    def form_values(self):
        return [{
            'id': 'vendor_id', 'selector': '#vendor_id',
            'value': '2', 'selected': [self.vendor],
        }] + [{
            'id': key, 'selector': '#' + key, 'value': value, 'selected': [],
        } for key, value in self.values.items()]

    def click(self, selector):
        self.clicks += 1
        self.rows.append([
            self.vendor, self.values['invoice_number'],
            self.values['amount'], self.values['due_date'],
        ])
        self.page.url = 'http://localhost:5000/bills'
        return json.dumps({'url': self.page.url, 'error': ''})


class SafetyRegressionTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        redirect = redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)
        self.reset_worker()

    def reset_worker(self):
        self.browser = BrowserStub()
        self.state = AgentState(GOAL)
        self.state.documents[DOCUMENT['path']] = DOCUMENT['text']
        self.trace = AuditTrace()
        self.approve = Mock(return_value='y')
        self.guard = Guard(self.browser, self.state, self.trace, self.approve)
        self.tools = Tools(self.browser, self.state, self.guard, self.trace)
        self.verifier = Verifier(self.browser, self.state, None, self.trace)

    def submit(self):
        return self.tools.execute('click', SELECTOR)

    def events(self, kind):
        return [event['details'] for event in self.trace.data['events']
                if event['type'] == kind]

    def test_unchanged_approval_submits_and_checks_fresh_saved_values(self):
        self.assertFalse(self.submit().startswith('ERROR'))
        self.assertEqual(self.browser.clicks, 1)
        self.assertEqual(self.approve.call_count, 1)
        self.assertEqual(len(self.state.approvals), 1)
        self.assertEqual(
            [event['phase'] for event in self.events('bill_preflight')],
            ['before_approval', 'before_click'],
        )
        self.assertIsNone(self.verifier._check_saved_bills([DOCUMENT], []))
        self.assertTrue(self.browser.fresh_pages[-1].closed)

    def test_rejected_typo_does_not_poison_corrected_record_check(self):
        self.browser.values['invoice_number'] = 'GLX-2305-TYPO'
        self.assertTrue(self.submit().startswith('ERROR'))
        self.assertEqual(self.browser.clicks, 0)
        self.approve.assert_not_called()
        self.browser.values['invoice_number'] = 'GLX-2305'
        self.assertFalse(self.submit().startswith('ERROR'))
        self.assertEqual(self.browser.clicks, 1)
        self.assertEqual(
            self.events('bill_submission_request')[0]['observed']['invoice_number'],
            'GLX-2305-TYPO',
        )
        self.assertIsNone(self.verifier._check_saved_bills([DOCUMENT], []))

    def test_wrong_amount_is_blocked_before_approval(self):
        self.browser.values['amount'] = '9999.00'
        self.assertIn("expected '1920.00'", self.submit())
        self.approve.assert_not_called()
        self.assertEqual(self.browser.clicks, 0)

    def test_changed_fields_invalidate_approval_and_need_a_new_prompt(self):
        for field, changed in (
            ('amount', '9999.00'), ('due_date', '2026-11-08'),
            ('invoice_number', 'GLX-2201'),
        ):
            with self.subTest(field=field):
                self.reset_worker()
                original = self.browser.values[field]
                self.approve.side_effect = lambda prompt: (
                    self.browser.values.update({field: changed}) or 'y'
                )
                self.assertIn('Approval invalidated', self.submit())
                self.assertEqual(self.browser.clicks, 0)
                self.assertEqual(self.state.approvals, [])
                self.assertEqual(len(self.events('approval_invalidated')), 1)
                self.browser.values[field] = original
                self.approve.side_effect = None
                self.assertFalse(self.submit().startswith('ERROR'))
                self.assertEqual(self.approve.call_count, 2)
                self.assertEqual(self.browser.clicks, 1)

    def test_changed_vendor_invalidates_approval(self):
        self.approve.side_effect = lambda prompt: (
            setattr(self.browser, 'vendor', 'Acme Supplies') or 'y'
        )
        self.assertIn('Approval invalidated', self.submit())
        self.assertEqual(self.browser.clicks, 0)

    def test_changed_page_invalidates_approval(self):
        self.approve.side_effect = lambda prompt: (
            setattr(self.browser.page, 'url', 'http://localhost:5000/vendors') or 'y'
        )
        self.assertIn('Approval invalidated', self.submit())
        self.assertEqual(self.browser.clicks, 0)
        self.assertEqual(
            self.events('approval_invalidated')[0]['approved_snapshot']['url'],
            'http://localhost:5000/bills/new',
        )

    def test_changed_target_action_invalidates_approval(self):
        self.approve.side_effect = lambda prompt: (
            self.browser.element.update({
                'form_action': 'http://localhost:5000/vendors/1/edit',
            }) or 'y'
        )
        self.assertIn('Approval invalidated', self.submit())
        self.assertEqual(self.browser.clicks, 0)

    def test_uninspectable_target_after_approval_blocks_click(self):
        def remove_target(prompt):
            self.browser.describe = Mock(side_effect=ValueError('Target removed'))
            return 'y'
        self.approve.side_effect = remove_target
        self.assertIn('could not be re-inspected', self.submit())
        self.assertEqual(self.browser.clicks, 0)

    def test_sources_are_reread_after_approval(self):
        changed = deepcopy(DOCUMENT)
        changed['text'] = changed['text'].replace('1,920.00', '9,999.00')
        with patch('agent.tools.read_pdf_document', side_effect=[DOCUMENT, changed]):
            result = self.submit()
        self.assertIn('Pre-click validation failed', result)
        self.assertEqual(self.browser.clicks, 0)
        self.assertEqual(self.state.approvals, [])

    def test_change_during_preclick_validation_is_also_blocked(self):
        count = 0
        def validate_then_change(*args):
            nonlocal count
            result = check_bill_values(*args)
            count += 1
            if count == 2:
                self.browser.values['amount'] = '9999.00'
            return result
        with patch('agent.tools.check_bill_values', side_effect=validate_then_change):
            self.assertIn('Approval invalidated', self.submit())
        self.assertEqual(count, 2)
        self.assertEqual(self.browser.clicks, 0)

    def test_denial_stops_click_and_fresh_records_verify_blocked_outcome(self):
        self.approve.return_value = 'n'
        self.assertTrue(self.submit().startswith('ERROR: Approval denied.'))
        self.assertEqual(self.browser.clicks, 0)
        self.assertIs(self.state.approvals[-1]['approved'], False)
        self.assertIn('previous approval was denied', self.submit())
        self.assertEqual(self.approve.call_count, 1)

    def test_denied_bill_verification_checks_audit_and_absent_record(self):
        # An invalidated yes is not an executable approval or a human denial.
        self.approve.side_effect = lambda prompt: (
            self.browser.values.update({'amount': '9999.00'}) or 'y'
        )
        self.assertIn('Approval invalidated', self.submit())
        self.browser.values['amount'] = '1920.00'
        self.approve.side_effect = None
        self.approve.return_value = 'n'
        self.submit()
        result = self.verifier._verify_denied_bill([])
        self.assertIn('Verification PASS (not_completed)', result)
        self.assertEqual(self.state.status, 'not_completed')
        self.assertTrue(self.browser.fresh_pages[-1].closed)

    def test_blank_approval_is_denial(self):
        self.approve.return_value = ''
        self.assertTrue(self.submit().startswith('ERROR: Approval denied.'))
        self.assertEqual(self.browser.clicks, 0)

    def test_eof_approval_is_denial(self):
        self.approve.side_effect = EOFError
        self.assertTrue(self.submit().startswith('ERROR: Approval denied.'))
        self.assertEqual(self.browser.clicks, 0)

    def test_saved_wrong_value_still_fails_independent_check(self):
        self.submit()
        self.browser.rows[-1][2] = '9999.00'
        result = self.verifier._check_saved_bills([DOCUMENT], [])
        self.assertIn("amount is '9999.00'; expected '1920.00'", result)

    def test_approval_without_saved_record_cannot_prove_completion(self):
        self.submit()
        self.browser.rows.pop()
        self.assertIn(
            'Expected one saved record for invoice GLX-2305',
            self.verifier._check_saved_bills([DOCUMENT], []),
        )

    def test_missing_due_date_requires_human_answer_before_submission(self):
        document = read_pdf_document('invoices/umbrella_UMB-310.pdf')
        self.state.documents = {document['path']: document['text']}
        self.state.goal = 'Enter the latest invoice from Umbrella Tools.'
        self.browser.vendor = 'Umbrella Tools'
        self.browser.values.update({
            'invoice_number': 'UMB-310', 'amount': '615.75',
            'due_date': '2026-10-09',
        })
        self.assertIn('no printed due date', self.submit())
        self.approve.assert_not_called()
        self.assertEqual(self.browser.clicks, 0)
        self.tools.ask_human = lambda question: '2026-11-08'
        self.tools.execute('ask_human', {
            'question': 'What is the due date for invoice UMB-310?',
        })
        self.browser.values['due_date'] = '2026-11-08'
        self.assertFalse(self.submit().startswith('ERROR'))
        self.assertIsNone(self.verifier._check_saved_bills([document], []))

    def test_vendor_save_uses_the_same_approval_binding(self):
        self.browser.page.url = 'http://localhost:5000/vendors/1/edit'
        self.browser.element.update({
            'id': 'save-vendor', 'text': 'Save vendor',
            'form_action': self.browser.page.url,
        })
        fields = [{'id': 'payment_terms', 'selector': '#payment_terms',
                   'value': 'net 45', 'selected': []}]
        self.browser.form_values = lambda: deepcopy(fields)
        self.approve.side_effect = lambda prompt: (
            fields[0].update({'value': 'net 90'}) or 'y'
        )
        result = self.guard.check('click', {'selector': '#save-vendor'})
        self.assertIn('Approval invalidated', result)
        self.assertEqual(self.state.approvals, [])


if __name__ == '__main__':
    unittest.main()
