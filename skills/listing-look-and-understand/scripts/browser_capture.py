"""Cross-platform capture CLI. Selenium is loaded only for online capture."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time

from listing_core import ListingError, asin_from, parse_page, sha, write_json

VERSION = '1.1.1'


def browser_candidates(system=None):
    system = system or platform.system()
    if system == 'Windows':
        for family, rel in [('edge', 'Microsoft/Edge/Application/msedge.exe'), ('chrome', 'Google/Chrome/Application/chrome.exe')]:
            for base in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA'):
                if os.environ.get(base):
                    yield family, str(Path(os.environ[base]) / rel)
    for family, names in [('chrome', ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser']), ('edge', ['microsoft-edge', 'microsoft-edge-stable', 'msedge'])]:
        for name in names:
            if found := shutil.which(name):
                yield family, found


def choose_browser(family='auto', binary=None):
    if binary:
        path = Path(binary).expanduser().resolve()
        if not path.is_file():
            raise ListingError('BROWSER_MISSING', f'Browser binary does not exist: {path}')
        if family == 'auto':
            name = path.name.lower()
            if 'edge' in name:
                family = 'edge'
            elif 'chrom' in name:
                family = 'chrome'
            else:
                raise ListingError('INVALID_INPUT', 'Use --browser edge/chrome with a custom browser binary.')
        return family, str(path)
    for kind, path in browser_candidates():
        if (family == 'auto' or family == kind) and Path(path).is_file():
            return kind, path
    raise ListingError('BROWSER_MISSING', 'No compatible installed browser found. Use --binary PATH or offline HTML import; no browser is downloaded automatically.')


def classify_exception(exc):
    message = str(exc)
    value = message.lower()
    if 'err_blocked_by_administrator' in value:
        return ListingError('NETWORK_POLICY_BLOCKED', 'Browser reports ERR_BLOCKED_BY_ADMINISTRATOR; use offline import. ' + message[:300])
    if any(s in value for s in ('err_name_not_resolved', 'err_connection', 'err_proxy', 'err_tunnel', 'err_internet', 'err_cert')):
        return ListingError('NETWORK_ERROR', message[:500] + ' Use authorized offline HTML; do not disable certificate/network protections.')
    if 'nosuchdriver' in type(exc).__name__.lower() or 'unable to obtain driver' in value:
        return ListingError('DRIVER_UNAVAILABLE', 'Driver resolution failed (possibly restricted download). Supply a matching local --driver PATH. ' + message[:300])
    if 'timeout' in type(exc).__name__.lower():
        return ListingError('PAGE_TIMEOUT', 'Browser operation timed out; reachability is unconfirmed. ' + message[:300])
    return ListingError('BROWSER_START_OR_RUNTIME_FAILED', message[:600])


def make_driver(args):
    if not importlib.util.find_spec('selenium'):
        raise ListingError('DEPENDENCY_MISSING', 'Online capture needs requirements-online.txt (selenium). Offline import only needs lxml.')
    family, binary = choose_browser(args.browser, args.binary)
    from selenium import webdriver
    if family == 'edge':
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.edge.service import Service
        constructor = webdriver.Edge
    else:
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        constructor = webdriver.Chrome
    options = Options()
    options.binary_location = binary
    if not args.headed:
        options.add_argument('--headless=new')
    options.add_argument('--window-size=1400,1800')
    options.add_argument('--lang=en-US')
    # No sandbox-disabling, certificate bypass, or automation-concealment flags.
    options.page_load_strategy = 'eager'
    driver_path = args.driver or shutil.which('msedgedriver' if family == 'edge' else 'chromedriver')
    if driver_path and not Path(driver_path).is_file():
        raise ListingError('DRIVER_UNAVAILABLE', f'Driver does not exist: {driver_path}')
    service = Service(executable_path=str(driver_path)) if driver_path else Service()
    try:
        driver = constructor(options=options, service=service)
        driver.set_page_load_timeout(args.timeout)
        driver.set_script_timeout(min(args.timeout, 15))
        return driver, dict(family=family, binary=binary, driver=driver_path or 'Selenium Manager',
                            version=driver.capabilities.get('browserVersion'))
    except Exception as exc:
        raise classify_exception(exc) from exc


def set_zip(driver, zipcode):
    # An acknowledged request alone is not proof that the page uses this delivery ZIP.
    try:
        return driver.execute_async_script("""
            const zip=arguments[0], done=arguments[arguments.length-1];
            fetch('/gp/delivery/ajax/address-change.html', {
              method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'},
              body:new URLSearchParams({locationType:'LOCATION_INPUT',zipCode:zip,
                storeContext:'generic',deviceType:'web',pageType:'Detail',actionSource:'glow'})
            }).then(r=>done({request_ok:r.ok,status:r.status})).catch(e=>done({error:String(e)}));
        """, zipcode)
    except Exception as exc:
        return dict(error=str(exc)[:250])


def load_product(driver, asin, timeout):
    try:
        driver.get('https://www.amazon.com/dp/' + asin)
        end = time.monotonic() + timeout
        while True:
            raw = driver.page_source
            if re.search(r'id\s*=\s*[\"\x27]productTitle[\"\x27]', raw) or any(s in raw.lower() for s in ('captchacharacters', 'validatecaptcha', 'err_blocked_by_administrator')):
                break
            if time.monotonic() >= end:
                break
            time.sleep(0.25)
        data = parse_page(raw, asin)
        # Trigger lazy A+ images before saving the final DOM.
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight)')
        time.sleep(0.5)
        raw = driver.page_source
        data = parse_page(raw, asin)
        return raw, data
    except ListingError:
        raise
    except Exception as exc:
        raise classify_exception(exc) from exc


def save_page(root, asin, raw, data, source, run_id, **extra):
    out = root / asin
    out.mkdir(parents=True, exist_ok=True)
    (out / 'page.html').write_text(raw, encoding='utf-8')
    record = dict(status='ok', source=source, run_id=run_id, sha256=sha(raw),
                  observed_asin=data['observed_asin'], parent_asin=data['parent_asin'],
                  warnings=data['warnings'], **extra)
    write_json(out / 'capture.json', record)
    return record


def new_manifest(target, source, zipcode=None):
    now = datetime.now(timezone.utc).isoformat()
    return dict(version=VERSION, run_id=now, target_asin=target, source=source,
                started_at=now, requested_zip=zipcode, pages={}, errors=[], warnings=[],
                family_completeness='unknown; only page-disclosed ASINs can be enumerated')


def finish(root, target, manifest, children):
    out = root / target
    out.mkdir(parents=True, exist_ok=True)
    ok = [a for a in children if manifest['pages'].get(a, {}).get('status') == 'ok']
    missing = [a for a in children if a not in ok]
    manifest['coverage'] = dict(discovered=len(children), captured=len(ok), missing=missing)
    manifest['status'] = 'failed' if not ok or not children else ('partial' if missing or manifest['errors'] else 'ok')
    write_json(out / 'children.json', children)
    write_json(out / 'run.json', manifest)
    write_json(out / 'diagnostics.json', dict(status=manifest['status'], errors=manifest['errors'], warnings=manifest['warnings'],
                                            fallback='Run import_html.py TARGET --html FILE (single saved page), or --html-dir DIRECTORY (multiple pages).'))
    print(json.dumps(dict(status=manifest['status'], coverage=manifest['coverage'], errors=manifest['errors'], warnings=manifest['warnings'], output=str(out)), ensure_ascii=False))
    return 0 if manifest['status'] == 'ok' else (3 if manifest['status'] == 'partial' else 2)


def capture(args, all_variants=True):
    target = asin_from(args.target)
    if not re.fullmatch(r'\d{5}', args.zip):
        raise ListingError('INVALID_INPUT', 'ZIP must contain five digits.')
    root = Path(args.output).resolve()
    manifest = new_manifest(target, 'online', args.zip)
    driver = None
    children = {}
    try:
        driver, manifest['browser'] = make_driver(args)
        raw, data = load_product(driver, target, args.timeout)
        manifest['zip_request'] = set_zip(driver, args.zip)
        raw, data = load_product(driver, target, args.timeout)
        manifest['delivery_text'] = data['delivery']
        manifest['delivery_zip_verified'] = bool(re.search(r'(?<!\d)' + args.zip + r'(?!\d)', data['delivery']))
        if not manifest['delivery_zip_verified']:
            manifest['warnings'].append('DELIVERY_UNVERIFIED: price/availability cannot be claimed to apply to requested US ZIP.')
        manifest['parent_asin'] = data['parent_asin']
        children = (data['children'] if all_variants else {}) or {data['observed_asin'] or target: []}
        if all_variants and not data['children']:
            manifest['warnings'].append('VARIATIONS_UNDISCOVERED: no embedded variation map; does not prove a single-variant family.')
        manifest['pages'][target] = save_page(root, target, raw, data, 'online', manifest['run_id'], url=driver.current_url)
        try:
            driver.execute_script('window.scrollTo(0,0)')
            driver.save_screenshot(str(root / target / 'page_top.png'))
        except Exception as exc:
            manifest['warnings'].append(f'{target}: SCREENSHOT_FAILED: {str(exc)[:150]}')
        for asin in children:
            if asin == target and data['observed_asin'] in (None, target):
                # The requested child was captured above. Do not save another
                # screenshot here: earlier sibling navigation may have left
                # the browser displaying a different variant.
                continue
            else:
                time.sleep(args.delay)
                try:
                    child_raw, child_data = load_product(driver, asin, args.timeout)
                    if child_data['observed_asin'] and child_data['observed_asin'] != asin:
                        raise ListingError('ASIN_MISMATCH', 'Child page redirected to a different selected ASIN.')
                    manifest['pages'][asin] = save_page(root, asin, child_raw, child_data, 'online', manifest['run_id'], url=driver.current_url)
                except ListingError as exc:
                    manifest['pages'][asin] = dict(status='failed', code=exc.code)
                    manifest['errors'].append(dict(asin=asin, code=exc.code, message=str(exc)))
                    if exc.code in ('CAPTCHA', 'NETWORK_POLICY_BLOCKED', 'NETWORK_BLOCKED'):
                        break
                    continue
            page_out = root / asin
            try:
                driver.execute_script('window.scrollTo(0,0)')
                driver.save_screenshot(str(page_out / 'page_top.png'))
            except Exception as exc:
                manifest['warnings'].append(f'{asin}: SCREENSHOT_FAILED: {str(exc)[:150]}')
    except ListingError as exc:
        manifest['errors'].append(dict(code=exc.code, message=str(exc)))
    except (OSError, UnicodeError) as exc:
        manifest['errors'].append(dict(code='FILE_ERROR', message=str(exc)))
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
    return finish(root, target, manifest, children)


def main(all_variants=True):
    p = argparse.ArgumentParser(description='Capture Amazon US DOM with Windows Edge or Linux Chrome/Chromium. Offline alternative: import_html.py.')
    p.add_argument('target', nargs='?', help='ASIN or Amazon US URL')
    p.add_argument('zip', nargs='?', default='20003')
    p.add_argument('--browser', choices=['auto', 'edge', 'chrome'], default='auto')
    p.add_argument('--binary', help='Installed browser executable')
    p.add_argument('--driver', help='Matching local driver; avoids driver downloads')
    p.add_argument('--headed', action='store_true')
    p.add_argument('--timeout', type=float, default=25)
    p.add_argument('--delay', type=float, default=1.5)
    p.add_argument('--output', default='product_pages')
    p.add_argument('--diagnose', action='store_true', help='Only inspect local dependencies/browser; no network or browser launch')
    args = p.parse_args()
    if args.diagnose:
        report = dict(python=sys.version, platform=platform.platform(), dependencies={m:bool(importlib.util.find_spec(m)) for m in ['lxml','selenium']})
        try:
            report['browser'] = choose_browser(args.browser, args.binary)
        except ListingError as exc:
            report['browser_error'] = dict(code=exc.code, message=str(exc))
        print(json.dumps(report, indent=2))
        return 0 if all(report['dependencies'].values()) and 'browser' in report else 2
    if not args.target or args.timeout <= 0 or args.delay < 0:
        p.error('target is required, timeout must be positive, and delay cannot be negative')
    try:
        return capture(args, all_variants)
    except ListingError as exc:
        print(json.dumps(dict(code=exc.code, message=str(exc))))
        return 2
