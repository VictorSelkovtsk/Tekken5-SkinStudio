from pathlib import Path
import sys
import io
import hashlib
import json
import ntpath
import struct
import numpy as np
from tools.stages.container import pack

REPO = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]


def worlds(bones):
    result = [None] * len(bones)
    visiting = set()
    def resolve(i):
        if result[i] is not None:
            return result[i]
        if i in visiting:
            raise ValueError('Hierarquia de ossos cíclica')
        visiting.add(i)
        bone = bones[i]
        parent = bone['parent']
        if parent < -1 or parent >= len(bones) or parent == i:
            raise ValueError('Pai de osso inválido')
        x, y, z = bone.get('rotation', (0, 0, 0))
        cx, cy, cz = np.cos([x, y, z]); sx, sy, sz = np.sin([x, y, z])
        m = np.eye(4)
        m[:3, :3] = [[cy*cz, sx*sy*cz-cx*sz, cx*sy*cz+sx*sz],
                         [cy*sz, sx*sy*sz+cx*cz, cx*sy*sz-sx*cz],
                         [-sy, sx*cy, cx*cy]]
        m[:3, 3] = bone['translation']
        result[i] = resolve(parent) @ m if parent >= 0 else m
        visiting.remove(i)
        return result[i]
    for i in range(len(bones)):
        resolve(i)
    return np.asarray(result)


def checked(source):
    bones = source['bones']
    if not 0 < len(bones) <= 4096:
        raise ValueError('O modelo precisa de um esqueleto com até 4096 ossos')
    if not np.isfinite(worlds(bones)).all():
        raise ValueError('Transformação de osso não finita')
    if not source['meshes']:
        raise ValueError('Modelo sem malhas')
    for m in source['meshes']:
        n = len(m['positions'])
        if not n or n > 2000000:
            raise ValueError('Quantidade de vértices inválida')
        for key, width in [('positions', 3), ('normals', 3), ('uv0', 2), ('weights', 4), ('indices', 4)]:
            a = np.asarray(m[key])
            if a.shape != (n, width) or not np.isfinite(a).all():
                raise ValueError('Stream inválido: ' + key)
        if (m['weights'] < 0).any() or not np.allclose(m['weights'].sum(1), 1, atol=.003):
            raise ValueError('Pesos negativos, vazios ou não normalizados')
        ids = m['indices'][m['weights'] > 0]
        if ids.min(initial=0) < 0 or ids.max(initial=0) >= len(bones):
            raise ValueError('Índice de osso fora do esqueleto')
        f = m['faces']
        if f.ndim != 2 or f.shape[1] != 3 or not len(f) or f.min() < 0 or f.max() >= n:
            raise ValueError('Índices de faces inválidos')
    return source


T4_COSTUMES = (
    (322, 'Paul', 1), (328, 'Paul', 2), (346, 'Law', 1), (352, 'Law', 2), (370, 'Lei', 1), (376, 'Lei', 2),
    (394, 'King', 1), (400, 'King', 2), (418, 'Yoshimitsu', 1), (424, 'Yoshimitsu', 2), (442, 'Nina', 1),
    (448, 'Nina', 2), (466, 'Hwoarang', 1), (472, 'Hwoarang', 2), (490, 'Xiaoyu', 1), (496, 'Xiaoyu', 2),
    (502, 'Xiaoyu', 3), (508, 'Miharu', 1), (514, 'Christie', 1), (520, 'Christie', 2), (526, 'Eddy', 1),
    (538, 'Jin', 1), (544, 'Jin', 2), (556, 'Jin', 3), (568, 'Julia', 1), (562, 'Julia', 2), (586, 'Kuma', 1),
    (592, 'Panda', 1), (610, 'Bryan', 1), (616, 'Bryan', 2), (634, 'Heihachi', 1), (640, 'Heihachi', 2),
    (658, 'Kazuya', 1), (664, 'Kazuya', 2), (682, 'Violet', 1), (688, 'Violet', 2), (694, 'Lee', 1),
    (700, 'Lee', 2), (706, 'Steve', 1), (712, 'Steve', 2), (730, 'Marduk', 1), (736, 'Marduk', 2),
    (754, 'Combot', 1), (760, 'Combot', 2))


def t4_name(resource):
    for r, name, n in T4_COSTUMES:
        if r == resource:
            return '%s · Tekken 4 · %d' % (name, n)
    return 'Tekken 4 · %d' % resource


def t4_library():
    return [dict(path='t4:%d:0' % r, name='%s · T4 · %d' % (name, n), kind='t4', thumbnail=None)
            for r, name, n in T4_COSTUMES]


def open_t4(iso):
    from tools.stages.tekken4 import Archive
    if not str(iso or '').strip():
        raise ValueError('Escolha a ISO do Tekken 4 em Pastas e jogo')
    if not Path(iso).is_file():
        raise ValueError('ISO do Tekken 4 não encontrada: ' + str(iso))
    try:
        return Archive(iso)
    except (ValueError, KeyError, struct.error, OSError):
        raise ValueError('Esta ISO não é o Tekken 4 USA (SLUS-20328) original. Use a ISO original, sem modificações.') from None


def t4_iso(spec, iso, cache=None):
    from tools.stages.tekken4 import character_draws
    from tools.stages.ps2gs import Memory
    from PIL import Image
    try:
        _, resource, part = str(spec).split(':')
        resource, part = int(resource), int(part)
    except ValueError:
        raise ValueError('Modelo do Tekken 4 inválido: ' + str(spec)) from None
    if not 0 <= part < 3:
        raise ValueError('Modelo do Tekken 4 inválido: ' + str(spec))
    raw = open_t4(iso).read(resource)
    parts = pack(raw)
    if len(parts) < part + 4 or not parts[part + 3].startswith(b'CHRTK4'):
        raise ValueError('Recurso %d não é um modelo de personagem do Tekken 4' % resource)
    draws, bones = character_draws(parts[part + 3])
    for i, b in enumerate(bones):
        b['name'] = 'T4 bone %d' % i
    bank = parts[part]
    root = Path(cache or REPO / 'cache' / 't4')
    folder = root / hashlib.sha256(bank).hexdigest()[:24]
    folder.mkdir(parents=True, exist_ok=True)
    memory = None
    textures = {}
    for d in draws:
        tex0 = d['tex0']
        if tex0 not in textures:
            file = folder / ('%016x.png' % tex0)
            if not file.is_file():
                if memory is None:
                    memory = Memory().load_ngi(bank)
                memory.texture(tex0).save(file, format='PNG')
            with Image.open(file) as image:
                alpha = image.convert('RGBA').getextrema()[3][0] < 255
            textures[tex0] = (str(file), alpha)
        d['texture'], alpha = textures[tex0]
        d['alpha'] = 'texture' if alpha else 'opaque'
        d['name'] = 'T4_%d_%016x' % (resource, tex0)
    warnings = []
    from .cloth import append_cloth
    cloth_faces = append_cloth(raw, draws, root / 'cloth')
    if cloth_faces:
        warnings.append('Tecido CLT recuperado: %d triângulos. Pesos iniciais transferidos do corpo para edição; a simulação física T4 não foi convertida.' % cloth_faces)
    return checked({'kind': 't4', 'name': t4_name(resource), 'path': '%s' % spec,
                    'bones': bones, 'meshes': draws, 'warnings': warnings})


def t4(path, cache=None):
    from tools.stages.tekken4 import character_draws
    path = Path(path)
    manifest = json.loads(path.read_text(encoding='utf8'))
    if manifest.get('skin_weight_mapping') != 'CHRTK4_DMA_palette_v2':
        raise ValueError('Exportação T4 antiga: reextraia com os pesos DMA corrigidos')
    raw = (path.parent / 'native_package.bin').read_bytes()
    warnings = []
    record = manifest.get('resources', [{}])[0]
    if record.get('sha256') and hashlib.sha256(raw).hexdigest() != record['sha256']:
        from tools.stages.tekken4 import Archive
        raw = Archive(record['iso']).read(record['catalog_id'])
        if hashlib.sha256(raw).hexdigest() != record['sha256']:
            raise ValueError('A origem T4 difere do manifesto de exportação')
        warnings.append('Pacote do export divergente: modelo relido da ISO T4 original verificada.')
    part = manifest['native_model_part'] + 3
    count = struct.unpack_from('<I', raw)[0]
    if not 0 <= part < count or 4+8*count > len(raw):
        raise ValueError('Tabela de partes T4 inválida')
    offset, size = struct.unpack_from('<II', raw, 4+part*8)
    if offset < 4+8*count or offset+size > len(raw):
        raise ValueError('Modelo CHRTK4 truncado')
    draws, bones = character_draws(raw[offset:offset+size])
    for i, b in enumerate(bones):
        b['name'] = 'T4 bone %d' % i
    from PIL import Image
    textures = {}; memory = None; recovered = 0
    for d in draws:
        key = manifest['name'] + '_%016x' % d['tex0']
        if key not in textures:
            entry = manifest['textures'][key]
            texture = Path(entry['file'])
            try:
                with Image.open(texture) as image:
                    image.load()
                    if image.size != (entry['width'],entry['height']):
                        raise ValueError('Dimensões divergentes do atlas T4')
            except (OSError, ValueError):
                if memory is None:
                    from tools.stages.ps2gs import Memory
                    bank_index = int(manifest['native_model_part'])
                    if not 0 <= bank_index < count: raise ValueError('Banco de texturas T4 inválido')
                    bank_offset, bank_size = struct.unpack_from('<II', raw, 4+bank_index*8)
                    if bank_offset < 4+8*count or bank_offset+bank_size > len(raw):
                        raise ValueError('Banco de texturas T4 truncado')
                    bank = raw[bank_offset:bank_offset+bank_size]
                    memory = Memory().load_ngi(bank)
                    bank_hash = hashlib.sha256(bank).hexdigest()[:24]
                folder = Path(cache or REPO/'out/skins_t5/t4_textures') / bank_hash
                folder.mkdir(parents=True, exist_ok=True)
                texture = folder/('%016x.png' % d['tex0'])
                memory.texture(d['tex0']).save(texture, format='PNG')
                recovered += 1
            textures[key] = str(texture)
        d['texture'] = textures[key]
        d['alpha'] = 'texture' if manifest['textures'][key].get('has_alpha') else 'opaque'
        d['name'] = key
    if recovered:
        warnings.append('%d texturas ausentes ou danificadas recuperadas do banco original T4.' % recovered)
    from .cloth import append_cloth
    cloth_faces=append_cloth(raw,draws,Path(cache or REPO/'out/skins_t5/t4_textures')/'cloth')
    if cloth_faces:
        warnings.append('Tecido CLT recuperado: %d triângulos. Pesos iniciais transferidos do corpo para edição; a simulação física T4 não foi convertida.' % cloth_faces)
    name = 'Julia · Tekken 4 · 1P' if manifest['name'] == 'Character_0568_0' else manifest['name']
    return checked({'kind': 't4', 'name': name, 'path': str(path),
                    'bones': bones, 'meshes': draws, 'warnings': warnings})


class Binary:
    def __init__(self, data):
        self.data, self.pos = data, 0
    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise ValueError('Arquivo XPS truncado em 0x%x' % self.pos)
        out = self.data[self.pos:self.pos+n]; self.pos += n
        return out
    def values(self, fmt):
        return struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))
    def number(self, fmt='I', maximum=None):
        n = self.values(fmt)[0]
        if maximum is not None and not 0 <= n <= maximum:
            raise ValueError('Contagem XPS fora do limite: ' + str(n))
        return n
    def string(self):
        a = self.number('B')
        length = (a & 127) + (self.number('B') * 128 if a >= 128 else 0)
        return self.take(length).decode('utf-8-sig')


def influence(ids, weights, bone_count):
    if len(ids) != len(weights) or not ids:
        raise ValueError('Vértice sem influências válidas')
    sums = {}
    for i, w in zip(ids, weights):
        if not np.isfinite(w) or w < 0 or (w > 0 and not 0 <= i < bone_count):
            raise ValueError('Influência XPS inválida')
        if w:
            sums[i] = sums.get(i, 0) + w
    ranked = sorted(sums.items(), key=lambda x: -x[1])
    total = sum(w for _, w in ranked)
    if total <= 1e-8:
        raise ValueError('Vértice sem pesos')
    discarded = sum(w for _, w in ranked[4:]) / total
    ranked = ranked[:4]; kept = sum(w for _, w in ranked)
    return ([i for i, _ in ranked] + [0]*4)[:4], ([w/kept for _, w in ranked] + [0]*4)[:4], discarded


def xps(path):
    path = Path(path); raw = path.read_bytes()
    warnings = []; bones = []; meshes = []; dropped = 0.
    ascii_format = path.name.lower().endswith(('.ascii', '.mesh.ascii'))
    if ascii_format:
        lines = iter(raw.decode('utf-8-sig').splitlines())
        def line():
            try:
                return next(lines).split('#', 1)[0].strip()
            except StopIteration:
                raise ValueError('Arquivo XPS ASCII truncado') from None
        def count(maximum):
            n = int(line())
            if not 0 <= n <= maximum:
                raise ValueError('Contagem XPS ASCII fora do limite')
            return n
        def vector(n, cast=float):
            v = list(map(cast, line().split()))
            if n is not None and len(v) != n:
                raise ValueError('Linha XPS ASCII com quantidade incorreta de valores')
            return v
        bone_count = count(4096)
        for i in range(bone_count):
            bones.append({'name': line(), 'parent': int(line()), 'world': vector(3)})
        mesh_count = count(10000)
    else:
        r = Binary(raw); major = minor = 0; header = False
        if r.values('I')[0] == 323232:
            header = True; major, minor = r.values('2H')
            if major not in (1, 2, 3):
                raise ValueError('Versão XPS não suportada: %d.%d' % (major, minor))
            r.string(); settings = r.number(maximum=1000000)
            r.string(); r.string(); r.string()
            r.take(settings * 4)
        else:
            r.pos = 0
        tangent = not header or (major <= 2 and minor <= 12)
        variable = header and major >= 3
        bone_count = r.number(maximum=4096)
        for i in range(bone_count):
            bones.append({'name': r.string(), 'parent': r.number('h'), 'world': list(r.values('3f'))})
        mesh_count = r.number(maximum=10000)
    if not bone_count:
        raise ValueError('Modelo XPS sem ossos: é necessário rig antes da importação')
    for i, b in enumerate(bones):
        p = b['parent']
        if p < -1 or p >= bone_count or p == i:
            raise ValueError('Pai de osso XPS inválido')
        b['translation'] = (np.array(b['world']) - (np.array(bones[p]['world']) if p >= 0 else 0)).tolist()
        b['rotation'] = [0, 0, 0]
    for _ in range(mesh_count):
        name = line() if ascii_format else r.string()
        uv_count = count(8) if ascii_format else r.number(maximum=8)
        nt = count(32) if ascii_format else r.number(maximum=32)
        textures = []
        for _ in range(nt):
            filename = line() if ascii_format else r.string()
            layer = int(line()) if ascii_format else r.number()
            if not 0 <= layer < uv_count:
                raise ValueError('Textura referencia canal UV inexistente')
            textures.append((filename, layer))
        texture = None; layer = textures[0][1] if textures else 0
        if textures:
            filename = textures[0][0]
            candidate = path.parent / filename.replace('\\', '/')
            if not candidate.is_file():
                candidate = path.parent / ntpath.basename(filename)
            if candidate.is_file():
                texture = str(candidate.resolve())
            else:
                warnings.append('Textura não encontrada: ' + filename)
        n = count(2000000) if ascii_format else r.number(maximum=2000000)
        fields = {k: [] for k in ('positions', 'normals', 'uv0', 'indices', 'weights')}
        for _ in range(n):
            if ascii_format:
                pos, normal = vector(3), vector(3); vector(4, int)
                uvs = [vector(2) for _ in range(uv_count)]
                ids, weights = vector(None, int), vector(None)
            else:
                pos, normal = r.values('3f'), r.values('3f'); r.take(4)
                uvs = []
                for _ in range(uv_count):
                    uvs.append(r.values('2f'))
                    if tangent:
                        r.take(16)
                nw = r.number('h', 256) if variable else 4
                ids, weights = r.values(str(nw)+'h'), r.values(str(nw)+'f')
            ids, weights, loss = influence(ids, weights, bone_count); dropped = max(dropped, loss)
            for key, value in [('positions', pos), ('normals', normal), ('uv0', uvs[layer] if uvs else (0, 0)), ('indices', ids), ('weights', weights)]:
                fields[key].append(value)
        nf = count(4000000) if ascii_format else r.number(maximum=4000000)
        faces = [vector(3, int) if ascii_format else r.values('3I') for _ in range(nf)]
        mesh = {k: np.asarray(v, np.int32 if k == 'indices' else np.float32) for k, v in fields.items()}
        mesh.update(name=name, texture=texture, faces=np.asarray(faces, np.int32).reshape(-1, 3))
        meshes.append(mesh)
    if dropped:
        warnings.append('Redução para 4 pesos por vértice: descarte máximo %.2f%%' % (100*dropped))
    if not ascii_format and r.pos != len(raw):
        warnings.append('%d bytes adicionais de metadados XPS não convertidos' % (len(raw)-r.pos))
    return checked({'kind': 'xps', 'name': path.stem, 'path': str(path), 'bones': bones,
                    'meshes': meshes, 'warnings': warnings})


def load(path, cache=None, t4_iso_path=None):
    if str(path).startswith('t4:'):
        return t4_iso(path, t4_iso_path, cache=Path(cache).parent / 't4' if cache else None)
    path = Path(path)
    if path.name.lower().endswith('.t5skin.json'):
        data=json.loads(path.read_text(encoding='utf8'))
        if data.get('format')!='T5SkinStudioEdit1':raise ValueError('Edição do Studio inválida')
        for mesh in data['meshes']:
            for key in ('positions','normals','uv0','weights','indices','faces'):
                mesh[key]=np.asarray(mesh[key],np.int32 if key in ('indices','faces') else np.float32)
        return checked(dict(kind='t5edit',name=data['name'],path=str(path),bones=data['bones'],
                            meshes=data['meshes'],warnings=data.get('warnings',[]),base_index=data['base_index']))
    if path.name.lower() == 'scene.json':
        return t4(path, cache=Path(cache).parent/'t4' if cache else None)
    if path.suffix.lower() in ('.mesh', '.xps', '.ascii'):
        return xps(path)
    raise ValueError('Escolha um modelo .mesh, .mesh.ascii ou .xps')
