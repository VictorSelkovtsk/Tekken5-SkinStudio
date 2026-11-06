from pathlib import Path
import datetime
import hashlib
import io
import json
import re
import secrets
import zipfile

from tools.stages.container import pack
from .convert import MAX_PACKAGE, skeleton
from .game import catalogue
from . import original

FORMAT = 'T5SkinStudioMod1'
GAME = 'SLUS-21059'
MAX_FILE = 24 * 1024 * 1024
MAX_IMAGE = 4 * 1024 * 1024
MAX_TEXTURES = 64
TEXTURE_NAME = re.compile(r'textures/(t5_[0-9a-f]{8})\.png')


def _bones(package):
    return [(b['parent'], tuple(round(v, 3) for v in b['translation'])) for b in skeleton(package)]


def export(studio, mod, destination, version=''):
    destination = Path(destination)
    if destination.suffix.lower() != '.t5mod':
        destination = destination.with_suffix('.t5mod')
    chars, _ = catalogue(studio.game())
    owner = next((c for c in chars if c['id'] == mod['character']), None)
    manifest = dict(format=FORMAT, game=GAME, studio=version, name=mod['name'], character=mod['character'],
                    character_name=owner['name'] if owner else '', base_index=int(mod['base_index']), mode=mod['mode'],
                    created=datetime.datetime.now().strftime('%Y-%m-%d'))
    files = {}
    if mod.get('kind') == 'textures':
        manifest['kind'] = 'textures'
        manifest['textures'] = {}
        for material, path in sorted(mod.get('settings', {}).get('textures', {}).items()):
            if not re.fullmatch(r't5_[0-9a-f]{8}', material):
                raise ValueError('Textura do mod com nome inválido: ' + material)
            from PIL import Image
            buffer = io.BytesIO()
            with Image.open(path) as image:
                image.convert('RGBA').save(buffer, format='PNG')
            name = 'textures/%s.png' % material
            files[name] = buffer.getvalue()
            manifest['textures'][material] = name
        if not files:
            raise ValueError('Este mod não tem texturas para exportar')
    else:
        data = Path(mod['asset']).read_bytes()
        manifest.update(kind='skin', package='skin.bin', sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
                        triangles=int(mod.get('report', {}).get('triangles', 0)))
        files['skin.bin'] = data
    temp = destination.with_name(destination.name + '.tmp')
    with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('mod.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        for name, data in files.items():
            archive.writestr(name, data)
    temp.replace(destination)
    return dict(path=str(destination), bytes=destination.stat().st_size, kind=manifest['kind'])


def _read(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError('Arquivo de mod não encontrado: ' + str(path))
    if path.stat().st_size > MAX_FILE:
        raise ValueError('Arquivo de mod grande demais')
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ValueError('Este arquivo não é um mod do Tekken 5 Skin Studio (.t5mod)') from None
    with archive:
        members = {}
        total = 0
        for info in archive.infolist():
            name = info.filename
            if info.is_dir():
                continue
            if name != 'mod.json' and name != 'skin.bin' and not TEXTURE_NAME.fullmatch(name):
                raise ValueError('Arquivo inesperado dentro do mod: ' + name)
            if name in members:
                raise ValueError('Arquivo repetido dentro do mod: ' + name)
            limit = 256 * 1024 if name == 'mod.json' else MAX_PACKAGE if name == 'skin.bin' else MAX_IMAGE
            if info.file_size > limit:
                raise ValueError('Arquivo grande demais dentro do mod: ' + name)
            total += info.file_size
            if total > 4 * MAX_FILE or len(members) > MAX_TEXTURES + 2:
                raise ValueError('Conteúdo do mod grande demais')
            data = archive.read(info)
            if len(data) != info.file_size:
                raise ValueError('Arquivo corrompido dentro do mod: ' + name)
            members[name] = data
    if 'mod.json' not in members:
        raise ValueError('Este arquivo não é um mod do Tekken 5 Skin Studio (.t5mod)')
    try:
        manifest = json.loads(members['mod.json'].decode('utf8'))
    except (UnicodeDecodeError, ValueError):
        raise ValueError('Descrição do mod ilegível') from None
    if not isinstance(manifest, dict) or manifest.get('format') != FORMAT:
        raise ValueError('Este arquivo não é um mod do Tekken 5 Skin Studio (.t5mod)')
    if manifest.get('game') != GAME:
        raise ValueError('Este mod foi feito para outra versão do jogo')
    return manifest, members


def inspect(studio, path):
    manifest, members = _read(path)
    game = studio.game()
    chars, _ = catalogue(game)
    try:
        base = int(manifest['base_index'])
        char = int(manifest['character'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('Descrição do mod incompleta') from None
    owner = next((c for c in chars if c['id'] == char), None)
    if owner is None or base not in [s['index'] for s in owner['slots']]:
        raise ValueError('A roupa base do mod não pertence ao personagem indicado')
    mode = manifest.get('mode')
    kind = manifest.get('kind')
    if mode not in ('replace', 'add') or kind not in ('skin', 'textures') or (kind == 'textures' and mode != 'replace'):
        raise ValueError('Descrição do mod incompleta')
    name = re.sub(r'[\x00-\x1f]', '', str(manifest.get('name') or '')).strip()[:100] or 'Mod importado'
    base_package = game.read(original.resource(base))
    images = {}
    if kind == 'skin':
        data = members.get('skin.bin')
        if data is None:
            raise ValueError('O mod não contém a skin')
        if hashlib.sha256(data).hexdigest() != manifest.get('sha256'):
            raise ValueError('A skin do mod está corrompida')
        if len(data) % 4 or len(data) > MAX_PACKAGE:
            raise ValueError('A skin do mod não cabe na memória do PS2')
        try:
            parts = pack(data)
            same = _bones(data) == _bones(base_package)
            meshes = original.costume_meshes(data)
        except Exception:
            raise ValueError('A skin do mod não é uma roupa válida do Tekken 5') from None
        if len(parts) != len(pack(base_package)) or not same or not meshes:
            raise ValueError('A skin do mod não combina com o esqueleto da roupa base')
        package = data
    else:
        from PIL import Image
        table = original.picture_table(pack(base_package)[1])
        listed = manifest.get('textures')
        if not isinstance(listed, dict) or not listed or len(listed) > MAX_TEXTURES:
            raise ValueError('O mod não contém texturas')
        for material, member in listed.items():
            match = TEXTURE_NAME.fullmatch(str(member))
            if not match or match.group(1) != material or member not in members:
                raise ValueError('Textura do mod com nome inválido: ' + str(material))
            tid = int(material[3:], 16)
            if tid not in table:
                raise ValueError('O mod troca uma textura que esta roupa não tem: ' + material)
            try:
                with Image.open(io.BytesIO(members[member])) as image:
                    if image.width > 2048 or image.height > 2048:
                        raise ValueError
                    image.load()
            except Exception:
                raise ValueError('Imagem inválida dentro do mod: ' + material) from None
            images[material] = members[member]
        package = None
    return dict(manifest=manifest, name=name, kind=kind, character=char, character_name=owner['name'],
                base_index=base, mode=mode, package=package, images=images,
                slot=next(s['label'] for s in owner['slots'] if s['index'] == base))


def install(studio, path):
    info = inspect(studio, path)
    key = secrets.token_hex(8)
    folder = studio.home / 'mods' / key
    folder.mkdir(parents=True)
    if info['kind'] == 'skin':
        asset = folder / 'skin.bin'
        asset.write_bytes(info['package'])
        report = dict(asset=str(asset), bytes=len(info['package']),
                      triangles=int(info['manifest'].get('triangles', 0) or 0))
        mod = dict(id=key, name=info['name'], kind='imported', source='', character=info['character'],
                   base_index=info['base_index'], mode=info['mode'], asset=str(asset), settings={}, report=report)
    else:
        keep = folder / 'textures'
        keep.mkdir()
        stored = {}
        for material, data in info['images'].items():
            file = keep / (material + '.png')
            file.write_bytes(data)
            stored[material] = str(file)
        package = studio.game().read(original.resource(info['base_index']))
        asset = folder / ('textures_' + secrets.token_hex(4) + '.bin')
        asset.write_bytes(original.texture_package(package, {int(m[3:], 16): p for m, p in stored.items()}))
        report = dict(asset=str(asset), bytes=asset.stat().st_size, triangles=0, textures=len(stored))
        mod = dict(id=key, name=info['name'], kind='textures', source=str(studio.config['iso']), character=info['character'],
                   base_index=info['base_index'], mode='replace', asset=str(asset), settings=dict(textures=stored), report=report)
    mod['imported'] = Path(path).name
    mod['enabled'] = not _conflict(studio, mod)
    (folder / 'mod.json').write_text(json.dumps(mod, ensure_ascii=False, indent=2), encoding='utf8')
    studio.config['mods'].append(mod)
    studio.save()
    return dict(mod, conflict=not mod['enabled'], character_name=info['character_name'], slot=info['slot'])


def _conflict(studio, mod):
    others = [m for m in studio.config['mods'] if m['enabled']]
    if mod['mode'] == 'replace':
        return any(m['mode'] == 'replace' and m['base_index'] == mod['base_index'] for m in others)
    chars, _ = catalogue(studio.game())
    owner = next(c for c in chars if c['id'] == mod['character'])
    extra = sum(m['mode'] == 'add' and m['character'] == mod['character'] for m in others)
    return not owner['can_add'] or len(owner['slots']) + extra >= 5
