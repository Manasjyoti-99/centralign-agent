import json
import os
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / '.env')

SNAPSHOT_JS = r'''() => {
    const visible = el => el.getClientRects().length > 0;
    const selector = el => el.id ? '#' + CSS.escape(el.id) : null;
    const text = document.body.innerText;
    return {
        text: text.slice(0, 4500) + (text.length > 4500 ? '\n[truncated]' : ''),
        fields: [...document.querySelectorAll('input, select, textarea')]
            .filter(visible).slice(0, 25).map(el => ({
                id: el.id,
                selector: selector(el),
                type: el.type,
                value: el.type === 'password' ? '[hidden]' : el.value,
                selected: el.tagName === 'SELECT'
                    ? [...el.selectedOptions].map(o => o.label) : [],
                options: el.tagName === 'SELECT'
                    ? [...el.options].map(o => o.label).slice(0, 20) : []
            })),
        buttons: [...document.querySelectorAll('button, input[type="submit"]')]
            .filter(visible).slice(0, 20).map(el => ({
                selector: selector(el), text: el.innerText || el.value
            })),
        links: [...document.querySelectorAll('a[href]')]
            .filter(visible).slice(0, 30).map(el => ({
                selector: selector(el), text: el.innerText, url: el.href
            })),
        error: [...document.querySelectorAll('#error')]
            .filter(visible).map(el => el.innerText).join('\n')
    };
}'''


class Browser:
    def __init__(self, app_url=None, headless=None):
        self.app_url = (
            app_url or os.getenv('APP_URL', 'http://localhost:5000')
        ).rstrip('/')

        if headless is None:
            headless = os.getenv('HEADLESS', '0') == '1'

        self.visited_urls = []
        self._playwright = sync_playwright().start()

        try:
            self.browser = self._playwright.chromium.launch(
                headless=headless
            )
            self.context = self.browser.new_context(
                service_workers='block'
            )
            self.context.set_default_timeout(8000)
            self.context.set_default_navigation_timeout(15000)
            self.context.route('**/*', self._route)
            self.page = self.context.new_page()
        except Exception:
            self._playwright.stop()
            raise

    def safe_url(self, url):
        absolute = urljoin(self.app_url + '/', url)
        target = urlsplit(absolute)
        allowed = urlsplit(self.app_url)

        def origin(parts):
            port = parts.port or (
                443 if parts.scheme == 'https' else 80
            )
            return parts.scheme, parts.hostname, port

        if (
            target.scheme not in ('http', 'https')
            or origin(target) != origin(allowed)
        ):
            raise ValueError(
                'Only the configured APP_URL origin is allowed.'
            )

        if target.username or target.password:
            raise ValueError('URLs containing credentials are blocked.')

        if unquote(target.path).lower().startswith('/admin'):
            raise ValueError(
                'Admin/reset pages are blocked for the agent.'
            )

        return absolute

    def _route(self, route):
        try:
            self.safe_url(route.request.url)
        except ValueError:
            route.abort('blockedbyclient')
        else:
            route.continue_()

    def _capture(self, page):
        page.wait_for_load_state('domcontentloaded')
        self.safe_url(page.url)
        data = {'url': page.url, **page.evaluate(SNAPSHOT_JS)}

        if page is self.page and page.url not in self.visited_urls:
            self.visited_urls.append(page.url)

        return data

    def get_page(self):
        return json.dumps(
            self._capture(self.page), ensure_ascii=False
        )

    def _action_result(self, status=200):
        data = self._capture(self.page)
        snapshot = json.dumps(data, ensure_ascii=False)

        if data['error'] or status >= 400:
            reason = data['error'] or f'HTTP {status}'
            return f'ERROR: {reason}\n{snapshot}'

        return snapshot

    def open_url(self, url):
        response = self.page.goto(
            self.safe_url(url),
            wait_until='domcontentloaded',
        )
        return self._action_result(
            response.status if response else 200
        )

    def _element(self, selector):
        element = self.page.locator(selector)

        if element.count() != 1:
            raise ValueError(
                f'Selector must match exactly one element: {selector}'
            )

        return element

    def fill(self, selector, value):
        element = self._element(selector)

        if element.evaluate('el => el.tagName') == 'SELECT':
            element.select_option(label=str(value))
        else:
            element.fill(str(value))

        return self.get_page()

    def click(self, selector):
        # The tool dispatcher must run the approval guard first.
        self._element(selector).click()
        return self._action_result()

    def describe(self, selector):
        return self._element(selector).evaluate(r'''el => {
            el = el.closest(
                'button, a, input[type="submit"], input[type="button"]'
            ) || el;
            return {
                id: el.id,
                text: el.innerText || el.value || '',
                tag: el.tagName.toLowerCase(),
                type: el.type || '',
                href: el.href || '',
                form_action: el.form ? el.form.action : '',
                form_method: el.form ? el.form.method : ''
            };
        }''')

    def form_values(self):
        return self._capture(self.page)['fields']

    def screenshot(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(path), full_page=True)
        return str(path)

    def fresh_snapshots(self):
        results = []

        for url in list(self.visited_urls):
            tab = self.context.new_page()
            try:
                response = tab.goto(
                    self.safe_url(url),
                    wait_until='domcontentloaded',
                )
                data = self._capture(tab)
                data['status'] = response.status if response else None
                results.append(data)
            except Exception as error:
                results.append({'url': url, 'error': str(error)})
            finally:
                tab.close()

        return results

    def close(self):
        try:
            self.context.close()
            self.browser.close()
        finally:
            self._playwright.stop()


if __name__ == '__main__':
    browser = Browser()

    try:
        print(browser.open_url('/bills'))
        browser.open_url('/bills/new')
        browser.fill('#vendor_id', 'Globex Logistics')
        browser.fill('#invoice_number', 'BROWSER-CHECK')

        fields = {
            field['id']: field
            for field in browser.form_values()
        }

        if fields['vendor_id']['selected'] != ['Globex Logistics']:
            raise RuntimeError('Dropdown selection check failed.')

        if fields['invoice_number']['value'] != 'BROWSER-CHECK':
            raise RuntimeError('Text field check failed.')

        print(browser.get_page())

        path = browser.screenshot(
            PROJECT_ROOT / 'runs' / 'browser_check.png'
        )
        print('Screenshot saved:', path)
        input('Browser check passed. Press Enter to close Chromium. ')

    finally:
        browser.close()