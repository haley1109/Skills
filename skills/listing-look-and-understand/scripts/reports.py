"""Shared reports preserve source, coverage, prices, A+ and per-child differences."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

from listing_core import ListingError, asin_from, assign_dimensions, read_json, read_page, sha, write_json


def cell(value):
    return str(value if value not in ('', None, []) else 'unknown').replace('|', '\\|').replace('\n', ' ')


def table(headers, rows):
    return ['| ' + ' | '.join(map(cell, headers)) + ' |', '|' + '---|' * len(headers)] + ['| ' + ' | '.join(map(cell, r)) + ' |' for r in rows]


def page_report(path):
    path = Path(path)
    data = read_page(path)
    provenance = read_json(path.parent / 'capture.json') if (path.parent / 'capture.json').exists() else {'source': 'untracked local HTML'}
    sections = [('Title', data['title']), ('Brand', data['brand']), ('Breadcrumb / Category', ' > '.join(data['category'])),
                ('Selected ASIN', data['observed_asin']), ('Parent ASIN (page evidence)', data['parent_asin']),
                ('Price (main product only)', data['prices']), ('Availability', data['availability']),
                ('Delivery location', data['delivery']), ('Coupon / Promo', data['coupon']),
                ('Rating / Reviews (page aggregate; not child-specific proof)', [data['rating'], data['review_text']]),
                ('About this item (bullets)', data['bullets']), ('Product description', data['description']),
                ('A+ content (text)', data['aplus_text']), ('A+ image URLs (visual review required)', data['aplus_images']),
                ('Product details', data['details']), ('Main image', data['image']),
                ('Variation data', json.dumps(data['children'], ensure_ascii=False))]
    lines = ['# Amazon product snapshot', '', 'Source: ' + json.dumps(provenance, ensure_ascii=False), '',
             'Missing fields are unknown. No price does not prove unavailability; no A+ text does not prove image-only A+.', '']
    for title, value in sections:
        lines += ['## ' + title, '']
        lines += ['- ' + str(v) for v in value] if isinstance(value, list) and value else [str(value or 'unknown')]
        lines += ['']
    (path.parent / 'page_content.md').write_text('\n'.join(lines), encoding='utf-8')
    serial = {k: v for k, v in data.items() if k != 'dimension_sets'}
    write_json(path.parent / 'page_content.json', serial)
    return data


def family(root, target):
    root = Path(root)
    manifest_path = root / target / 'run.json'
    manifest = read_json(manifest_path) if manifest_path.exists() else None
    kids = read_json(root / target / 'children.json')
    if not isinstance(kids, dict) or any(asin_from(a) != a or not isinstance(v, list) for a, v in kids.items()):
        raise ListingError('INVALID_CHILDREN', 'children.json must map ASINs to dimension value lists.')
    parent = None
    if not manifest or manifest.get('pages', {}).get(target, {}).get('status') == 'ok':
        if manifest:
            parent_raw = (root / target / 'page.html').read_text(encoding='utf-8-sig')
            if manifest['pages'][target].get('sha256') != sha(parent_raw):
                raise ListingError('SNAPSHOT_CHANGED', 'Target snapshot no longer matches this run; reimport before generating reports.')
        try:
            parent = read_page(root / target / 'page.html')
        except (ListingError, OSError):
            pass
    rows = []
    for asin, values in kids.items():
        entry = dict(asin=asin, values=values, dimensions=assign_dimensions(values, parent['dimension_sets'] if parent else {}), status='missing', data=None)
        path = root / asin / 'page.html'
        record = manifest.get('pages', {}).get(asin) if manifest else None
        if manifest and (not record or record.get('status') != 'ok'):
            entry['status'] = 'not acquired in current run'
        elif path.exists():
            try:
                raw = path.read_text(encoding='utf-8-sig')
                if record and record.get('sha256') != sha(raw):
                    raise ListingError('SNAPSHOT_CHANGED', 'HTML no longer matches this run')
                data = read_page(path, asin)
                if data['observed_asin'] and data['observed_asin'] != asin:
                    raise ListingError('ASIN_MISMATCH', 'DOM selects a different child')
                state = 'ok' if manifest else 'legacy snapshot; source untracked'
                if not data['observed_asin']:
                    state += '; ASIN identity unverified'
                entry.update(status=state, data=data)
            except (ListingError, OSError) as exc:
                entry['status'] = getattr(exc, 'code', 'FILE_ERROR') + ': ' + str(exc)
        rows.append(entry)
    prefix = ['Source: ' + (manifest['source'] if manifest else 'legacy/untracked'),
              'Coverage: ' + json.dumps(manifest.get('coverage', {}) if manifest else {}, ensure_ascii=False),
              'Family completeness: unknown beyond page-disclosed ASINs.',
              'Delivery verification: ' + str(manifest.get('delivery_zip_verified', 'unverified') if manifest else 'unverified'), '']
    if manifest:
        prefix += ['Warning: ' + str(w) for w in manifest.get('warnings', [])]
        prefix += ['Error: ' + json.dumps(e, ensure_ascii=False) for e in manifest.get('errors', [])]
        prefix += ['']
    return root, rows, prefix


def summary(rows):
    lines = ['VARIANT_TABLE', ''] + table(['ASIN', 'Dimensions', 'Price', 'Availability', 'Rating', 'Status'],
        [(r['asin'], json.dumps(r['dimensions'], ensure_ascii=False), ' / '.join((r['data'] or {}).get('prices', [])),
          (r['data'] or {}).get('availability', ''), (r['data'] or {}).get('rating', ''), r['status']) for r in rows])
    keys = set(k for r in rows for k in r['dimensions'] if k != 'unmapped')
    active = sorted((k for k in keys if len({r['dimensions'].get(k) for r in rows} - {None}) >= 2),
                    key=lambda k: (-len({r['dimensions'].get(k) for r in rows} - {None}), k))
    def price(r):
        return r['asin'] + ': ' + (' / '.join((r['data'] or {}).get('prices', [])) or 'unknown')
    if not active:
        lines += ['', 'PRICE_MATRIX: n/a (no mapped varying dimensions; family structure may be unknown)']
    elif len(active) == 1:
        key = active[0]
        lines += ['', 'PRICE_LIST (by ' + key + ')', ''] + table([key, 'ASIN / Price'], [(r['dimensions'].get(key, ''), price(r)) for r in rows])
    else:
        rowdim, coldim = active[:2]
        rv = sorted({r['dimensions'][rowdim] for r in rows if rowdim in r['dimensions']})
        cv = sorted({r['dimensions'][coldim] for r in rows if coldim in r['dimensions']})
        lines += ['', f'PRICE_MATRIX (row={rowdim}, col={coldim})', '',
                  'Multiple ASINs per cell are retained, including any additional dimensions.', '']
        matrix = [(v, *['; '.join(price(r) for r in rows if r['dimensions'].get(rowdim) == v and r['dimensions'].get(coldim) == c) or 'unknown' for c in cv]) for v in rv]
        lines += table([rowdim + ' / ' + coldim] + cv, matrix)
    lines += ['', 'IMAGE_BY_VARIANT', '']
    lines += ['- ' + r['asin'] + ': ' + ((r['data'] or {}).get('image') or 'unknown') for r in rows]
    return lines


def bullet_export(rows):
    lines = []
    for r in rows:
        lines += ['### ' + r['asin'] + ' | ' + ' / '.join(r['values']), 'status: ' + r['status'], 'title: ' + (r['data'] or {}).get('title', 'unknown')]
        lines += ['- ' + b for b in (r['data'] or {}).get('bullets', [])]
        lines += ['']
    return lines


def difference(rows):
    lines = ['TITLE_TABLE', ''] + table(['ASIN', 'Variant', 'Title', 'Meta title', 'Status'],
        [(r['asin'], ' / '.join(r['values']), (r['data'] or {}).get('title', ''), (r['data'] or {}).get('meta_title', ''), r['status']) for r in rows])
    groups = defaultdict(list)
    for r in rows:
        if r['data'] and r['data']['bullets']:
            signature = tuple(b.casefold().rstrip('.!。！ ').strip() for b in r['data']['bullets'])
            groups[signature].append(r['asin'])
    lines += ['', 'BULLET_GROUPS: ' + str(len(groups)) + ' (missing bullets excluded)']
    for idx, (bullets, asins) in enumerate(groups.items(), 1):
        lines += ['', f'## group {idx}', 'members: ' + ', '.join(asins)] + ['- ' + b for b in bullets]
    lines += ['', 'ANOMALIES (candidates for review; not established product facts)']
    found = False
    for r in rows:
        data = r['data']
        if not data:
            lines += ['- ' + r['asin'] + ': evidence missing; cannot compare.']
            found = True
            continue
        # Compare explicit quantities only; a dimension named Number of Items is not automatically pack size.
        titlepacks = set(re.findall(r'(?:set of|pack of)\s*(\d+)', data['title'], re.I))
        bulletpacks = set(re.findall(r'(?:set of|pack of)\s*(\d+)', ' '.join(data['bullets']), re.I))
        grams = lambda text: set(re.findall(r'\b(\d+(?:\.\d+)?)\s*g\b', text, re.I))
        titlegrams, bulletgrams = grams(data['title'] + ' ' + data['meta_title']), grams(' '.join(data['bullets']))
        for label, left, right in [('explicit pack count', titlepacks, bulletpacks), ('weight in grams', titlegrams, bulletgrams)]:
            if left and right and left != right:
                found = True
                lines += [f'- {r["asin"]}: title vs bullets {label}: {sorted(left)} / {sorted(right)}; confirm meaning and units with product evidence.']
    if not found:
        lines += ['- No explicit title/bullet quantity contradictions detected; this is not proof of consistency.']
    lines += ['', 'A+ / DESCRIPTION / DETAILS BY VARIANT', '']
    for r in rows:
        d = r['data'] or {}
        lines += ['### ' + r['asin'], 'Description: ' + ' / '.join(d.get('description', [])),
                  'A+ text: ' + ' / '.join(d.get('aplus_text', [])),
                  'A+ images: ' + ' / '.join(d.get('aplus_images', [])),
                  'Details: ' + ' / '.join(d.get('details', [])), '']
    return lines


def family_report(root, target, mode):
    root, rows, prefix = family(root, target)
    out = root / target
    modes = {'summary': ('variants_summary.md', summary), 'bullets': ('bullets_by_variant.txt', bullet_export), 'diff': ('variant_diff.md', difference)}
    for key, (filename, build) in modes.items():
        if mode in (key, 'all'):
            (out / filename).write_text('\n'.join(prefix + build(rows)), encoding='utf-8')
    if mode == 'all':
        manifest_file = out / 'run.json'
        latest = read_json(manifest_file) if manifest_file.exists() else None
        if (out / 'page.html').exists() and (not latest or latest.get('pages', {}).get(target, {}).get('status') == 'ok'):
            page_report(out / 'page.html')
        for r in rows:
            if r['data']:
                page_report(root / r['asin'] / 'page.html')
        lines = ['# Listing evidence overview', ''] + prefix + [
            'Requested ASIN: ' + target,
            f'Parsed children: {sum(bool(r["data"]) for r in rows)} / {len(rows)} disclosed or imported children.',
            'Read variants_summary.md for prices, variant_diff.md for child differences, and page_content.md for each snapshot.',
            'Product positioning, image interpretation and optimization recommendations require human/agent review of the evidence.',
            'Do not infer materials, care, pack meaning, variation compliance, or authentic reviews from missing fields.', '']
        (out / 'listing_overview.md').write_text('\n'.join(lines), encoding='utf-8')
    return 0


def main(mode):
    p = argparse.ArgumentParser()
    if mode == 'page':
        p.add_argument('html')
    else:
        p.add_argument('root')
        p.add_argument('target')
    args = p.parse_args()
    try:
        if mode == 'page':
            page_report(args.html)
        else:
            family_report(args.root, asin_from(args.target), mode)
        print('Report written; inspect provenance and coverage before using it.')
        return 0
    except (ListingError, OSError, ValueError) as exc:
        print(getattr(exc, 'code', 'REPORT_INPUT_ERROR') + ': ' + str(exc))
        return 2
