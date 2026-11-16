"""Offline import never imports Selenium, launches a browser, or uses the network."""
import argparse
from pathlib import Path
from listing_core import ListingError, asin_from, parse_page
from browser_capture import new_manifest, save_page, finish


def run(args):
    target = asin_from(args.target)
    root = Path(args.output).resolve()
    manifest = new_manifest(target, 'offline')
    manifest['warnings'].append('OFFLINE_SNAPSHOT: save time and delivery location are unverified; not current live Amazon data.')
    files = [Path(args.html)] if args.html else sorted(Path(args.html_dir).rglob('*.html'))
    if not files:
        manifest['errors'].append(dict(code='NO_HTML_FILES', message='Directory is missing or contains no *.html files.'))
    children = {}
    accepted = {}
    seed = None
    for path in files:
        try:
            raw = path.read_text(encoding='utf-8-sig')
            data = parse_page(raw)
            inferred = path.stem.upper() if len(path.stem) == 10 else path.parent.name.upper()
            observed = data['observed_asin']
            # File name is only a fallback label, never proof of the selected ASIN.
            asin = observed or asin_from(target if args.html else inferred)
            if asin in accepted:
                if accepted[asin][0] != raw:
                    raise ListingError('DUPLICATE_ASIN', f'Conflicting snapshots for {asin}; provide one file per selected ASIN.')
                continue
            accepted[asin] = (raw, data, path)
            if asin == target or data['parent_asin'] == target:
                seed = seed or asin
        except (ListingError, OSError, UnicodeError) as exc:
            manifest['errors'].append(dict(file=str(path), code=getattr(exc, 'code', 'FILE_ERROR'), message=str(exc)))
    if seed is None:
        manifest['errors'].append(dict(code='TARGET_NOT_FOUND', message='No imported page identifies the target or its parent. Provide the target snapshot; a file name alone cannot override a conflicting DOM ASIN.'))
    else:
        raw, data, path = accepted[seed]
        children = dict(data['children']) or {seed: []}
        if not data['children']:
            manifest['warnings'].append('VARIATIONS_UNDISCOVERED: no map; family completeness unknown.')
        for asin, (raw, item, path) in accepted.items():
            if asin == target or asin in children or item['parent_asin'] == target:
                children.setdefault(asin, [])
                manifest['pages'][asin] = save_page(root, asin, raw, item, 'offline', manifest['run_id'], imported_from=str(path.resolve()))
        raw, data, path = accepted[seed]
        manifest['parent_asin'] = data['parent_asin']
        if target not in manifest['pages']:
            manifest['pages'][target] = save_page(root, target, raw, data, 'offline', manifest['run_id'], imported_from=str(path.resolve()), note='Target is parent; DOM selects a child.')
    return finish(root, target, manifest, children)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('target')
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument('--html')
    source.add_argument('--html-dir', help='Files named ASIN.html or ASIN/page.html; embedded ASIN has priority')
    p.add_argument('--output', default='product_pages')
    args = p.parse_args()
    try:
        return run(args)
    except ListingError as exc:
        p.exit(2, f'{exc.code}: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
