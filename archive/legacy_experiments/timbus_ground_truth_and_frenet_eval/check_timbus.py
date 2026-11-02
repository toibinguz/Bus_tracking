import sys
import re

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\Users\Giang\.gemini\antigravity\brain\6147a42a-6e13-4d38-8c4a-d499c84a3554\.system_generated\steps\6266\content.md', 'r', encoding='utf-8', errors='ignore') as f:
    js = f.read()

# Find ajax calls and action parameters
actions = re.findall(r'action\.ashx\?([^\'\"\s]+)', js)
print('Actions in URL:')
for a in set(actions):
    print(' ', a)

posts = re.findall(r'act=([a-zA-Z0-9_]+)', js)
print('\nact parameter values:')
for p in set(posts):
    print(' ', p)

# Search functions
funcs = re.findall(r'function\s+([a-zA-Z0-9_]+)\s*\(', js)
relevant = [f for f in funcs if any(k in f.lower() for k in ['route', 'station', 'stop', 'bus', 'geo', 'map'])]
print('\nRelevant functions:')
for f in set(relevant):
    print(' ', f)
