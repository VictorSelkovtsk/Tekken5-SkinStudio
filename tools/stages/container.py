import struct
import numpy as np


def pack(data):
    if len(data)<4:raise ValueError('Truncated little-endian container')
    count=struct.unpack_from('<I',data)[0]
    if not 1<=count<=4096 or 4+8*count>len(data):raise ValueError('Invalid container table')
    result=[];end=4+8*count
    for i in range(count):
        off,size=struct.unpack_from('<2I',data,4+i*8)
        if off<end or off+size>len(data):raise ValueError('Overlapping/truncated container entries')
        result.append(data[off:off+size]);end=off+size
    return result


def mif(data,count):
    if data[:4]!=b'MIF\0':raise ValueError('Missing MIF')
    n,start,names,end=struct.unpack_from('<4I',data,16)
    if n!=count or start+192*n>len(data) or names>=len(data):raise ValueError('Invalid MIF table')
    out=[]
    for i in range(n):
        pos=start+192*i;off=names+struct.unpack_from('<I',data,pos)[0]
        if not names<=off<end:raise ValueError('MIF name outside table')
        name=data[off:data.index(b'\0',off,end)].decode('cp932','replace')
        matrix=np.frombuffer(data,'<f4',16,pos+16).reshape(4,4).astype(np.float32)
        if not np.isfinite(matrix).all():raise ValueError('Nonfinite MIF matrix')
        out.append((name,matrix))
    return out
