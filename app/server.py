from datetime import date
import math
import re
import sqlite3

from flask import Flask, abort, redirect, render_template, request, url_for

from app.seed import DB_PATH, get_db, reset_db

app = Flask(__name__)


def validate_bill(form, vendors):
    valid_vendor_ids = {str(vendor['id']) for vendor in vendors}

    if form['vendor_id'] not in valid_vendor_ids:
        raise ValueError('Please select a valid vendor.')

    if not form['invoice_number']:
        raise ValueError('Invoice number is required.')

    try:
        amount = float(form['amount'])
    except ValueError:
        raise ValueError('Amount must be a positive number.') from None

    if not math.isfinite(amount) or amount <= 0:
        raise ValueError('Amount must be a positive number.')

    try:
        due_date = date.fromisoformat(form['due_date'])
    except ValueError:
        raise ValueError(
            'Due date must be a valid date in YYYY-MM-DD format.'
        ) from None

    if due_date.isoformat() != form['due_date']:
        raise ValueError(
            'Due date must be a valid date in YYYY-MM-DD format.'
        )

    return (
        int(form['vendor_id']),
        form['invoice_number'],
        amount,
        due_date.isoformat(),
    )


@app.get('/')
def home():
    return redirect(url_for('bills'))


@app.get('/bills')
def bills():
    with get_db() as db:
        records = db.execute('''
            SELECT bills.*, vendors.name AS vendor_name
            FROM bills
            JOIN vendors ON vendors.id = bills.vendor_id
            ORDER BY bills.id DESC
        ''').fetchall()

    saved = request.args.get('saved')
    success = None

    if any(record['invoice_number'] == saved for record in records):
        success = 'Bill saved successfully.'

    return render_template(
        'bills.html', bills=records, success=success
    )


@app.route('/bills/new', methods=['GET', 'POST'])
def new_bill():
    field_names = ('vendor_id', 'invoice_number', 'amount', 'due_date')
    form = {
        name: request.form.get(name, '').strip()
        for name in field_names
    }
    error = None
    status = 200

    with get_db() as db:
        vendors = db.execute(
            'SELECT * FROM vendors ORDER BY id'
        ).fetchall()

    if request.method == 'POST':
        try:
            values = validate_bill(form, vendors)
        except ValueError as exc:
            error = str(exc)
            status = 400
        else:
            with get_db() as db:
                # Atomically consume the one-time failure flag.
                fail_once = db.execute(
                    'UPDATE settings SET value = ? '
                    'WHERE key = ? AND value = ?',
                    ('0', 'fail_next_bill', '1'),
                ).rowcount

                if fail_once:
                    error = 'Temporary server error. Please retry.'
                    status = 503
                else:
                    try:
                        db.execute(
                            'INSERT INTO bills '
                            '(vendor_id, invoice_number, amount, due_date) '
                            'VALUES (?, ?, ?, ?)',
                            values,
                        )
                    except sqlite3.IntegrityError as exc:
                        if 'bills.invoice_number' not in str(exc):
                            raise

                        error = (
                            'Invoice number already exists. '
                            'No new bill was created.'
                        )
                        status = 409

            if error is None:
                return redirect(url_for('bills', saved=values[1]))

    # Preserve entered values when validation or submission fails.
    return render_template(
        'bill_form.html',
        vendors=vendors,
        form=form,
        error=error,
    ), status


@app.get('/vendors')
def vendors():
    with get_db() as db:
        records = db.execute(
            'SELECT * FROM vendors ORDER BY id'
        ).fetchall()

    updated = request.args.get('updated', type=int)
    success = None

    if any(record['id'] == updated for record in records):
        success = 'Vendor details saved successfully.'

    return render_template(
        'vendors.html', vendors=records, success=success
    )


@app.route('/vendors/<int:vendor_id>/edit', methods=['GET', 'POST'])
def edit_vendor(vendor_id):
    with get_db() as db:
        vendor = db.execute(
            'SELECT * FROM vendors WHERE id = ?',
            (vendor_id,),
        ).fetchone()

    if vendor is None:
        abort(404)

    form = {
        'email': vendor['email'],
        'payment_terms': vendor['payment_terms'],
    }
    error = None
    status = 200

    if request.method == 'POST':
        form = {
            name: request.form.get(name, '').strip()
            for name in form
        }

        if not form['email']:
            error = 'Email is required.'
        elif not re.fullmatch(r'net [0-9]+', form['payment_terms']):
            error = (
                'Payment terms must use lowercase net N, '
                'for example net 45.'
            )

        if error:
            status = 400
        else:
            with get_db() as db:
                db.execute(
                    'UPDATE vendors SET email = ?, payment_terms = ? '
                    'WHERE id = ?',
                    (
                        form['email'],
                        form['payment_terms'],
                        vendor_id,
                    ),
                )

            return redirect(url_for('vendors', updated=vendor_id))

    return render_template(
        'vendor_form.html',
        vendor=vendor,
        form=form,
        error=error,
    ), status


@app.get('/admin/reset')
def admin_reset():
    flaky = request.args.get('flaky', '0')

    if flaky not in ('0', '1'):
        abort(400)

    reset_db(flaky=(flaky == '1'))
    return redirect(url_for('bills'))


if __name__ == '__main__':
    # Preserve existing records when restarting the server.
    if not DB_PATH.exists():
        reset_db()

    app.run(
        host='127.0.0.1',
        port=5000,
        debug=False,
        use_reloader=False,
    )