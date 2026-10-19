from pathlib import Path

import reportlab
from pypdf import PdfReader
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

OUTPUT_DIR = Path(__file__).resolve().parent / 'invoices'

# Embed fonts bundled with ReportLab for consistent PDF rendering.
FONT_DIR = Path(reportlab.__file__).resolve().parent / 'fonts'
pdfmetrics.registerFont(
    TTFont('InvoiceSans', str(FONT_DIR / 'Vera.ttf'))
)
pdfmetrics.registerFont(
    TTFont('InvoiceSans-Bold', str(FONT_DIR / 'VeraBd.ttf'))
)

INVOICES = [
    {
        'filename': 'acme_ACM-1041.pdf',
        'vendor': 'Acme Supplies',
        'invoice_number': 'ACM-1041',
        'invoice_date': '2026-08-12',
        'amount': 4250.00,
        'due_date': '2026-09-11',
    },
    {
        'filename': 'acme_ACM-1187.pdf',
        'vendor': 'Acme Supplies',
        'invoice_number': 'ACM-1187',
        'invoice_date': '20 September 2026',
        'amount': 5780.50,
        'due_date': '20 October 2026',
    },
    {
        'filename': 'globex_GLX-2305.pdf',
        'vendor': 'Globex Logistics',
        'invoice_number': 'GLX-2305',
        'invoice_date': '2026-10-02',
        'amount': 1920.00,
        'due_date': '2026-10-17',
    },
    {
        'filename': 'globex_GLX-2201.pdf',
        'vendor': 'Globex Logistics',
        'invoice_number': 'GLX-2201',
        'invoice_date': '2026-09-15',
        'amount': 1200.00,
        'due_date': '2026-09-30',
    },
    {
        'filename': 'initech_INI-77.pdf',
        'vendor': 'Initech Software',
        'invoice_number': 'INI-77',
        'invoice_date': '2026-10-05',
        'amount': 9000.00,
        'payment_terms': 'net 45',
    },
    {
        'filename': 'umbrella_UMB-310.pdf',
        'vendor': 'Umbrella Tools',
        'invoice_number': 'UMB-310',
        'invoice_date': '2026-10-09',
        'amount': 615.75,
    },
]


def write_invoice(invoice):
    path = OUTPUT_DIR / invoice['filename']
    width, height = A4

    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(f'Invoice {invoice["invoice_number"]}')
    pdf.setAuthor('CentrAlign prototype - synthetic data')

    # Header.
    pdf.setFillColor(HexColor('#172b4d'))
    pdf.rect(0, height - 120, width, 120, fill=1, stroke=0)

    pdf.setFillColor(HexColor('#ffffff'))
    pdf.setFont('InvoiceSans-Bold', 26)
    pdf.drawString(48, height - 52, 'INVOICE')

    pdf.setFont('InvoiceSans', 14)
    pdf.drawString(48, height - 83, invoice['invoice_number'])

    # Vendor and invoice details.
    pdf.setFillColor(HexColor('#172033'))
    pdf.setFont('InvoiceSans-Bold', 20)
    pdf.drawString(48, height - 164, invoice['vendor'])

    fields = [
        ('Invoice number', invoice['invoice_number']),
        ('Invoice date', invoice['invoice_date']),
        ('Bill to', 'Demo Company'),
    ]

    if invoice.get('due_date'):
        fields.append(('Due date', invoice['due_date']))

    if invoice.get('payment_terms'):
        fields.append(('Payment terms', invoice['payment_terms']))

    y = height - 218

    for label, value in fields:
        pdf.setFont('InvoiceSans-Bold', 11)
        pdf.drawString(48, y, f'{label}:')

        pdf.setFont('InvoiceSans', 12)
        pdf.drawString(190, y, value)

        y -= 34

    # Amount includes a thousands separator.
    amount_text = f'{invoice["amount"]:,.2f}'

    pdf.setFillColor(HexColor('#edf2f8'))
    pdf.roundRect(
        48, height - 492, width - 96, 72, 8,
        fill=1, stroke=0,
    )

    pdf.setFillColor(HexColor('#172033'))
    pdf.setFont('InvoiceSans-Bold', 12)
    pdf.drawString(68, height - 462, 'Amount due')

    pdf.setFont('InvoiceSans-Bold', 24)
    pdf.drawRightString(width - 68, height - 463, amount_text)

    pdf.setFillColor(HexColor('#536278'))
    pdf.setFont('InvoiceSans', 9)
    pdf.drawString(
        48, 48, 'SYNTHETIC INVOICE - LOCAL DEMO ONLY'
    )

    pdf.save()
    return path


def check_readable(path, invoice):
    reader = PdfReader(path)
    text = '\n'.join(
        page.extract_text() or ''
        for page in reader.pages
    )

    expected = [
        invoice['vendor'],
        invoice['invoice_number'],
        invoice['invoice_date'],
        f'{invoice["amount"]:,.2f}',
    ]

    for name in ('due_date', 'payment_terms'):
        if invoice.get(name):
            expected.append(invoice[name])

    missing = [
        value for value in expected
        if value not in text
    ]

    if missing:
        raise RuntimeError(
            f'Unreadable fields in {path.name}: {missing}'
        )


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for invoice in INVOICES:
        path = write_invoice(invoice)
        check_readable(path, invoice)
        print(f'Created and checked: {path.name}')

    print(
        f'Ready: {len(INVOICES)} sample invoices in {OUTPUT_DIR}'
    )


if __name__ == '__main__':
    main()