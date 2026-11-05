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
