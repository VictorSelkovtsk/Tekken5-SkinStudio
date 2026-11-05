import base64
import hashlib
import io
import struct
from pathlib import Path

import numpy as np
from PIL import Image

from tools.stages.container import pack, mif
from .anim64 import BodyBank, decode, is_short, quaternions
from .convert import skeleton
from .native import pictures, texture, packet_meshes
from .physics import physics
from .sources import worlds

TRACK_BONE = {2: 0, 3: 1, 4: 2, 7: 3, 8: 6, 5: 4, 9: 7, 10: 8, 11: 9, 12: 10, 13: 11, 14: 12, 15: 13, 16: 14,
              17: 15, 18: 16, 19: 17, 20: 18, 21: 19, 22: 20}
BANKS = (-9, -7, -5)
BANK_NAMES = ('Golpes', 'Golpes (variação)', 'Extra')


def resource(base):
    if not 0 <= int(base) < 79:
        raise ValueError('Roupa base inválida')
    return 240 + 11 * int(base)


def picture_table(bank):
    return dict(pictures(bank))


def costume_meshes(package):
    parts = pack(package)
    nud = parts[2]
    count = struct.unpack_from('<H', nud, 10)[0]
    names = mif(parts[4], count)
    merged = {}
    off = 32
    for obj in range(count):
        draws = struct.unpack_from('<H', nud, off + 4)[0]
        for j in range(draws):
            sub = off + 24 + 40 * j
            tid, gs, mat, flags, start = struct.unpack_from('<5I', nud, sub)
            size = struct.unpack_from('<H', nud, sub + 20)[0] * 16
            if start + size > len(nud):
                raise ValueError('Pacote NUDP truncado')
            for mesh in packet_meshes(nud[start:start + size], list(nud[sub + 30:sub + 40])):
                if not len(mesh['faces']):
                    continue
                key = (obj, tid)
                target = merged.setdefault(key, dict(name='%03d · %s' % (obj, names[obj][0]), texture=tid, object_id=obj,
                                                     positions=[], normals=[], uv0=[], weights=[], indices=[], faces=[]))
                base = sum(len(p) for p in target['positions'])
                target['faces'].append(mesh['faces'] + base)
                for field in ('positions', 'normals', 'uv0', 'weights', 'indices'):
                    target[field].append(mesh[field])
        off += 24 + 40 * draws
    meshes = []
    for m in merged.values():
        for field in ('positions', 'normals', 'uv0', 'weights', 'indices', 'faces'):
            m[field] = np.concatenate(m[field])
        meshes.append(m)
    return meshes


def texture_images(package, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    bank = pack(package)[1]
    out = {}
    for tid, info in picture_table(bank).items():
        path = folder / ('t5_%08x.png' % tid)
        if not path.exists():
            texture(bank, info).save(path)
        out[tid] = path
    return out


def preview(archive, base, home, register, overrides=None):
    package = archive.read(resource(base))
    digest = hashlib.sha256(package).hexdigest()[:16]
    images = texture_images(package, Path(home) / 'cache' / 't5' / digest)
    table = picture_table(pack(package)[1])
    target = skeleton(package)
    overrides = overrides or {}
    materials, result = {}, []
    for m in costume_meshes(package):
        tid = m['texture']
        key = 't5_%08x' % tid
        if key not in materials:
            info = table.get(tid, {})
            shown = overrides.get(key)
            url = register(game_preview(shown, info, Path(home) / 'cache' / 't5' / 'previews')) if shown else register(images.get(tid))
            materials[key] = dict(key=key, name='%s · %dx%d' % (key, info.get('width', 0), info.get('height', 0)),
                                  path=str(images.get(tid, '')), texture=shown or '', url=url, color='#ffffff',
                                  alpha='texture', native=dict(id=tid, width=info.get('width'), height=info.get('height'),
                                                               colors=info.get('colors'), kind=info.get('it')))
        result.append(dict(positions=m['positions'].round(4).ravel().tolist(), normals=m['normals'].round(4).ravel().tolist(),
                           uv=m['uv0'].round(7).ravel().tolist(), faces=m['faces'].ravel().tolist(),
                           weights=m['weights'].round(6).ravel().tolist(), sources=m['indices'].ravel().tolist(),
                           indices=m['indices'].ravel().tolist(), material=key))
    try:
        physics_note = physics(package, len(target))['note']
    except ValueError as error:
        physics_note = str(error)
    positions = worlds(target)[:, :3, 3]
    bones = [dict(id=i, name=b.get('label', b['name']), parent=b['parent'], position=pos.tolist(),
                  category=b.get('category', ''), native_objects=b.get('native_objects', []), evidence=b.get('evidence', ''),
                  physics=b.get('physics')) for i, (b, pos) in enumerate(zip(target, positions))]
    return dict(name='', kind='t5', meshes=result, materials=list(materials.values()),
                source_bones=[dict(id=b['id'], name=b['name'], target=b['id']) for b in bones], target_bones=bones,
                facial_available=False, triangles=sum(len(m['faces']) // 3 for m in result), warnings=[],
                physics_note=physics_note, base_index=int(base))


def _swizzle(palette):
    order = np.arange(256)
    return palette[(order & ~24) | ((order & 8) << 1) | ((order & 16) >> 1)]


def encode_picture(bank, info, image):
    w, h = info['width'], info['height']
    rgba = image.convert('RGBA')
    if rgba.size != (w, h):
        rgba = rgba.resize((w, h), Image.LANCZOS)
    offset = info['offset'] + info['header']
    if info['it'] in (4, 5):
        channels = {2: 3, 3: 4}.get(info['ct'] & 63)
        if channels is None:
            raise ValueError('Paleta TIM2 não suportada')
        colors = info['colors']
        pal_image = rgba.quantize(colors=colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        ids = np.asarray(pal_image, np.uint8).ravel()
        flat = (pal_image.getpalette('RGBA') or [])[:colors * 4]
        palette = np.zeros((colors, 4), np.uint8)
        palette[:len(flat) // 4] = np.asarray(flat, np.uint8).reshape(-1, 4)
        if channels == 4:
            palette[:, 3] = (palette[:, 3].astype(np.uint16) * 128 + 127) // 255
        if colors == 256 and not info['format'] & 1:
            palette = _swizzle(palette)
        if info['it'] == 5:
            pixels = ids.tobytes()
        else:
            pixels = (ids[0::2] & 15 | (ids[1::2] & 15) << 4).astype(np.uint8).tobytes()
        clut = palette[:, :channels].tobytes()
        if len(pixels) > info['pixels'] or len(clut) > colors * channels:
            raise ValueError('Textura maior que o espaço original')
        bank[offset:offset + len(pixels)] = pixels
        bank[offset + info['pixels']:offset + info['pixels'] + len(clut)] = clut
    elif info['it'] in (2, 3):
        data = np.asarray(rgba, np.uint8).copy()
        if info['it'] == 2:
            raw = data[:, :, :3].tobytes()
        else:
            data[:, :, 3] = (data[:, :, 3].astype(np.uint16) * 128 + 127) // 255
            raw = data.tobytes()
        bank[offset:offset + len(raw)] = raw
    else:
        raise ValueError('Formato TIM2 não suportado: ' + str(info['it']))


def game_preview(path, info, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stat = Path(path).stat()
    key = hashlib.sha256(repr((str(Path(path).resolve()), stat.st_mtime_ns, sorted(info.items()))).encode()).hexdigest()[:20]
    out = folder / (key + '.png')
    if not out.exists():
        bank = bytearray(info['offset'] + info['header'] + info['pixels'] + info.get('colors', 0) * 4 + 16)
        local = dict(info, offset=0)
        with Image.open(path) as image:
            encode_picture(bank, local, image)
        texture(bytes(bank), local).save(out)
    return out


def texture_package(package, images):
    data = bytearray(package)
    count = struct.unpack_from('<I', data)[0]
    if count < 2:
        raise ValueError('Pacote sem banco de texturas')
    start, size = struct.unpack_from('<2I', data, 4 + 8)
    bank = bytearray(data[start:start + size])
    table = picture_table(bytes(bank))
    for tid, path in images.items():
        if tid not in table:
            raise ValueError('Textura %08x não existe nesta roupa' % tid)
        with Image.open(path) as image:
            encode_picture(bank, table[tid], image)
    if len(bank) != size:
        raise ValueError('O banco de texturas mudou de tamanho')
    data[start:start + size] = bank
    if pack(bytes(data))[1] != bytes(bank):
        raise ValueError('Falha ao regravar o banco de texturas')
    return bytes(data)


def banks(archive, base):
    out = []
    for n, delta in enumerate(BANKS):
        try:
            bank = BodyBank(pack(archive.read(resource(base) + delta))[0])
        except (ValueError, struct.error):
            continue
        out.append(dict(bank=n, name=BANK_NAMES[n], clips=[bank.duration(i) for i in range(len(bank))]))
    return out


def _euler(r):
    x, y, z = r
    cx, cy, cz = np.cos([x, y, z]); sx, sy, sz = np.sin([x, y, z])
    return np.array([[cy*cz, sx*sy*cz-cx*sz, cx*sy*cz+sx*sz], [cy*sz, sx*sy*sz+cx*cz, cx*sy*sz-sx*cz], [-sy, sx*cy, cx*cy]])


def _matrices(q):
    x, y, z, w = np.moveaxis(q, -1, 0)
    return np.stack([np.stack([1-2*(y*y+z*z), 2*(x*y+z*w), 2*(x*z-y*w)], -1),
                     np.stack([2*(x*y-z*w), 1-2*(x*x+z*z), 2*(y*z+x*w)], -1),
                     np.stack([2*(x*z+y*w), 2*(y*z-x*w), 1-2*(x*x+y*y)], -1)], -2)


def clip_transforms(archive, base, bank, clip, root_motion=False):
    out = clip_skin(archive, base, bank, clip, root_motion)
    count, n = out.shape[:2]
    return dict(frames=count, bones=n, fps=60, data=base64.b64encode(out.astype('<f4').tobytes()).decode('ascii'))


HELPER_FOLLOW = 1.0


def _followers(bones, driven):
    out = {}
    for i, b in enumerate(bones):
        if i in driven or b.get('physics'):
            continue
        for d in driven:
            o = bones[d]
            if o['parent'] == b['parent'] and np.linalg.norm(np.subtract(o['translation'], b['translation'])) < 3.0:
                out[i] = d
                break
    return out


def _segment_helpers(bones, driven, skip):
    rest = worlds(bones)[:, :3, 3]
    n = len(bones)
    kids = {}
    for i, b in enumerate(bones):
        kids.setdefault(b['parent'], []).append(i)
    segments = {}
    for d in driven:
        for c in kids.get(d, []):
            if c in driven and np.linalg.norm(rest[c] - rest[d]) > 1.0:
                segments[d] = c
                break

    def below(p):
        out, stack = [], list(kids.get(p, []))
        while stack:
            k = stack.pop()
            if k in driven:
                out.append(k)
                stack.extend(kids.get(k, []))
        return out
    out = {}
    for h, b in enumerate(bones):
        if h in driven or h in skip or b.get('physics') or not 0 <= b['parent'] < n:
            continue
        best = None
        for d in below(b['parent']):
            if d not in segments:
                continue
            a, e = rest[d], rest[segments[d]]
            v = e - a
            length = np.linalg.norm(v)
            t = float(np.dot(rest[h] - a, v) / (length * length))
            gap = np.linalg.norm(rest[h] - (a + np.clip(t, 0, 1) * v))
            if -0.02 <= t <= 1.02 and gap < max(6.0, 0.08 * length):
                rank = (t > 0.95, t)
                if best is None or rank < best[0]:
                    best = (rank, d)
        if best is not None:
            d, t = best[1], best[0][1]
            up = bones[d]['parent']
            joint = t < 0.05 and segments.get(up) == d and up in driven and up != b['parent']
            out[h] = (d, up if joint else None)
    return out


def _scale_rotation(R, s):
    if s == 1.0:
        return R
    tr = np.clip((np.trace(R, axis1=-2, axis2=-1) - 1) / 2, -1, 1)
    angle = np.arccos(tr)
    axis = np.stack([R[..., 2, 1] - R[..., 1, 2], R[..., 0, 2] - R[..., 2, 0], R[..., 1, 0] - R[..., 0, 1]], -1)
    norm = np.linalg.norm(axis, axis=-1, keepdims=True)
    axis = np.where(norm > 1e-9, axis / np.maximum(norm, 1e-9), [1.0, 0.0, 0.0])
    a = angle * s
    x, y, z = axis[..., 0], axis[..., 1], axis[..., 2]
    c, sn, t = np.cos(a), np.sin(a), 1 - np.cos(a)
    return np.stack([np.stack([c + x * x * t, x * y * t - z * sn, x * z * t + y * sn], -1),
                     np.stack([y * x * t + z * sn, c + y * y * t, y * z * t - x * sn], -1),
                     np.stack([z * x * t - y * sn, z * y * t + x * sn, c + z * z * t], -1)], -2)


def clip_skin(archive, base, bank, clip, root_motion=False):
    package = archive.read(resource(base))
    bones = skeleton(package)
    data = BodyBank(pack(archive.read(resource(base) + BANKS[int(bank)]))[0])
    if not 0 <= int(clip) < len(data):
        raise ValueError('Animação inexistente')
    frames = decode(data.clip(int(clip)))
    q = quaternions(frames, data.types)
    local = _matrices(q)
    n = len(bones)
    rest = worlds(bones)
    inv = np.linalg.inv(rest)
    count = len(frames)
    world = np.zeros((count, n, 4, 4))
    driven = {b: t for t, b in TRACK_BONE.items() if is_short(data.types[t])}
    follow = _followers(bones, driven)
    attach = _segment_helpers(bones, driven, follow)
    order, seen = [], set()

    def visit(i):
        if i in seen:
            return
        seen.add(i)
        p = bones[i]['parent']
        if 0 <= p < n:
            visit(p)
        if i in attach:
            visit(attach[i][0])
        order.append(i)
    for i in range(n):
        visit(i)
    for i in order:
        b = bones[i]
        if i in attach:
            d, up = attach[i]
            world[:, i] = world[:, d] @ (inv[d] @ rest[i])
            if up is not None:
                other = (world[:, up] @ (inv[up] @ rest[i]))[:, :3, :3]
                mine = world[:, i, :3, :3]
                world[:, i, :3, :3] = other @ _scale_rotation(np.swapaxes(other, -1, -2) @ mine, 0.5)
            continue
        m = np.tile(np.eye(4), (count, 1, 1))
        if i in driven:
            m[:, :3, :3] = local[:, driven[i]]
        elif i in follow:
            src = follow[i]
            delta = local[:, driven[src]] @ _euler(bones[src]['rotation']).T
            m[:, :3, :3] = _scale_rotation(delta, HELPER_FOLLOW) @ _euler(b['rotation'])
        else:
            m[:, :3, :3] = _euler(b['rotation'])
        m[:, :3, 3] = b['translation']
        if i == 0:
            m[:, :3, 3] = q[:, 1, :3] + (q[:, 0, :3] if root_motion else 0)
        p = b['parent']
        world[:, i] = world[:, p] @ m if 0 <= p < n else m
    skin = world @ inv
    return np.concatenate([skin[:, :, :3, :3].reshape(count, n, 9), skin[:, :, :3, 3]], -1).astype(np.float32)
