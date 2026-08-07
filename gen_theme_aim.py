#!/usr/bin/env python3
"""
gen_theme_aim.py — generate the SCOPED design-system stylesheet from the canonical one.

    frontend/theme.css   (canonical, hand-edited — the single source of truth)
            │
            ▼   python gen_theme_aim.py
            │
    frontend/theme.aim.css   (GENERATED — do not hand-edit)

Every rule in theme.css is namespaced under `.aim` so the design system styles ONLY
elements inside a `class="aim"` container and can never restyle the legacy /learn
screens. Keyframes are renamed `aim-*` (with their animation references) to avoid
colliding with the SPA's own @keyframes.

Rule: edit theme.css and re-run this; never commit a hand-edited theme.aim.css.

Usage:
    python gen_theme_aim.py                # frontend/theme.css -> frontend/theme.aim.css
    python gen_theme_aim.py SRC DST        # explicit paths
"""
import os
import re
import sys

HEADER = (
    "/* theme.aim.css - GENERATED from theme.css by gen_theme_aim.py. DO NOT HAND-EDIT.\n"
    "   Every rule is namespaced under .aim so it affects ONLY elements inside a\n"
    "   <... class=\"aim\"> container and cannot restyle existing /learn screens.\n"
    "   Keyframes are prefixed aim-*. Edit theme.css and re-run the generator. */\n\n"
)


def split_blocks(s):
    """Walk top-level CSS into comment / whitespace / at-statement / rule blocks."""
    blocks = []
    i, n = 0, len(s)
    while i < n:
        if s[i:i + 2] == '/*':
            j = s.find('*/', i + 2)
            j = n if j < 0 else j + 2
            blocks.append(('comment', s[i:j])); i = j; continue
        if s[i].isspace():
            j = i
            while j < n and s[j].isspace():
                j += 1
            blocks.append(('ws', s[i:j])); i = j; continue
        j = i
        while j < n and s[j] not in '{;':
            j += 1
        if j < n and s[j] == ';':
            blocks.append(('stmt', s[i:j + 1])); i = j + 1; continue
        prelude = s[i:j]
        depth, k = 0, j
        while k < n:
            if s[k] == '{':
                depth += 1
            elif s[k] == '}':
                depth -= 1
                if depth == 0:
                    k += 1; break
            k += 1
        blocks.append(('rule', prelude, s[j:k])); i = k
    return blocks


def prefix_selector(sel):
    sel = sel.strip()
    if not sel:
        return sel
    if sel == ':root':
        return '.aim'
    if sel in ('html', 'body'):
        return '.aim'
    if sel == '*':
        return '.aim *'
    return '.aim ' + sel


def prefix_selector_list(prelude):
    return ', '.join(prefix_selector(p) for p in prelude.split(','))


def transform(s):
    out = []
    for b in split_blocks(s):
        if b[0] in ('comment', 'ws', 'stmt'):
            out.append(b[1]); continue
        _, prelude, body = b
        p = prelude.strip()
        if p.startswith('@keyframes'):
            name = p.split()[1]
            out.append(prelude.replace(name, 'aim-' + name, 1) + body); continue
        if p.startswith(('@font-face', '@import', '@charset')):
            out.append(prelude + body); continue
        if p.startswith(('@media', '@supports')):
            inner = body[body.find('{') + 1:body.rfind('}')]
            out.append(prelude + '{' + transform(inner) + '}'); continue
        if p.startswith('@'):
            out.append(prelude + body); continue
        out.append(prefix_selector_list(prelude) + body)
    return ''.join(out)


def generate(css):
    kf = re.findall(r'@keyframes\s+([A-Za-z0-9_-]+)', css)
    scoped = transform(css)
    for name in kf:
        scoped = re.sub(
            r'(animation(?:-name)?\s*:[^;}]*?)\b' + re.escape(name) + r'\b',
            lambda m: m.group(0).replace(name, 'aim-' + name), scoped)
    return HEADER + scoped


def main(argv):
    here = os.path.dirname(os.path.abspath(__file__))
    src = argv[1] if len(argv) > 1 else os.path.join(here, 'frontend', 'theme.css')
    dst = argv[2] if len(argv) > 2 else os.path.join(here, 'frontend', 'theme.aim.css')
    with open(src, encoding='utf-8') as f:
        css = f.read()
    out = generate(css)
    with open(dst, 'w', encoding='utf-8', newline='') as f:
        f.write(out)
    print('generated %s (%d bytes) from %s' % (dst, len(out), src))


if __name__ == '__main__':
    main(sys.argv)
