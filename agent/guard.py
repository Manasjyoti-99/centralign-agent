from copy import deepcopy
import json


WRITE_WORDS = (
    'submit', 'save', 'delete', 'pay', 'send', 'confirm'
)


class Guard:
    def __init__(self, browser, state, trace, approve=None):
        self.browser = browser
        self.state = state
        self.trace = trace
        self.approve = approve if approve is not None else input
        self.failures = {}

    @staticmethod
    def action_key(tool_name, arguments):
        return json.dumps(
            [tool_name, arguments],
            sort_keys=True,
        )

    def _click_snapshot(self, selector):
        """Capture the page, action and values that an approval authorizes."""
        info = self.browser.describe(selector)
        if info['tag'] not in ('a', 'button', 'input'):
            raise ValueError('Click a link or button using its selector.')
        for key in ('href', 'form_action'):
            if info[key]:
                self.browser.safe_url(info[key])
        return deepcopy({
            'url': self.browser.page.url,
            'selector': selector,
            'element': info,
            'fields': self.browser.form_values(),
        })

    def _check_unchanged(self, snapshot):
        try:
            current = self._click_snapshot(snapshot['selector'])
            reason = 'The page, action or form values changed during approval.'
            if current == snapshot:
                return None
        except Exception as error:
            current = None
            reason = f'The approved action could not be re-inspected: {error}'

        self.trace.log(
            'approval_invalidated', approved_snapshot=snapshot,
            observed_snapshot=current, reason=reason,
        )
        return (
            f'ERROR: Approval invalidated. {reason} No click was executed. '
            'Review the current page and request fresh approval.'
        )

    def check(self, tool_name, arguments, before_click=None):
        key = self.action_key(tool_name, arguments)

        if self.failures.get(key, 0) >= 3:
            return (
                'ERROR: This action is blocked after three failures.'
            )

        if tool_name != 'click':
            return None

        try:
            snapshot = self._click_snapshot(arguments['selector'])
            info = snapshot['element']

            label = f"{info['id']} {info['text']}".lower()

            needs_approval = (
                info['tag'] != 'a'
                or any(word in label for word in WRITE_WORDS)
            )

            if not needs_approval:
                return None

            if any(
                not item['approved']
                for item in self.state.approvals
            ):
                return (
                    'ERROR: A previous approval was denied. '
                    'Writes remain blocked for this run.'
                )

            fields = snapshot['fields']

        except Exception as error:
            # Inspection failure must block the click.
            return (
                'ERROR: Cannot inspect this click; '
                f'action blocked: {error}'
            )

        shown = {
            field['id'] or field['selector']: (
                field['selected'] or field['value']
            )
            for field in fields
        }

        print('\nAPPROVAL REQUIRED')
        print('Page:', snapshot['url'])
        print('Action:', arguments['selector'], info['text'])
        print('Current form values:')
        print(json.dumps(shown, ensure_ascii=False, indent=2))

        try:
            answer = self.approve(
                'Approve this action? [y/N]: '
            )
            approved = answer.strip().lower() in ('y', 'yes')
        except EOFError:
            approved = False

        decision = {**snapshot, 'approved': approved}

        if approved:
            blocked = self._check_unchanged(snapshot)
            if blocked is not None:
                return blocked

            # The dispatcher owns source validation. Repeat it after the human
            # pause, then check that validation did not outlive this snapshot.
            if before_click is not None:
                try:
                    before_click()
                except Exception as error:
                    self.trace.log(
                        'approval_invalidated', approved_snapshot=snapshot,
                        reason=f'Pre-click validation failed: {error}',
                    )
                    return (
                        f'ERROR: Pre-click validation failed: {error}. '
                        'No click was executed. Correct the values or sources '
                        'and request fresh approval.'
                    )
                blocked = self._check_unchanged(snapshot)
                if blocked is not None:
                    return blocked

        self.state.approvals.append(decision)
        self.trace.log('approval', **decision)

        if not approved:
            return (
                'ERROR: Approval denied. '
                'Writes are blocked for the rest of this run.'
            )

        return None

    def record_result(self, tool_name, arguments, result):
        if isinstance(result, str) and result.startswith('ERROR'):
            key = self.action_key(tool_name, arguments)
            self.failures[key] = self.failures.get(key, 0) + 1

            self.trace.log(
                'guard_failure',
                tool=tool_name,
                arguments=arguments,
                failures=self.failures[key],
            )


if __name__ == '__main__':
    from agent.browser import Browser
    from agent.state import AgentState
    from agent.trace import Trace

    state = AgentState(
        'Check approval denial and repeated-failure blocking.'
    )
    trace = Trace(state.goal)
    browser = Browser()

    try:
        browser.open_url('/bills/new')
        browser.fill('#vendor_id', 'Globex Logistics')
        browser.fill('#invoice_number', 'GUARD-CHECK')
        browser.fill('#amount', '1.00')
        browser.fill('#due_date', '2026-10-17')

        guard = Guard(browser, state, trace)
        arguments = {'selector': '#submit-bill'}

        print('For this check, type n at the approval prompt.')
        result = guard.check('click', arguments)

        if result is None:
            raise RuntimeError(
                'For this check, choose n and rerun the command.'
            )

        if (
            not state.approvals
            or state.approvals[-1]['approved']
        ):
            raise RuntimeError(result)

        print('Approval denial check passed.')

        result = guard.check('click', arguments)

        if result is None or len(state.approvals) != 1:
            raise RuntimeError(
                'Denied approval was not retained.'
            )

        print('Repeated approval request blocked.')

        for _ in range(3):
            guard.record_result(
                'get_page',
                {},
                'ERROR: simulated test failure',
            )

        if guard.check('get_page', {}) is None:
            raise RuntimeError(
                'Three-failure blocking check failed.'
            )

        print('Three-failure check passed.')

        trace.screenshot(browser)
        trace.finish('completed', 'Guard smoke check passed.')
        print('Trace saved:', trace.path)
        print('Guard check passed.')

    except Exception as error:
        trace.finish('failed', str(error))
        raise

    finally:
        browser.close()
