import argparse

from agent.loop import run_agent


def main():
    parser = argparse.ArgumentParser(
        description='Run the local AI task worker.'
    )

    parser.add_argument(
        'task',
        help='Natural-language task, inside quotes.',
    )
    parser.add_argument(
        '--headless',
        action='store_true',
        default=None,
    )
    parser.add_argument(
        '--max-steps',
        type=int,
        choices=range(1, 26),
        default=25,
    )

    args = parser.parse_args()

    result = run_agent(
        args.task,
        max_steps=args.max_steps,
        headless=args.headless,
    )

    print('\nSTATUS:', result['status'].upper())
    print(result['message'])
    print('Steps:', result['steps'])
    print('Trace:', result['trace_path'])

    codes = {
        'completed': 0,
        'not_completed': 2,
        'failed': 1,
        'cancelled': 130,
    }

    return codes[result['status']]


if __name__ == '__main__':
    raise SystemExit(main())