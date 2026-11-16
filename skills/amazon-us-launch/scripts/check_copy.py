"""Check final copy lengths; conservative UTF-8 backend byte validation.

This checks mechanical limits only, not Amazon approval or claim accuracy.
"""
import argparse
import json
from pathlib import Path
import sys


def check(data, title_max=75, highlights_max=125, bullet_max=None, description_max=None):
    if not isinstance(data, dict):
        raise ValueError('Input must be a JSON object')
    errors = []
    lengths = {}
    for key, limit in [('title', title_max), ('highlights', highlights_max),
                       ('description', description_max), ('generic_keywords', None)]:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f'{key}: required nonempty string')
            continue
        lengths[key] = {'characters': len(value), 'utf8_bytes': len(value.encode('utf-8'))}
        if limit is not None and len(value) > limit:
            errors.append(f'{key}: {len(value)} characters exceeds {limit}')
        if key == 'generic_keywords':
            if len(value.encode('utf-8')) >= 250:
                errors.append('generic_keywords: must be fewer than 250 UTF-8 bytes')
            if value != value.strip() or any(ch in value for ch in '\r\n\t'):
                errors.append('generic_keywords: remove surrounding whitespace and line/tab characters')
    bullets = data.get('bullets')
    if not isinstance(bullets, list) or not bullets:
        errors.append('bullets: required nonempty string array')
    else:
        lengths['bullets'] = []
        for index, value in enumerate(bullets, 1):
            if not isinstance(value, str) or not value.strip():
                errors.append(f'bullet {index}: required nonempty string')
                continue
            lengths['bullets'].append(len(value))
            if bullet_max is not None and len(value) > bullet_max:
                errors.append(f'bullet {index}: exceeds {bullet_max} characters')
    return {'passed': not errors, 'lengths': lengths, 'errors': errors,
            'scope': 'Mechanical checks only. Verify category limits, facts and policies separately.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('json_file', type=Path)
    parser.add_argument('--title-max', type=int, default=75)
    parser.add_argument('--highlights-max', type=int, default=125)
    parser.add_argument('--bullet-max', type=int)
    parser.add_argument('--description-max', type=int)
    args = parser.parse_args()
    try:
        data = json.loads(args.json_file.read_text(encoding='utf-8-sig'))
        result = check(data, args.title_max, args.highlights_max,
                       args.bullet_max, args.description_max)
    except (OSError, ValueError, UnicodeError) as error:
        print(json.dumps({'passed': False, 'errors': [str(error)]}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
