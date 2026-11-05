from pathlib import Path
import struct
from tools.stages.ps2gs import Memory
from .sources import worlds, REPO
import numpy as np


def read(path, cache=None):
    path = Path(path); data = path.read_bytes()
    if data[:8] != b'PS2TagA\0':
        raise ValueError('KMD não é um modelo de personagem do Tag HD')
    nmain, scale, extra, bone_end = struct.unpack_from('<IfII', data, 8)
    count = nmain + extra
    if not 0 < count < 256 or bone_end != 128 + count * 32:
        raise ValueError('Layout do esqueleto Tag HD desconhecido')
    bones = []
    for i in range(count):
        off = 124 + i * 32
        values = struct.unpack_from('<6f', data, off+4)
        bones.append({'name': 'Tag HD bone %d' % i, 'parent': struct.unpack_from('<i', data, off)[0],
                      'translation': list(values[:3]), 'rotation': list(values[3:])})
    matrices = worlds(bones)
    draws = []; strips = 0; palettes = 0
    for group, header_offset in enumerate((52, 72, 84, 92)):
        start = struct.unpack_from('<I', data, header_offset)[0]
        if not start:
            continue
        end = start + struct.unpack_from('<I', data, start+4)[0]
        if not bone_end <= start < end <= len(data):
            raise ValueError('Limites de geometria Tag HD não reconhecidos')
        p = start + 16; palette = None; tex0 = None
        while p < end:
            if p + 16 > end:
                raise ValueError('Comando KMD truncado')
            a, flag = struct.unpack_from('<2I', data, p)
            if a == 0 and flag == 0:
                p += 16
                continue
            if flag == 0 and 0 < a <= 256:
                if p+16+a*8 > end:
                    raise ValueError('Paleta Tag HD truncada')
                palette = [struct.unpack_from('<I', data, p+16+i*8)[0] for i in range(a)]
                if max(palette) >= count:
                    raise ValueError('Osso Tag HD fora do esqueleto')
                palettes += 1; p += 16+a*8; p = (p+15)//16*16; continue
            if flag == 0x20000000:
                p += 48; continue
            if flag == 0x10000000:
                tex0 = struct.unpack_from('<Q', data, p+16)[0]; p += 32; continue
            n = a & 32767
            if flag & 0xffdfffff != 0x310e4000 or not 3 <= n <= 255 or palette is None or tex0 is None:
                raise ValueError('Comando Tag HD desconhecido em 0x%x (%08x %08x)' % (p, a, flag))
            p += 16; positions = []; normals = []; weights = []; ids = []; uvs = []
            for _ in range(n):
                if p+32 > end:
                    raise ValueError('Vértice KMD truncado')
                uv = struct.unpack_from('<2f', data, p)
                nw = struct.unpack_from('<H', data, p+12)[0]
                if not 1 <= nw <= 4 or p+32+nw*32 > end:
                    raise ValueError('Influências Tag HD inválidas')
                local = [struct.unpack_from('<H', data, p+16+j*4)[0] for j in range(nw)]
                if min(local) < 1 or max(local) > len(palette):
                    raise ValueError('Índice local Tag HD fora da paleta em %x: %s / %s' % (p, local, palette))
                global_ids = [palette[i-1] for i in local]
                pos = np.zeros(3); normal = np.zeros(3); row = []
                for j, bone in enumerate(global_ids):
                    off = p+32+j*32
                    normal4 = np.array(struct.unpack_from('<4f', data, off))
                    position4 = np.array(struct.unpack_from('<4f', data, off+16))
                    pos += (matrices[bone] @ position4)[:3]
                    normal += (matrices[bone] @ normal4)[:3]
                    row.append(position4[3])
                p += 32+nw*32
                positions.append(pos); normals.append(normal / max(np.linalg.norm(normal), 1e-8))
                uvs.append(uv); weights.append(row+[0]*(4-nw)); ids.append(global_ids+[0]*(4-nw))
            faces = [(i-2, i-1, i) if i % 2 == 0 else (i-1, i-2, i) for i in range(2, n)]
            if a & 32768:
                faces = [(b, a, c) for a, b, c in faces]
            draw = {k: np.array(v, np.int32 if k == 'indices' else np.float32)
                    for k, v in [('positions', positions), ('normals', normals), ('uv0', uvs), ('weights', weights), ('indices', ids)]}
            draw.update(group=group, tex0=tex0, faces=np.array(faces, np.int32), name=path.stem+'_%016x'%tex0)
            draws.append(draw); strips += 1
    cache = Path(cache or REPO/'out/skins_t5/taghd') / path.stem
    cache.mkdir(parents=True, exist_ok=True)
    memory = Memory().load_ngi(path.with_suffix('.ngi').read_bytes())
    for tex in {d['tex0'] for d in draws}:
        file = cache / ('%016x.png' % tex)
        if not file.exists():
            memory.texture(tex).save(file)
        for d in draws:
            if d['tex0'] == tex:
                d['texture'] = str(file)
    return {'kind': 'taghd', 'name': path.stem, 'path': str(path), 'bones': bones, 'meshes': draws,
            'warnings': ['Tag HD: os quatro grupos nativos do corpo, pernas, olhos e cabelo são preservados.',
                         'Acessórios usam seus ancestrais animados; a física original do Tag HD não é transferida.',
                         'Rigs faciais reconhecidos são ligados aos controles T5; clipes originais do Tag HD não são importados. Confira o Teste facial e valide no jogo.',
                         'Remapeamento para T5 precisa ser revisado na prévia.'],
            'native': {'scale': scale, 'palettes': palettes, 'strips': strips}}
