"""Synthetic fixtures only. These are NOT Amazon B0H4VBC1SD evidence."""
import argparse
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from listing_core import ListingError, parse_page, json_value, asin_from, assign_dimensions
from browser_capture import choose_browser, classify_exception, capture
from import_html import run as import_run
from reports import family_report, summary

PARENT = 'B000000000'
ONE = 'B000000001'
TWO = 'B000000002'


def fixture(asin=ONE, price='$20.00', bullets='One soft pillow.', mapping=True, modern=False):
    about = f'<h3>About this item</h3><ul><li>{bullets}</li></ul>' if modern else f'<div id="feature-bullets"><ul><li>{bullets}</li></ul></div>'
    return f'''<html><head><title>Fixture pillow 500g</title></head><body>
    <input id="ASIN" value="{asin}"><span id="productTitle">Fixture pillow</span>
    <div id="corePriceDisplay_desktop_feature_div"><span class="a-price"><span class="a-offscreen">{price}</span></span>
    <span class="a-price a-text-price"><span class="a-offscreen">$99.00</span></span></div>
    <aside><span class="a-price"><span class="a-offscreen">$1.00</span></span></aside>
    <div id="availability">In Stock<script>secret()</script></div>
    <div id="glow-ingress-line2">Washington 20003</div>
    <table><tr><th>Brand</th><td>Fixture Brand</td></tr></table>
    {about}<div id="productDescription">Fixture description</div>
    <div id="aplus"><style>.hidden {{display:none}}</style>Fixture A+<img src="https://example.invalid/aplus.png"></div>
    <script>{{"parentAsin":"{PARENT}","dimensionValuesDisplayData":{json.dumps({ONE:['Cream','10 inch (Pack of 1)'], TWO:['Charcoal','10 inch (Pack of 1)']} if mapping else {})},
    "sortedDimValuesForAllDims":{{"size_name":[{{"dimensionValueDisplayText":"10 inch (Pack of 1)"}}],"color_name":[{{"dimensionValueDisplayText":"Cream"}},{{"dimensionValueDisplayText":"Charcoal"}}]}}}}</script>
    </body></html>'''


class ParsingTests(unittest.TestCase):
    def test_asin_and_url(self):
        self.assertEqual(asin_from('https://www.amazon.com/dp/b000000001?th=1'), ONE)
        for value in ('../bad', 'https://evil.example/dp/' + ONE, 'https://www.amazon.com.evil/dp/' + ONE):
            with self.assertRaises(ListingError):
                asin_from(value)

    def test_price_excludes_recommendations_and_list_price(self):
        self.assertEqual(parse_page(fixture())['prices'], ['$20.00'])

    def test_no_price_is_not_out_of_stock(self):
        data = parse_page('<h1 id="productTitle">Fixture</h1><div class="a-price"><span class="a-offscreen">$5</span></div>')
        self.assertEqual(data['prices'], [])
        self.assertEqual(data['availability'], '')

    def test_old_and_new_bullets(self):
        for modern in (False, True):
            self.assertEqual(parse_page(fixture(modern=modern))['bullets'], ['One soft pillow.'])

    def test_aplus_and_clean_stock(self):
        data = parse_page(fixture())
        self.assertEqual(data['availability'], 'In Stock')
        self.assertEqual(data['aplus_text'], ['Fixture A+'])
        self.assertEqual(len(data['aplus_images']), 1)
        self.assertEqual(data['brand'], 'Fixture Brand')

    def test_nested_json_string_braces(self):
        self.assertEqual(json_value('"foo": {"x":"} and \\\" hi", "nested":{"y":2}}', 'foo')['nested'], {'y': 2})

    def test_reordered_dimensions(self):
        data = parse_page(fixture())
        self.assertEqual(assign_dimensions(data['children'][ONE], data['dimension_sets']), {'color_name':'Cream','size_name':'10 inch (Pack of 1)'})

    def test_ambiguous_dimensions_remain_unknown(self):
        self.assertEqual(assign_dimensions(['1'], {'size':{'1'}, 'items':{'1'}}), {'unmapped':'1'})

    def test_invalid_pages_never_succeed(self):
        for raw, code in [('', 'EMPTY_HTML'), ('<form action="validateCaptcha"><input id="captchacharacters"></form>', 'CAPTCHA'),
                          ('<title>Sign in</title>', 'LOGIN_REQUIRED'), ('<p>ERR_BLOCKED_BY_ADMINISTRATOR</p>', 'NETWORK_POLICY_BLOCKED'),
                          ('<p>Access Denied</p>', 'NETWORK_BLOCKED'), ('<h1>Something else</h1>', 'NOT_PRODUCT_PAGE')]:
            with self.subTest(code=code), self.assertRaises(ListingError) as ctx:
                parse_page(raw)
            self.assertEqual(ctx.exception.code, code)

    def test_parent_redirect_and_wrong_child(self):
        self.assertEqual(parse_page(fixture(), PARENT)['observed_asin'], ONE)
        with self.assertRaises(ListingError) as ctx:
            parse_page(fixture(), TWO)
        self.assertEqual(ctx.exception.code, 'ASIN_MISMATCH')

    def test_module_imports_have_no_side_effects(self):
        for name in ['capture_single','capture_all_variants','extract_page','summarize_variants','bullets_by_variant','variant_diff']:
            importlib.import_module(name)


class OfflineWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.inputs = self.base / 'input'
        self.inputs.mkdir()
        self.output = self.base / 'output'

    def tearDown(self):
        self.temp.cleanup()

    def run_import(self):
        return import_run(argparse.Namespace(target=PARENT, html=None, html_dir=str(self.inputs), output=str(self.output)))

    def test_complete_family_bom_reports_full_bullets(self):
        long_bullet = 'Fixture evidence ' * 50
        (self.inputs / (ONE + '.html')).write_text(fixture(bullets=long_bullet), encoding='utf-8-sig')
        (self.inputs / (TWO + '.html')).write_text(fixture(TWO, '$25.00', bullets='Different template 450g'), encoding='utf-8')
        self.assertEqual(self.run_import(), 0)
        family_report(self.output, PARENT, 'all')
        parent = self.output / PARENT
        summary = (parent / 'variants_summary.md').read_text(encoding='utf-8')
        self.assertIn('PRICE_LIST (by color_name)', summary)
        self.assertNotIn('$1.00', summary)
        self.assertIn('Fixture evidence ' * 30, (parent / 'bullets_by_variant.txt').read_text(encoding='utf-8'))
        diff = (parent / 'variant_diff.md').read_text(encoding='utf-8')
        self.assertIn('BULLET_GROUPS: 2', diff)
        self.assertIn('Fixture A+', diff)
        self.assertIn('weight in grams', diff)

    def test_missing_child_and_stale_file_excluded(self):
        (self.inputs / 'one.html').write_text(fixture(), encoding='utf-8')
        stale = self.output / TWO
        stale.mkdir(parents=True)
        (stale / 'page.html').write_text(fixture(TWO, '$999.00'), encoding='utf-8')
        self.assertEqual(self.run_import(), 3)
        family_report(self.output, PARENT, 'all')
        summary = (self.output / PARENT / 'variants_summary.md').read_text(encoding='utf-8')
        self.assertNotIn('$999.00', summary)
        self.assertIn('not acquired in current run', summary)

    def test_changed_snapshot_not_trusted(self):
        (self.inputs / 'one.html').write_text(fixture(), encoding='utf-8')
        self.run_import()
        (self.output / ONE / 'page.html').write_text(fixture(price='$888.00'), encoding='utf-8')
        family_report(self.output, PARENT, 'summary')
        text = (self.output / PARENT / 'variants_summary.md').read_text(encoding='utf-8')
        self.assertIn('SNAPSHOT_CHANGED', text)
        self.assertNotIn('$888.00', text)

    def test_invalid_html_fails_no_children_claim(self):
        (self.inputs / 'page.html').write_text('<title>Robot Check</title>', encoding='utf-8')
        self.assertEqual(self.run_import(), 2)
        manifest = json.loads((self.output / PARENT / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['coverage']['captured'], 0)

    def test_wrong_target_not_relabelled(self):
        path = self.inputs / (ONE + '.html')
        path.write_text(fixture(), encoding='utf-8')
        result = import_run(argparse.Namespace(target=TWO, html=str(path), html_dir=None, output=str(self.output)))
        self.assertEqual(result, 2)

    def test_single_without_map(self):
        path = self.inputs / 'single.html'
        path.write_text(fixture(mapping=False), encoding='utf-8')
        self.assertEqual(import_run(argparse.Namespace(target=ONE, html=str(path), html_dir=None, output=str(self.output))), 0)
        family_report(self.output, ONE, 'summary')
        self.assertIn('PRICE_MATRIX: n/a', (self.output / ONE / 'variants_summary.md').read_text(encoding='utf-8'))

    def test_punctuation_does_not_split_group(self):
        for asin, bullet in [(ONE,'One soft pillow.'),(TWO,'ONE SOFT PILLOW!')]:
            (self.inputs / (asin + '.html')).write_text(fixture(asin, bullets=bullet), encoding='utf-8')
        self.run_import()
        family_report(self.output, PARENT, 'diff')
        self.assertIn('BULLET_GROUPS: 1', (self.output / PARENT / 'variant_diff.md').read_text(encoding='utf-8'))

    def test_offline_no_selenium_or_network(self):
        # A fresh interpreter blocks imports, not merely a mock of a known HTTP client.
        script = '''import sys
class Block:
 def find_spec(self, name, *args):
  if name.split('.')[0] in ('selenium','socket','urllib3','requests'):
   raise RuntimeError('Forbidden in offline mode: '+name)
sys.meta_path.insert(0,Block())
from import_html import main
raise SystemExit(main())
'''
        (self.inputs / 'single.html').write_text(fixture(mapping=False), encoding='utf-8')
        result = subprocess.run([sys.executable,'-c',script,ONE,'--html',str(self.inputs / 'single.html'),'--output',str(self.output)],
                                cwd=Path(__file__).resolve().parents[1] / 'scripts', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_directory_has_clear_error(self):
        result = import_run(argparse.Namespace(target=ONE, html=None, html_dir=str(self.base / 'not-there'), output=str(self.output)))
        self.assertEqual(result, 2)
        self.assertIn('NO_HTML_FILES', (self.output / ONE / 'diagnostics.json').read_text())

    def test_conflicting_snapshots_diagnosed(self):
        (self.inputs / 'a.html').write_text(fixture(), encoding='utf-8')
        (self.inputs / 'b.html').write_text(fixture(price='$30.00'), encoding='utf-8')
        self.assertEqual(self.run_import(), 3)
        self.assertIn('DUPLICATE_ASIN', (self.output / PARENT / 'diagnostics.json').read_text())

    def test_failed_rerun_excludes_previous_success(self):
        path = self.inputs / 'a.html'
        path.write_text(fixture(), encoding='utf-8')
        self.run_import()
        path.write_text('<title>Robot Check</title>', encoding='utf-8')
        self.assertEqual(self.run_import(), 2)
        family_report(self.output, PARENT, 'all')
        self.assertNotIn('$20.00', (self.output / PARENT / 'variants_summary.md').read_text())

    def test_three_dimensions_preserve_price_collisions(self):
        rows = []
        for asin, color, size, style, price in [(ONE,'Cream','S','Ball','$20'),(TWO,'Cream','S','Knot','$25'),('B000000003','Blue','L','Ball','$30')]:
            rows.append(dict(asin=asin, dimensions=dict(color=color,size=size,style=style), status='ok',data=dict(prices=[price])))
        text = '\n'.join(summary(rows))
        self.assertIn('PRICE_MATRIX', text)
        self.assertIn(ONE + ': $20; ' + TWO + ': $25', text)

    def test_cli_failure_exit_code(self):
        result = subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/import_html.py'),ONE,'--html',str(self.inputs/'missing.html'),'--output',str(self.output)],capture_output=True,text=True)
        self.assertEqual(result.returncode, 2)


class BrowserRoutingTests(unittest.TestCase):
    def test_online_family_reports_observed_children(self):
        from unittest.mock import MagicMock
        driver = MagicMock()
        driver.current_url = 'https://www.amazon.com/dp/' + PARENT
        parent = fixture()
        pages = [(parent,parse_page(parent)),(parent,parse_page(parent)),
                 (fixture(),parse_page(fixture())),(fixture(TWO),parse_page(fixture(TWO)))]
        with tempfile.TemporaryDirectory() as temp, patch('browser_capture.make_driver', return_value=(driver, {'family':'edge'})), patch('browser_capture.load_product', side_effect=pages), patch('browser_capture.set_zip',return_value={'request_ok':True}):
            args = argparse.Namespace(target=PARENT,zip='20003',output=temp,timeout=1,delay=0)
            self.assertEqual(capture(args),0)
            run = json.loads((Path(temp)/PARENT/'run.json').read_text())
            self.assertEqual(run['coverage']['captured'],2)
            self.assertTrue(run['delivery_zip_verified'])
            self.assertEqual(run['pages'][PARENT]['observed_asin'],ONE)
            driver.quit.assert_called_once()

    def test_requested_child_screenshot_is_not_overwritten_by_sibling(self):
        from unittest.mock import MagicMock
        driver = MagicMock()
        driver.current_url = 'https://www.amazon.com/dp/' + ONE
        raw_target = fixture()
        raw_sibling = fixture(TWO)
        pages = [(raw_target,parse_page(raw_target)),(raw_target,parse_page(raw_target)),
                 (raw_sibling,parse_page(raw_sibling))]
        with tempfile.TemporaryDirectory() as temp, patch('browser_capture.make_driver', return_value=(driver, {'family':'edge'})), patch('browser_capture.load_product', side_effect=pages), patch('browser_capture.set_zip',return_value={'request_ok':True}):
            args = argparse.Namespace(target=ONE,zip='20003',output=temp,timeout=1,delay=0)
            self.assertEqual(capture(args),0)
            screenshot_dirs = [Path(call.args[0]).parent.name for call in driver.save_screenshot.call_args_list]
            self.assertEqual(screenshot_dirs,[ONE,TWO])

    def test_partial_online_and_unverified_zip(self):
        from unittest.mock import MagicMock
        driver = MagicMock()
        driver.current_url = 'https://www.amazon.com/dp/' + PARENT
        raw = fixture().replace('Washington 20003','Deliver to Canada')
        pages = [(raw,parse_page(raw)),(raw,parse_page(raw)),(raw,parse_page(raw)),ListingError('CAPTCHA','fixture robot page')]
        with tempfile.TemporaryDirectory() as temp, patch('browser_capture.make_driver',return_value=(driver,{})), patch('browser_capture.load_product',side_effect=pages), patch('browser_capture.set_zip',return_value={}):
            args = argparse.Namespace(target=PARENT,zip='20003',output=temp,timeout=1,delay=0)
            self.assertEqual(capture(args),3)
            run = json.loads((Path(temp)/PARENT/'run.json').read_text())
            self.assertFalse(run['delivery_zip_verified'])
            self.assertEqual(run['coverage']['missing'],[TWO])
            self.assertEqual(run['errors'][0]['code'],'CAPTCHA')
            driver.quit.assert_called_once()

    def test_windows_edge_and_linux_chromium_selection(self):
        for family, binary in [('edge','C:/Edge/msedge.exe'),('chrome','/usr/bin/chromium')]:
            with patch('browser_capture.browser_candidates', return_value=iter([(family,binary)])), patch('pathlib.Path.is_file', return_value=True):
                self.assertEqual(choose_browser(), (family,binary))

    def test_missing_browser(self):
        with patch('browser_capture.browser_candidates', return_value=iter([])), self.assertRaises(ListingError) as ctx:
            choose_browser()
        self.assertEqual(ctx.exception.code, 'BROWSER_MISSING')

    def test_policy_diagnosis(self):
        self.assertEqual(classify_exception(Exception('net::ERR_BLOCKED_BY_ADMINISTRATOR')).code, 'NETWORK_POLICY_BLOCKED')

    def test_failed_capture_has_nonzero_status_and_receipt(self):
        with tempfile.TemporaryDirectory() as temp, patch('browser_capture.make_driver', side_effect=ListingError('DEPENDENCY_MISSING','fixture')):
            args = argparse.Namespace(target=ONE, zip='20003', output=temp)
            self.assertEqual(capture(args), 2)
            run = json.loads((Path(temp)/ONE/'run.json').read_text(encoding='utf-8'))
            self.assertEqual(run['status'],'failed')
            self.assertEqual(run['errors'][0]['code'],'DEPENDENCY_MISSING')


if __name__ == '__main__':
    unittest.main()
