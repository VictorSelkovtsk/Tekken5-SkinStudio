from pathlib import Path
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import time


def inspect(home, mod):
    home = Path(home).resolve()
    key = str(mod['id'])
    if not re.fullmatch(r'[0-9a-f]{16}', key):
        raise ValueError('ID do mod inválido para exclusão')
    root = home / 'mods'
    folder = root / key
    for path in (root, folder):
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('A pasta do mod contém um link ou junção; exclusão recusada')
    if root.resolve() != root or folder.resolve() != folder or home not in folder.resolve().parents:
        raise ValueError('A pasta do mod está fora do gerenciador')
    asset = Path(mod['asset']).resolve()
    if folder not in asset.parents:
        raise ValueError('O arquivo convertido está fora da pasta deste mod')
    if folder == Path(mod['source']).resolve() or folder in Path(mod['source']).resolve().parents:
        raise ValueError('O modelo de origem está na pasta do mod; mova-o antes de excluir')
    entries = []
    if folder.exists():
        if not folder.is_dir():
            raise ValueError('A pasta do mod não é um diretório')
        def scan_error(error):
            raise error
        for current, dirs, files in os.walk(folder, followlinks=False, onerror=scan_error):
            for name in sorted(dirs + files):
                path = Path(current) / name
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise ValueError('A pasta do mod contém um link ou junção; exclusão recusada')
                if folder not in path.resolve().parents:
                    raise ValueError('Arquivo fora da pasta do mod')
                entries.append((str(path.relative_to(folder)), info.st_size if path.is_file() else 0,
                                info.st_mtime_ns, path.is_file()))
    entries.sort()
    stamp = hashlib.sha256(repr((str(folder), entries)).encode('utf8')).hexdigest()
    return dict(id=key, name=mod['name'], folder=str(folder), stamp=stamp,
                files=sum(entry[3] for entry in entries), bytes=sum(entry[1] for entry in entries))


def delete(studio, mod, stamp):
    plan = inspect(studio.home, mod)
    if stamp != plan['stamp']:
        raise ValueError('Os arquivos mudaram. Abra Excluir novamente para conferir o tamanho atual.')
    folder = Path(plan['folder'])
    pending = folder.with_name('.deleting_' + mod['id'])
    if pending.exists():
        raise ValueError('Há uma exclusão anterior pendente: ' + str(pending))
    moved = folder.exists()
    if moved:
        folder.rename(pending)
    previous = studio.config['mods']
    studio.config['mods'] = [item for item in previous if item['id'] != mod['id']]
    try:
        studio.save()
    except Exception:
        studio.config['mods'] = previous
        if moved:
            pending.rename(folder)
        raise
    warning = None
    trash = None
    if moved:
        try:
            if pending.resolve().parent != folder.parent.resolve():
                raise ValueError('Destino de exclusão inválido')
            bin_dir = folder.parent / '.lixeira'
            bin_dir.mkdir(exist_ok=True)
            trash = bin_dir / (mod['id'] + '_' + time.strftime('%Y%m%d_%H%M%S'))
            pending.rename(trash)
        except (OSError, ValueError) as error:
            warning = 'Mod removido da lista, mas há arquivos que não puderam ser movidos para a lixeira em ' + str(pending) + ': ' + str(error)
    studio.files = {key: value for key, value in studio.files.items() if folder not in Path(value).parents}
    return dict(mods=studio.config['mods'], freed_bytes=0, trash=str(trash) if trash else None, warning=warning)


def recover(studio):
    root = Path(studio.home) / 'mods'
    known = {m['id'] for m in studio.config['mods']}
    added = []
    if not root.is_dir():
        return added
    for meta in sorted(root.glob('*/mod.json')):
        try:
            mod = json.loads(meta.read_text(encoding='utf8'))
        except (OSError, ValueError):
            continue
        if not re.fullmatch(r'[0-9a-f]{16}', str(mod.get('id', ''))) or mod['id'] in known or meta.parent.name != mod['id']:
            continue
        asset = Path(mod.get('asset', ''))
        if not asset.is_file():
            asset = meta.parent / asset.name
            if not asset.is_file():
                continue
        mod.update(asset=str(asset), enabled=False)
        studio.config['mods'].append(mod)
        known.add(mod['id'])
        added.append(mod['id'])
    if added:
        studio.save()
    return added


def update(studio, mod, convert, changes):
    folder = Path(inspect(studio.home, mod)['folder'])
    old = Path(mod['asset']).resolve()
    asset = folder/('skin_'+secrets.token_hex(4)+'.bin')
    try:
        report = convert(asset)
    except Exception:
        asset.unlink(missing_ok=True)
        raise
    entry = dict(mod, **changes, asset=report['asset'], report=report)
    index = studio.config['mods'].index(mod)
    studio.config['mods'][index] = entry
    try:
        studio.save()
    except Exception:
        studio.config['mods'][index] = mod
        asset.unlink(missing_ok=True)
        raise
    if old != asset.resolve() and old.parent == folder:
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass
    (folder/'mod.json').write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding='utf8')
    return entry
