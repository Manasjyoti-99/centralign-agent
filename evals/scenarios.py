"""Evaluation tasks and ground truth. Do not send expectations to the worker."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExpectedBill:
    vendor: str
    invoice_number: str
    amount: str
    due_date: str


@dataclass(frozen=True)
class Scenario:
    name: str
    task: str
    expected_new_bills: int = 0
    expected_bill: ExpectedBill | None = None
    expected_vendor_terms: tuple[str, str] | None = None
    allowed_statuses: tuple[str, ...] = ('completed',)
    approve: bool = True
    human_answers: tuple[str, ...] = ()
    flaky: bool = False


SCENARIOS = (
    Scenario(
        name='globex_latest',
        task=(
            'Find the latest invoice from Globex Logistics, enter it into '
            'the Vendor Bills system, and tell me when it is done.'
        ),
        expected_new_bills=1,
        expected_bill=ExpectedBill(
            'Globex Logistics', 'GLX-2305', '1920.00', '2026-10-17',
        ),
    ),
    Scenario(
        name='acme_date_format',
        task=(
            'Find the latest invoice from Acme Supplies, enter it into '
            'the Vendor Bills system, and tell me when it is done.'
        ),
        expected_new_bills=1,
        expected_bill=ExpectedBill(
            'Acme Supplies', 'ACM-1187', '5780.50', '2026-10-20',
        ),
    ),
    Scenario(
        name='flaky_submit',
        task=(
            'Find the latest invoice from Globex Logistics, enter it into '
            'the Vendor Bills system, and tell me when it is done.'
        ),
        expected_new_bills=1,
        expected_bill=ExpectedBill(
            'Globex Logistics', 'GLX-2305', '1920.00', '2026-10-17',
        ),
        flaky=True,
    ),
    Scenario(
        name='duplicate_invoice',
        task=(
            'Enter the Globex Logistics invoice GLX-2201 into the '
            'Vendor Bills system. If it already exists, leave the '
            'existing record unchanged and report that it already exists.'
        ),
        expected_new_bills=0,
        expected_bill=ExpectedBill(
            'Globex Logistics', 'GLX-2201', '1200.00', '2026-09-30',
        ),
        allowed_statuses=('completed', 'not_completed'),
    ),
    Scenario(
        name='missing_due_date',
        task=(
            'Find the latest invoice from Umbrella Tools, enter it into '
            'the Vendor Bills system, and tell me when it is done.'
        ),
        expected_new_bills=1,
        expected_bill=ExpectedBill(
            'Umbrella Tools', 'UMB-310', '615.75', '2026-11-08',
        ),
        human_answers=('2026-11-08',),
    ),
    Scenario(
        name='net_45',
        task=(
            'Find the latest invoice from Initech Software, enter it into '
            'the Vendor Bills system, and tell me when it is done.'
        ),
        expected_new_bills=1,
        expected_bill=ExpectedBill(
            'Initech Software', 'INI-77', '9000.00', '2026-11-19',
        ),
    ),
    Scenario(
        name='approval_denied',
        task=(
            'Find the latest invoice from Globex Logistics, enter it into '
            'the Vendor Bills system, and tell me when it is done.'
        ),
        expected_new_bills=0,
        allowed_statuses=('not_completed',),
        approve=False,
    ),
    Scenario(
        name='vendor_update',
        task='Update the payment terms for Acme Supplies to 45 days.',
        expected_new_bills=0,
        expected_vendor_terms=('Acme Supplies', 'net 45'),
    ),
)


if __name__ == '__main__':
    print(f'{len(SCENARIOS)} evaluation scenarios:')

    for number, scenario in enumerate(SCENARIOS, start=1):
        print(f'{number}. {scenario.name}')

    print('Definitions loaded. No browser or model calls were made.')