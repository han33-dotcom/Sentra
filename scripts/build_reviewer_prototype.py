"""Embed src/sentra/reviewer/field_map.json into the reviewer prototype page.

    python scripts/build_reviewer_prototype.py

Run after editing the field map; tests/test_reviewer_prototype.py fails while they differ.
"""
import json
from pathlib import Path
import re

FOLDER = Path(__file__).resolve().parents[1] / 'src' / 'sentra' / 'reviewer'
TAG = re.compile(r'(<script id="field-map" type="application/json">)(.*?)(</script>)', re.S)


def main():
    page = FOLDER / 'prototype.html'
    fields = json.loads((FOLDER / 'field_map.json').read_text(encoding='utf-8'))
    body = json.dumps(fields, ensure_ascii=False, indent=1).replace('</', '<\\/')
    html = page.read_text(encoding='utf-8')
    if not TAG.search(html):
        raise SystemExit('prototype.html has no field-map script tag')
    page.write_text(TAG.sub(lambda m: m.group(1) + body + m.group(3), html, count=1), encoding='utf-8', newline='\n')
    print(f'Embedded {len(fields)} fields into {page.name}')


if __name__ == '__main__':
    main()
