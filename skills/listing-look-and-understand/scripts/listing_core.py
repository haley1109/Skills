"""Shared, network-free Amazon DOM parsing. Missing evidence stays unknown."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


class ListingError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def asin_from(value):
    value = value.strip().upper()
    if ASIN_RE.fullmatch(value):
        return value
    url = urlparse(value.lower())
    if url.scheme not in ('http', 'https') or url.hostname not in ('amazon.com', 'www.amazon.com', 'smile.amazon.com'):
        raise ListingError('INVALID_INPUT', 'Use a 10-character ASIN or an Amazon US /dp/ or /gp/product/ URL.')
    match = re.search(r'/(?:dp|gp/product)/([a-z0-9]{10})(?:/|$)', url.path)
    if not match:
        raise ListingError('INVALID_INPUT', 'No ASIN in the Amazon US URL.')
    return match[1].upper()


def json_value(raw, key, default=None):
    # raw_decode respects braces in strings and nested objects; unlike brace-counting regex.
    pattern = r'(?:"' + re.escape(key) + r'"|\b' + re.escape(key) + r'\b)\s*[:=]\s*'
    for match in re.finditer(pattern, raw):
        try:
            return json.JSONDecoder().raw_decode(raw[match.end():])[0]
        except ValueError:
            continue
    return default


def clean(value):
    return ' '.join(value.split())


def text_of(node):
    return clean(' '.join(node.xpath('.//text()[not(ancestor::script) and not(ancestor::style)]')))


def sha(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def parse_page(raw, expected=None):
    try:
        from lxml import html
    except ImportError as exc:
        raise ListingError('DEPENDENCY_MISSING', 'Install requirements.txt (lxml) for offline parsing.') from exc
    if not raw.strip():
        raise ListingError('EMPTY_HTML', 'HTML is empty.')
    try:
        doc = html.fromstring(raw)
    except (ValueError, html.etree.ParserError) as exc:
        raise ListingError('PARSE_FAILED', str(exc)) from exc

    def texts(xp):
        return list(dict.fromkeys(t for n in doc.xpath(xp) if (t := text_of(n))))

    def first(xp):
        return next(iter(texts(xp)), '')

    visible = text_of(doc).lower()
    if 'err_blocked_by_administrator' in visible or 'blocked by your administrator' in visible:
        raise ListingError('NETWORK_POLICY_BLOCKED', 'Browser reports an administrator network block; use authorized offline HTML.')
    if doc.xpath('//*[@id="captchacharacters"] | //form[contains(@action,"validateCaptcha")]') or ('robot check' in visible and not doc.xpath('//*[@id="productTitle"]')):
        raise ListingError('CAPTCHA', 'Amazon returned a robot check. Stop automatic capture and import an authorized saved page.')
    if not first('//*[@id="productTitle"]'):
        if 'sign in' in first('//title').lower():
            raise ListingError('LOGIN_REQUIRED', 'A sign-in page was returned instead of a product.')
        if any(x in visible for x in ('access denied', 'request blocked', 'err_proxy', 'err_name_not_resolved', 'err_connection')):
            raise ListingError('NETWORK_BLOCKED', 'Access denied or a browser network error page was returned.')
        raise ListingError('NOT_PRODUCT_PAGE', 'No productTitle: incomplete HTML, changed layout, unavailable page, or access restriction; cause unconfirmed.')
    observed = doc.xpath('//*[@id="ASIN"]/@value')
    observed = next((a.upper() for a in observed if ASIN_RE.fullmatch(a.upper())), None)
    if not observed:
        canonical = doc.xpath('//link[@rel="canonical"]/@href')
        for url in canonical:
            try:
                observed = asin_from(url)
                break
            except ListingError:
                pass
    parent = json_value(raw, 'parentAsin') or json_value(raw, 'parentASIN')
    parent = parent.upper() if isinstance(parent, str) and ASIN_RE.fullmatch(parent.upper()) else None
    if expected and observed and observed != expected and parent != expected:
        raise ListingError('ASIN_MISMATCH', f'Requested {expected}; DOM identifies {observed}, parent {parent}.')
    children_raw = json_value(raw, 'dimensionValuesDisplayData', {})
    children = {a: [str(v) for v in vals] for a, vals in children_raw.items()
                if ASIN_RE.fullmatch(a) and isinstance(vals, list)} if isinstance(children_raw, dict) else {}
    dims = json_value(raw, 'sortedDimValuesForAllDims', {})
    dims = dims if isinstance(dims, dict) else {}
    dimsets = {k: {clean(str(item.get('dimensionValueDisplayText', ''))).lower() for item in vals if isinstance(item, dict)}
               for k, vals in dims.items() if isinstance(vals, list)}
    labels = json_value(raw, 'variationDisplayLabels', {})
    brand = first('//*[@id="bylineInfo" or @id="brand"]') or first('//tr[th[normalize-space(.)="Brand"]]/td')
    if not brand:
        brand = next((s for s in texts('//*[@id="detailBullets_feature_div"]//li') if re.match(r'^brand\b', s, re.I)), '')
    bullets = texts('//h3[contains(normalize-space(.),"About this item")]/following-sibling::ul[1]//li')
    bullets = bullets or texts('//*[@id="feature-bullets"]//li')
    prices = []
    for container in ('corePriceDisplay_desktop_feature_div', 'corePrice_feature_div', 'apex_desktop', 'buybox'):
        prices = texts(f'//*[@id="{container}"]//span[contains(concat(" ",normalize-space(@class)," ")," a-price ") and not(contains(@class,"a-text-price"))]//span[contains(@class,"a-offscreen")]')
        if prices:
            break
    prices = prices or texts('//*[@id="priceblock_ourprice" or @id="priceblock_dealprice"]')
    image = doc.xpath('//*[@id="landingImage"]/@src')
    dyn = doc.xpath('//*[@id="landingImage"]/@data-a-dynamic-image')
    try:
        image = [max(json.loads(dyn[0]).items(), key=lambda kv: kv[1][0] * kv[1][1])[0]] if dyn else image
    except (ValueError, TypeError, IndexError):
        pass
    ap_nodes = doc.xpath('//*[@id="aplus" or @id="aplus_feature_div"]')
    ap_text = list(dict.fromkeys(text_of(n) for n in ap_nodes if text_of(n)))
    ap_images = list(dict.fromkeys(doc.xpath('//*[@id="aplus" or @id="aplus_feature_div"]//img/@data-src | //*[@id="aplus" or @id="aplus_feature_div"]//img/@src')))
    details = texts('//*[@id="detailBullets_feature_div"]//li')
    for row in doc.xpath('//*[@id="productDetails_detailBullets_sections1" or @id="productDetails_techSpec_section_1" or @id="prodDetails"]//tr'):
        details.append(' : '.join(text_of(c) for c in row.xpath('./th|./td')))
    return dict(title=first('//*[@id="productTitle"]'), meta_title=first('//title'), brand=brand,
                observed_asin=observed, parent_asin=parent, children=children, dimension_sets=dimsets,
                dimension_labels=labels if isinstance(labels, dict) else {},
                category=texts('//*[@id="wayfinding-breadcrumbs_feature_div"]//a'), prices=prices,
                availability=first('//*[@id="availability"]'),
                delivery=first('//*[@id="glow-ingress-line2"]'),
                rating=next(iter(doc.xpath('//*[@id="acrPopover"]/@title')), ''),
                review_text=first('//*[@id="acrCustomerReviewText"]'), bullets=bullets,
                description=texts('//*[@id="productDescription"]'), aplus_text=ap_text,
                aplus_images=ap_images, details=list(dict.fromkeys(details)), image=next(iter(image), ''),
                coupon=first('//*[contains(@id,"coupon") or contains(@id,"promoPriceBlock") or contains(@class,"promoPriceBlockMessage")]'),
                warnings=[] if observed else ['ASIN_IDENTITY_UNVERIFIED: no selected ASIN or canonical URL in HTML'])


def assign_dimensions(values, dimension_sets):
    result = {}
    unknown = []
    for value in values:
        matches = [key for key, allowed in dimension_sets.items() if clean(value).lower() in allowed]
        if len(matches) == 1 and matches[0] not in result:
            result[matches[0]] = value
        else:
            unknown.append(value)
    if unknown:
        result['unmapped'] = ' / '.join(unknown)
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def read_page(path, expected=None):
    return parse_page(Path(path).read_text(encoding='utf-8-sig'), expected)
