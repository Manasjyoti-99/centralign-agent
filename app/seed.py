from contextlib import contextmanager
from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parent / 'bills.db'

VENDORS = [
    (1, 'Acme Supplies', 'billing@acme.example', 'net 30'),
    (2, 'Globex Logistics', 'billing@globex.example', 'net 15'),
    (3, 'Initech Software', 'billing@initech.example', 'net 45'),
    (4, 'Umbrella Tools', 'billing@umbrella.example', 'net 30'),
]


@contextmanager
def get_db():
    """Open a database connection and close it after use."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')

    try:
        with db:
            yield db
    finally:
        db.close()


def reset_db(flaky=False):
    """Reset the sandbox database to its known starting state."""
    with get_db() as db:
        db.executescript('''
            DROP TABLE IF EXISTS bills;
            DROP TABLE IF EXISTS vendors;
            DROP TABLE IF EXISTS settings;

            CREATE TABLE vendors (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                payment_terms TEXT NOT NULL
            );

            CREATE TABLE bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id INTEGER NOT NULL REFERENCES vendors(id),
                invoice_number TEXT NOT NULL UNIQUE,
                amount REAL NOT NULL CHECK (amount > 0),
                due_date TEXT NOT NULL
            );

            CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        ''')

        db.executemany(
            'INSERT INTO vendors (id, name, email, payment_terms) '
            'VALUES (?, ?, ?, ?)',
            VENDORS,
        )

        # Existing invoice: used later to test duplicate handling.
        db.execute(
            'INSERT INTO bills '
            '(vendor_id, invoice_number, amount, due_date) '
            'VALUES (?, ?, ?, ?)',
            (2, 'GLX-2201', 1200.0, '2026-09-30'),
        )

        # Used later to deliberately fail the first bill submission.
        db.execute(
            'INSERT INTO settings (key, value) VALUES (?, ?)',
            ('fail_next_bill', '1' if flaky else '0'),
        )


if __name__ == '__main__':
    reset_db()

    with get_db() as db:
        vendor_count = db.execute(
            'SELECT COUNT(*) FROM vendors'
        ).fetchone()[0]

        bill_count = db.execute(
            'SELECT COUNT(*) FROM bills'
        ).fetchone()[0]

        invoice = db.execute(
            'SELECT invoice_number FROM bills'
        ).fetchone()[0]

    print(f'Database ready: {DB_PATH}')
    print(f'Vendors: {vendor_count}')
    print(f'Bills: {bill_count}')
    print(f'Existing invoice: {invoice}')