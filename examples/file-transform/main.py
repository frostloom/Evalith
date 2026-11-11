"""Small deterministic command target for exercising Evalith file evidence."""
import json
import sys
from pathlib import Path

request = json.load(sys.stdin)
items = request.get('items', [])
if not isinstance(items, list) or any(not isinstance(item, dict) or type(item.get('cents')) is not int for item in items):
    raise ValueError('items must contain integer cents')
report = {'count': len(items), 'total_cent': sum(item['cents'] for item in items)}
Path('report.json').write_text(json.dumps(report))
print(json.dumps(report))
