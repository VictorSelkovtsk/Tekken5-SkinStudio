import struct
import numpy as np
from PIL import Image


def bits(value, positions):
    result = np.zeros_like(value)
    for source, target in enumerate(positions):
        result |= ((value >> source) & 1) << target
    return result


def address(x, y, bp, bw, psm):
    if psm == 0:
        pw,ph,cw,ch,bpp=64,32,8,8,32
        block=bits(x//cw%8,[0,2,4])|bits(y//ch%4,[1,3])
        column=bits(x%cw,[0,2,3])|bits(y%ch,[1,4,5])
    elif psm == 2:
        pw,ph,cw,ch,bpp=64,64,16,8,16
        block=bits(x//cw%4,[1,3])|bits(y//ch%8,[0,2,4])
        column=bits(x%cw,[1,3,4,0])|bits(y%ch,[2,5,6])
    elif psm == 19:
        pw,ph,cw,ch,bpp=128,64,16,16,8
        block=bits(x//cw%8,[0,2,4])|bits(y//ch%4,[1,3])
        column=bits(x%cw,[2,4,5,1]) ^ bits(y%ch,[3,0,6,7]) ^ ((((y>>1)^(y>>2))&1)<<5)
    elif psm == 20:
        pw,ph,cw,ch,bpp=128,128,32,16,4
        block=bits(x//cw%4,[1,3])|bits(y//ch%8,[0,2,4])
        column=bits(x%cw,[3,5,6,1,2]) ^ bits(y%ch,[4,0,7,8]) ^ ((((y>>1)^(y>>2))&1)<<6)
    else:
        raise ValueError('GS PSM %d unsupported'%psm)
    page=(y//ph)*(bw*64//pw)+x//pw
    return (bp*(2048//bpp)+page*(65536//bpp)+block*(2048//bpp)+column)%(33554432//bpp)


class Memory:
    def __init__(self):
        self.data=np.zeros(4*1024*1024,dtype=np.uint8)
        self.transfers=[]

    def upload(self, raw, bp, bw, psm, x, y, w, h):
        yy,xx=np.indices((h,w));a=address(xx+x,yy+y,bp,bw,psm).ravel()
        raw=np.frombuffer(raw,np.uint8)
        if psm==20:
            values=np.column_stack((raw&15,raw>>4)).ravel()[:w*h]
            for high in (0,1):
                mask=(a&1)==high;dst=a[mask]//2
                self.data[dst]=(self.data[dst]&(15 if high else 240))|(values[mask]<<(4*high))
        elif psm in (0,2):
            stride=4 if psm==0 else 2
            dst=(a[:,None]*stride+np.arange(stride)).ravel()
            self.data[dst]=raw[:len(dst)]
        elif psm==19:self.data[a]=raw[:len(a)]
        else:raise ValueError('Unsupported transfer PSM')
        self.transfers.append({'bp':bp,'bw':bw,'psm':psm,'xy':[x,y],'wh':[w,h]})

    def load_ngi(self, data):
        offset=0;regs={};pending=bytearray()
        while offset+16<=len(data):
            tag,desc=struct.unpack_from('<2Q',data,offset);offset+=16
            loops=tag&0x7fff;mode=(tag>>58)&3;nreg=(tag>>60)&15 or 16
            if mode==0:
                if pending:raise ValueError('Interrupted NGI transfer')
                for i in range(loops*nreg):
                    if offset+16>len(data):raise ValueError('Truncated GIF registers')
                    value,reg=struct.unpack_from('<2Q',data,offset);offset+=16
                    if (desc>>(4*(i%nreg)))&15 !=14:raise ValueError('NGI register mode unsupported')
                    regs[reg&255]=value
            elif mode==2:
                size=loops*16
                if offset+size>len(data):raise ValueError('Truncated GIF image')
                pending.extend(data[offset:offset+size]);offset+=size
                if not all(k in regs for k in (0x50,0x51,0x52,0x53)):raise ValueError('Missing NGI transfer setup')
                b,p,r=regs[0x50],regs[0x51],regs[0x52]
                bp=(b>>32)&0x3fff;bw=(b>>48)&63;psm=(b>>56)&63
                x=(p>>32)&2047;y=(p>>48)&2047;w=r&4095;h=(r>>32)&4095
                bpp={0:32,2:16,19:8,20:4}.get(psm)
                if not bpp or not w or not h or regs[0x53]&3:raise ValueError('Invalid NGI transfer')
                expected=(w*h*bpp+7)//8
                if len(pending)>=expected:
                    self.upload(bytes(pending[:expected]),bp,bw,psm,x,y,w,h);pending.clear()
            else:raise ValueError('NGI GIF mode unsupported: %d'%mode)
        if pending:raise ValueError('Unfinished NGI upload')
        if any(data[offset:]):raise ValueError('Trailing NGI data')
        return self

    def texture(self, tex0):
        bp=tex0&0x3fff;bw=(tex0>>14)&63;psm=(tex0>>20)&63
        w=1<<((tex0>>26)&15);h=1<<((tex0>>30)&15)
        if max(w,h)>2048:raise ValueError('Invalid GS texture size')
        yy,xx=np.indices((h,w));a=address(xx,yy,bp,bw,psm)
        if psm in (19,20):
            indices=self.data[a] if psm==19 else (self.data[a//2]>>((a&1)*4))&15
            cbp=(tex0>>37)&0x3fff;cpsm=(tex0>>51)&15;csm=(tex0>>55)&1
            if cpsm or csm:raise ValueError('Unsupported GS palette mode')
            pal=np.arange(256 if psm==19 else 16)
            order=bits(pal,[0,2,3,1,6,4,5,7])
            rgba=self.data[(cbp*256+order[:,None]*4+np.arange(4))%(4*1024*1024)][indices]
        elif psm==0:rgba=self.data[(a[:,:,None]*4+np.arange(4))%(4*1024*1024)]
        elif psm==2:
            color=self.data[a*2].astype(np.uint16)|(self.data[a*2+1].astype(np.uint16)<<8)
            rgba=np.stack(((color&31)*255//31,((color>>5)&31)*255//31,((color>>10)&31)*255//31,(color>>15)*128),axis=2).astype(np.uint8)
        else:raise ValueError('Unsupported GS texture format')
        rgba=rgba.copy();rgba[:,:,3]=np.minimum(rgba[:,:,3].astype(np.uint16)*2,255).astype(np.uint8)
        return Image.fromarray(rgba,'RGBA')
