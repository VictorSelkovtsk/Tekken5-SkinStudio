import json
import locale
from pathlib import Path

SOURCE = 'pt'
HERE = Path(__file__).resolve().parent / 'lang'


def folders(home):
    return [HERE, Path(home) / 'lang']


def available(home):
    out = {SOURCE: 'Português (Brasil)'}
    for folder in folders(home):
        if folder.is_dir():
            for f in sorted(folder.glob('*.json')):
                if f.stem.startswith('_'):
                    continue
                try:
                    out[f.stem] = json.loads(f.read_text(encoding='utf8')).get('_name', f.stem)
                except (OSError, ValueError):
                    pass
    return out


def system(home):
    try:
        import ctypes
        code = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), '')
    except Exception:
        code = locale.getlocale()[0] or ''
    code = code.lower()
    langs = available(home)
    for c in (code.replace('-', '_'), code[:2]):
        if c in langs:
            return c
    return SOURCE if code.startswith('pt') else ('en' if 'en' in langs else SOURCE)


def catalog(home, code):
    langs = available(home)
    code = code if code in langs else system(home)
    data = {}
    if code != SOURCE:
        for folder in folders(home):
            f = folder / (code + '.json')
            if f.is_file():
                try:
                    data.update(json.loads(f.read_text(encoding='utf8')))
                except (OSError, ValueError):
                    pass
    return dict(lang=code, catalog=data, languages=langs)


_state = {'lang': SOURCE, 'exact': {}, 'patterns': []}


def set_language(home, code=None):
    import re
    data = catalog(home, code or '')
    exact, patterns = {}, []
    slot = re.compile(r'\{(\d+)(?::[^}]*)?\}')
    for key, value in data['catalog'].items():
        if key == '_name' or not value or value == key:
            continue
        if not slot.search(key):
            exact[key] = value
            continue
        parts = slot.split(key)
        if not any(i % 2 == 0 and re.search(r'[A-Za-zÀ-ÿ]{3}', p) for i, p in enumerate(parts)):
            continue
        source, order = '^', []
        for i, p in enumerate(parts):
            if i % 2:
                order.append(int(p))
                source += r'([\s\S]*?)'
            else:
                source += re.escape(p)
        patterns.append((re.compile(source + '$'), order, value, len(slot.sub('', key))))
    patterns.sort(key=lambda p: -p[3])
    _state.update(lang=data['lang'], exact=exact, patterns=patterns, languages=data['languages'])
    return data['lang']


def language():
    return _state['lang']


def languages():
    return _state.get('languages', {SOURCE: 'Português (Brasil)'})


def _t(text, *args, **kw):
    out = _state['exact'].get(text, text)
    if args or kw:
        try:
            return out.format(*args, **kw)
        except (IndexError, KeyError, ValueError):
            return text.format(*args, **kw)
    return out


def tr(text):
    import re
    if not text or _state['lang'] == SOURCE:
        return text
    m = re.match(r'^(\s*)([\s\S]*?)(\s*)$', text)
    core = m.group(2)
    out = _state['exact'].get(core)
    if out is None:
        for pattern, order, value, _ in _state['patterns']:
            g = pattern.match(core)
            if not g:
                continue
            values = {n: tr(g.group(i + 1)) for i, n in enumerate(order)}
            out = re.sub(r'\{(\d+)(?::[^}]*)?\}', lambda x: values.get(int(x.group(1)), ''), value)
            break
    if out is None and ' · ' in core:
        parts = core.split(' · ')
        done = [tr(p) for p in parts]
        if done != parts:
            out = ' · '.join(done)
    return text if out is None else m.group(1) + out + m.group(3)
