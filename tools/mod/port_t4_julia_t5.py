import argparse
from collections import OrderedDict
import json
from pathlib import Path
import struct
from tools.stages.tekken4 import character_draws
from tools.stages.container import pack
import numpy as np
from PIL import Image


def align(data, n=16):
    data.extend(b'\0' * (-len(data) % n))


def container(parts):
    out = bytearray(4 + len(parts) * 8)
    struct.pack_into('<I', out, 0, len(parts))
    align(out)
    for i, part in enumerate(parts):
        struct.pack_into('<II', out, 4 + i * 8, len(out), len(part))
        out.extend(part)
        align(out)
    return bytes(out)


def bone_map():
    mapping = dict(enumerate([1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
                              4, 15, 16, 17, 21, 18, 19, 20, 22]))
    mapping.update({22: 6, 23: 17, 24: 21, 25: 20, 26: 22,
                    27: 32, 28: 25, 29: 31, 30: 35, 31: 32,
                    32: 33, 33: 41, 34: 34, 35: 35})
    mapping.update({i: i for i in range(36, 111)})
    mapping.update({49: 50, 50: 49, 53: 54, 54: 53})
    mapping.update({111: 111, 112: 112, 113: 113, 114: 126, 115: 127,
                    116: 128, 117: 114, 118: 115, 119: 116,
                    120: 117, 121: 118, 122: 120})
    assert len(mapping) == 123
    return mapping


def texture_picture(im, gidx):
    w, h = im.size
    if w & (w - 1) or h & (h - 1):
        raise ValueError('Expected power-of-two source texture')
    paletted = im.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
    pixels = np.asarray(paletted, np.uint8).copy()
    palette = np.zeros((256, 4), np.uint8)
    rgba = np.asarray(paletted.convert('RGBA'), np.uint8)
    for i in np.unique(pixels):
        palette[i] = rgba[pixels == i][0]
    palette[:, 3] = np.rint(palette[:, 3].astype(float) * 128 / 255).astype(np.uint8)
    order = np.arange(256)
    order = (order & ~24) | ((order & 8) << 1) | ((order & 16) >> 1)
    raw_palette = palette[order].tobytes()
    size = 80 + w * h + len(raw_palette)
    header = bytearray(80)
    struct.pack_into('<IIIHHBBBBHH', header, 0, size, len(raw_palette), w * h,
                     80, 256, 0, 1, 3, 5, w, h)
    header[48:52] = b'eXt\0'
    struct.pack_into('<II', header, 52, 32, 16)
    header[64:68] = b'GIDX'
    struct.pack_into('<III', header, 68, 16, gidx, 0)
    return bytes(header) + pixels.tobytes() + raw_palette


def crop_texture(path, draws):
    im = Image.open(str(path)).convert('RGBA')
    size = np.array(im.size)
    coords = np.concatenate([d['uv0'] for d in draws]) * size
    origin = np.rint(coords.min(0)).astype(int)
    extent = np.maximum(1, np.rint(coords.max(0)).astype(int) - origin)
    extent = np.array([1 << (int(v) - 1).bit_length() for v in extent])
    pixels = np.asarray(im)
    x = (np.arange(extent[0]) + origin[0]) % size[0]
    y = (np.arange(extent[1]) + origin[1]) % size[1]
    cropped = Image.fromarray(pixels[y[:, None], x[None, :]])
    for draw in draws:
        draw['uv0'] = ((draw['uv0'] * size - origin) / extent).astype(np.float32)
    return cropped


def vif(draw, mapping, translation=(0, 1127, 0)):
    positions = draw['positions'].copy()
    positions += np.asarray(translation, dtype=np.float32)
    n = len(positions)
    if not 3 <= n <= 40:
        raise ValueError('Unsupported VU packet size')
    weights = draw['weights'].copy()
    ids = np.vectorize(mapping.__getitem__)(draw['indices']).astype(np.uint8)
    for row in range(n):
        accum = {}
        for bone, weight in zip(ids[row], weights[row]):
            if weight > 0:
                accum[int(bone)] = accum.get(int(bone), 0.) + float(weight)
        weights[row] = 0
        ids[row] = 0
        for j, (bone, weight) in enumerate(accum.items()):
            weights[row, j], ids[row, j] = weight, bone
    palette = sorted(set(int(x) for x in ids[weights > 0]))
    if len(palette) > 10:
        raise ValueError('Native palette overflow')
    encoded = np.zeros((n, 4), np.uint8)
    for i, bone in enumerate(palette):
        encoded[(ids == bone) & (weights > 0)] = i * 7
    out = bytearray(struct.pack('<7I', 0x00910370, 0x01000105, 0x60018000,
                                 n, 0x20000000, 0x80, 0x78008001 | n << 16))
    out.extend(positions.astype('<f4').tobytes())
    out.extend(struct.pack('<I', 0x68008002 | n << 16))
    out.extend(draw['normals'].astype('<f4').tobytes())
    out.extend(struct.pack('<I', 0x64008004 | n << 16))
    out.extend(draw['uv0'].astype('<f4').tobytes())
    out.extend(struct.pack('<II', 0x01000102, 0x6c0080cc | n << 16))
    out.extend(weights.astype('<f4').tobytes())
    out.extend(struct.pack('<I', 0x6e00c0cd | n << 16))
    out.extend(encoded.tobytes())
    out.extend(struct.pack('<3I', 0x01000500, 0x20000000, 0xffffff7f))
    for start in draw.get('strip_starts', [0]):
        out.extend(struct.pack('<I', 0x70068001 + 5 * start))
    align(out)
    out.extend(struct.pack('<4I', 0x01000101, 0x20000000, 0, 0x14000000))
    struct.pack_into('<I', out, 0, 0x00910000 | len(out))
    return bytes(out), palette, positions


def batch_strips(draws, mapping=None):
    fields = ('positions', 'normals', 'uv0', 'weights', 'indices')
    mapping = bone_map() if mapping is None else mapping
    result = []
    current = None
    palette = set()
    for draw in draws:
        bones = {mapping[int(i)] for i in draw['indices'][draw['weights'] > 0]}
        count = 0 if current is None else len(current['positions'])
        padding = count % 2
        if current is None or count + padding + len(draw['positions']) > 40 or len(palette | bones) > 10:
            if current is not None:
                result.append(current)
            current = {f: draw[f].copy() for f in fields}
            current['strip_starts'] = [0]
            palette = bones
            continue
        for field in fields:
            pieces = [current[field]]
            if padding:
                pieces.append(current[field][-1:])
            pieces.append(draw[field])
            current[field] = np.concatenate(pieces)
        current['strip_starts'].append(count + padding)
        palette |= bones
    if current is not None:
        result.append(current)
    return result


def model(groups, textures, reference, mapping=None, translation=(0, 1127, 0), material_state=None):
    mapping = bone_map() if mapping is None else mapping
    out = bytearray(32)
    batches = [(tex0, batch_strips(draws, mapping)) for tex0, draws in groups.items()]
    total_packets = sum(len(draws) for _, draws in batches)
    allpos = np.concatenate([d['positions'] for _, draws in batches for d in draws]) + translation
    if total_packets>65535 or len(allpos)>65535:
        raise ValueError('Limite real do objeto NUDP: contadores de 16 bits (65.535). A skin gera %d pacotes e %d vértices após divisão em pacotes; reduza ou divida a geometria.'%(total_packets,len(allpos)))
    center = (allpos.min(0) + allpos.max(0)) / 2
    radius = np.linalg.norm(allpos - center, axis=1).max()
    object_count = struct.unpack_from('<H', reference, 10)[0]
    out.extend(struct.pack('<HBBHH4f', 0x20, 0, 0xff, total_packets,
                           len(allpos), *center, radius))
    first_sub = len(out)
    out.extend(b'\0' * (40 * total_packets))
    for _ in range(object_count - 1):
        out.extend(struct.pack('<HBBHH4f', 0, 0, 0xff, 0, 0, 0, 0, 0, 0))
    align(out)
    material = reference[0x2210:0x2240]
    gs = reference[0x2330:0x2360]
    if material_state is not None:
        material, gs = material_state
    if len(material) != 48 or len(gs) != 48:
        raise ValueError('Invalid reference material')
    matoff = len(out)
    out.extend(material)
    gsoff = len(out)
    out.extend(gs)
    align(out)
    packet_count = 0
    for tex0, draws in batches:
        for draw in draws:
            packet, palette, _ = vif(draw, mapping, translation)
            offset = len(out)
            out.extend(packet)
            sub = first_sub + packet_count * 40
            struct.pack_into('<5IHHI', out, sub, textures[tex0], gsoff, matoff,
                             0x80000042, offset, len(packet) // 16, 1, 0)
            out[sub + 28:sub + 40] = bytes([0, 0] + palette + [255] * (10 - len(palette)))
            packet_count += 1
    struct.pack_into('<4sIHHI4f', out, 0, b'NUDP', len(out), 0x5103,
                     object_count, 0, *center, radius)
    return bytes(out), packet_count


def build(source_manifest, source_native, target_package, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path(source_manifest).read_text(encoding='utf-8'))
    draws, _ = character_draws(Path(source_native).read_bytes())
    groups = OrderedDict()
    for draw in draws:
        groups.setdefault(draw['tex0'], []).append(draw)
    parts = list(pack(Path(target_package).read_bytes()))
    texbank = bytearray(parts[1])
    picture_count = struct.unpack_from('<H', texbank, 6)[0]
    textures = {}
    for i, tex0 in enumerate(groups):
        gidx = 0x10416000 + picture_count + i
        key = 'Character_0568_0_%016x' % tex0
        cropped = crop_texture(manifest['textures'][key]['file'], groups[tex0])
        texbank.extend(texture_picture(cropped, gidx))
        textures[tex0] = gidx
    struct.pack_into('<H', texbank, 6, picture_count + len(groups))
    native, packet_count = model(groups, textures, parts[2])
    parts[1] = bytes(texbank)
    parts[2] = native
    header = bytearray(parts[0])
    struct.pack_into('<I', header, 4, 0x30000)
    parts[0] = bytes(header)
    result = container(parts)
    original_size = Path(target_package).stat().st_size
    if len(result) > original_size:
        raise ValueError('Converted package exceeds reserved resource size: %d > %d' %
                         (len(result), original_size))
    result += b'\0' * (original_size - len(result))
    (output / 'julia_t4_for_t5.bin').write_bytes(result)
    (output / 'julia_t4_for_t5.nud').write_bytes(native)
    (output / 'julia_t4_for_t5.tm2').write_bytes(parts[1])
    (output / 'julia_t4_for_t5.mif').write_bytes(parts[4])
    report = {'status': 'experimental_assets_not_game_validated', 'target_resource': 548,
              'original_size': original_size, 'converted_size': sum(len(p) for p in parts),
              'objects': struct.unpack_from('<H', native, 10)[0],
              'materials': len(groups), 'draw_packets': packet_count,
              'vertices': sum(len(d['positions']) for d in draws),
              'triangles': sum(len(d['faces']) for d in draws),
              'source_bones': 123, 'target_bones': 132, 'bone_map': bone_map(),
              'checksum': int(np.frombuffer(result, '<u4', len(result) // 4).sum()) & 0xffffffff}
    (output / 'conversion.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'bone_map'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', required=True)
    parser.add_argument('--source-native', required=True)
    parser.add_argument('--target-package', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    build(args.source_manifest, args.source_native, args.target_package, args.output)
