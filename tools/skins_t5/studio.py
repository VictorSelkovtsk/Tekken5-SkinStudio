from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import argparse
import datetime
import json
import mimetypes
import os
import secrets
import socket
import struct
import subprocess
import sys
import threading
import traceback
import webbrowser
from urllib.parse import urlparse
from .game import Archive, catalogue, build_iso, NAMES
from .sources import load, worlds, open_t4, t4_library
from .convert import skeleton, prepared, material_key,alignment
from .xps_mapping import suggest as suggest_xps
from .convert import convert as native_convert
from .facial import NAMES as FACE_NAMES,native_face
from .physics import physics
from . import original
from . import i18n

ROOT = Path(__file__).resolve().parent


class StudioServer(ThreadingHTTPServer):
    allow_reuse_address = os.name != 'nt'
    def server_bind(self):
        if os.name=='nt':self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()
DEFAULT_ISO = DEFAULT_T4 = ''


def open_iso(path):
    if not str(path).strip():raise ValueError('Escolha a ISO original do Tekken 5 em Pastas e jogo')
    if not Path(path).is_file():raise ValueError('ISO do Tekken 5 não encontrada: '+str(path))
    try:return Archive(path)
    except (ValueError,KeyError,struct.error):
        raise ValueError('Esta ISO não é o Tekken 5 USA 1.00 (SLUS-21059) original. Use a ISO original, sem modificações.') from None


class Studio:
    def __init__(self, home):
        self.home = Path(home); self.home.mkdir(parents=True,exist_ok=True)
        self.file = self.home/'studio.json'
        self.config = json.loads(self.file.read_text(encoding='utf8')) if self.file.exists() else {
            'iso':DEFAULT_ISO,'t4':DEFAULT_T4,'mods':[]}
        self.config.pop('taghd',None)
        if str(self.config.get('t4','')).strip() and not Path(self.config['t4']).is_file():self.config['t4']=''
        self.source = None; self.archive = None; self.files = {}; self.token = secrets.token_urlsafe(32)
        self.job = {'state':'idle','message':'Pronto para importar','error':None}
        try:
            from .mods import recover
            recover(self)
        except Exception:
            pass
        self.lock = threading.Lock()
    def save(self):
        temp = self.file.with_suffix('.tmp'); temp.write_text(json.dumps(self.config,indent=2,ensure_ascii=False),encoding='utf8'); temp.replace(self.file)
    def register(self, path):
        if not path or not Path(path).is_file(): return None
        path = str(Path(path).resolve())
        for key,value in self.files.items():
            if value == path: return '/file/'+key
        key = secrets.token_urlsafe(18); self.files[key] = path
        return '/file/'+key
    def texture(self, path):
        if path and Path(path).suffix.lower() in ('.dds','.tga','.bmp'):
            import hashlib
            from PIL import Image
            file=Path(path)
            if file.is_file():
                key=hashlib.sha256((str(file.resolve())+str(file.stat().st_mtime_ns)).encode()).hexdigest()[:24]
                cached=self.home/'cache/textures'/(key+'.png');cached.parent.mkdir(parents=True,exist_ok=True)
                if not cached.exists():
                    with Image.open(file) as image:image.convert('RGBA').save(cached)
                path=cached
        return self.register(path)
    def game(self):
        if self.archive is None or str(self.archive.path) != str(Path(self.config['iso'])):
            self.archive = open_iso(self.config['iso'])
        return self.archive
    def library(self):
        t4 = str(self.config.get('t4', '') or '').strip()
        return t4_library() if t4 and Path(t4).is_file() else []
    def preview(self, data, source=None):
        source = self.source if source is None else source
        if source is None: raise ValueError('Escolha uma skin primeiro')
        base = int(data.get('base_index',28)); settings = data.get('settings',{})
        if not 0 <= base < 79: raise ValueError('Roupa base inválida')
        package=self.game().read(240+11*base)
        target = skeleton(package)
        meshes,mapping = prepared(source,target,settings)
        try:physics_note=physics(package,len(target))['note']
        except ValueError as error:physics_note=str(error)
        audit={}
        if source['kind']=='xps':
            scale,rotation,offset=alignment(source,target,settings)
            sp=worlds(source['bones'])[:,:3,3]@rotation.T*scale+offset
            _,audit=suggest_xps(source,target,sp,worlds(target)[:,:3,3],settings)
        materials, result = {}, []
        for mesh in source['meshes']:
            key=material_key(mesh);cfg=settings.get('materials',{}).get(key,{})
            file=cfg.get('texture') or mesh['texture']
            if key not in materials:
                materials[key]=dict(key=key,name=Path(file).name if file else mesh['name'],path=file,
                                    url=self.texture(file),color=cfg.get('color','#ffffff'),
                                    alpha=cfg.get('alpha',mesh.get('alpha','texture' if source['kind']=='xps' else 'opaque')))
        for m in meshes:
            key = m['material_key']; cfg = settings.get('materials',{}).get(key,{})
            file = cfg.get('texture') or m['texture']
            if key not in materials:
                materials[key] = dict(key=key,name=Path(file).name if file else m['name'],path=file,
                                      url=self.texture(file),color='#ffffff',alpha='opaque')
            result.append(dict(positions=m['positions'].round(4).ravel().tolist(),normals=m['normals'].round(4).ravel().tolist(),
                               uv=m['uv0'].round(7).ravel().tolist(),faces=m['faces'].ravel().tolist(),
                               weights=m['weights'].round(6).ravel().tolist(),sources=m['indices'].ravel().tolist(),
                               indices=[mapping[int(i)] for i in m['indices'].ravel()],material=key))
        return dict(name=source['name'],kind=source['kind'],meshes=result,materials=list(materials.values()),
                    source_bones=[dict(id=i,name=b['name'],target=mapping[i],**audit.get(i,{})) for i,b in enumerate(source['bones'])],
                    target_bones=[dict(id=i,name=b.get('label',b['name']),parent=b['parent'],position=pos.tolist(),
                                       category=b.get('category',''),native_objects=b.get('native_objects',[]),evidence=b.get('evidence',''),
                                       physics=b.get('physics'))
                                  for i,(b,pos) in enumerate(zip(target,worlds(target)[:,:3,3]))],
                    facial_available=native_face(target) and any(any(85<=mapping[int(i)]<=110 for i in m['indices'][m['weights']>0]) for m in meshes),
                    triangles=sum(len(m['faces']) for m in meshes),warnings=source['warnings'],physics_note=physics_note)
    def original(self, base, textures=None):
        textures={k:str(v) for k,v in (textures or {}).items() if v and Path(str(v)).is_file()}
        result=original.preview(self.game(),base,self.home,self.register,textures)
        chars,_=catalogue(self.game())
        owner=next((c for c in chars for s in c['slots'] if s['index']==base),None)
        slot=next((s for s in owner['slots'] if s['index']==base),None) if owner else None
        result['name']=(owner['name']+' · '+slot['label']) if slot else 'Roupa %d'%base
        result['character']=owner['id'] if owner else None
        result['textures']=textures
        return result
    def save_textures(self, data):
        base=int(self.source['base_index']);chars,_=catalogue(self.game())
        owner=next((c for c in chars for s in c['slots'] if s['index']==base),None)
        if owner is None:raise ValueError('Roupa sem personagem no catálogo')
        textures={k:str(v) for k,v in (data.get('textures') or {}).items() if v}
        if not textures:raise ValueError('Troque ao menos uma textura antes de salvar')
        for path in textures.values():
            if not Path(path).is_file():raise ValueError('Imagem não encontrada: '+path)
        name=str(data.get('name') or 'Texturas · '+self.original(base)['name']).strip()[:100]
        package=self.game().read(240+11*base);edit=data.get('edit')
        current=next((m for m in self.config['mods'] if m['id']==edit),None) if edit else None
        if edit and current is None:raise ValueError('O mod em edição não existe mais')
        def job():
            import shutil
            self.job['message']='Gravando as texturas na roupa original…'
            key=current['id'] if current else secrets.token_hex(8);folder=self.home/'mods'/key;keep=folder/'textures';keep.mkdir(parents=True,exist_ok=True)
            stored={}
            for material,path in textures.items():
                src=Path(path).resolve();dst=keep/(material+src.suffix.lower())
                if src!=dst.resolve():shutil.copyfile(src,dst)
                stored[material]=str(dst)
            images={int(material[3:],16):path for material,path in stored.items()}
            asset=folder/('textures_'+secrets.token_hex(4)+'.bin');asset.write_bytes(original.texture_package(package,images))
            report=dict(asset=str(asset),bytes=asset.stat().st_size,triangles=0,textures=len(images))
            mod=dict(id=key,name=name,kind='textures',source=str(self.config['iso']),character=owner['id'],base_index=base,mode='replace',
                     enabled=current['enabled'] if current else True,asset=str(asset),settings=dict(textures=stored),report=report)
            if current:
                old=Path(current['asset']);index=self.config['mods'].index(current);self.config['mods'][index]=mod
            else:self.config['mods'].append(mod)
            self.save()
            if current and old.resolve()!=asset.resolve() and old.parent.resolve()==folder.resolve():old.unlink(missing_ok=True)
            for f in keep.iterdir():
                if str(f) not in stored.values():f.unlink(missing_ok=True)
            (folder/'mod.json').write_text(json.dumps(mod,ensure_ascii=False,indent=2),encoding='utf8')
            return dict(mod,updated=bool(current))
        return self.background_job(job)
    def background_job(self, action):
        if self.job['state'] == 'running': raise ValueError('Aguarde a operação atual terminar')
        self.job = dict(state='running',message='Preparando…',error=None)
        def run():
            try:
                result = action()
                self.job.update(state='done',message='Concluído',result=result)
            except Exception as e:
                (self.home/'last_error.log').write_text(traceback.format_exc(),encoding='utf8')
                self.job.update(state='error',message=str(e),error=str(e))
        threading.Thread(target=run,daemon=True).start()
        return self.job
    def api(self, route, data):
        if route == '/api/job': return self.job
        if self.job['state'] == 'running' and route != '/api/init':
            raise ValueError('Aguarde a operação atual terminar')
        if route == '/api/init':
            error = None
            try: chars = catalogue(self.game())[0]
            except Exception as e: chars=[];error=str(e)
            edit_file=self.home/'last_blender_edit.json';edit=None
            if edit_file.is_file():
                try:edit=json.loads(edit_file.read_text(encoding='utf8'))
                except (OSError,ValueError):pass
            return dict(config=self.config,characters=chars,library=self.library(),home=str(self.home),error=error,job=self.job,blender_project=edit)
        if route == '/api/lang':
            code=str(data.get('lang',''))
            if code not in i18n.available(self.home):raise ValueError('Idioma indisponível')
            self.config['lang']=code;self.save();return {'lang':code}
        if route == '/api/config':
            candidate = {k:str(data.get(k,self.config.get(k,''))) for k in ('iso','t4')}
            if 'blender' in data:candidate['blender']=str(data['blender'])
            open_iso(candidate['iso'])
            if candidate['t4'].strip():open_t4(candidate['t4'])
            self.config.update(candidate);self.archive=None;self.save();return self.api('/api/init',{})
        if route == '/api/pick':
            executable = Path(sys.executable)
            if executable.name.lower() == 'pythonw.exe': executable = executable.with_name('python.exe')
            result = subprocess.run([str(executable),'-m','tools.skins_t5.studio','--pick',data.get('kind','source')],
                                    capture_output=True,text=True,encoding='utf8',cwd=str(ROOT.parent.parent),
                                    creationflags=0x08000000 if os.name=='nt' else 0)
            if result.returncode: raise ValueError(result.stderr.strip() or 'Não foi possível abrir a seleção de arquivo')
            return {'path':result.stdout.strip()}
        if route == '/api/source':
            source=load(data['path'],cache=self.home/'cache/sources',t4_iso_path=self.config.get('t4'))
            if source['kind']=='t5edit':data=dict(data,base_index=source['base_index'])
            result=self.preview(data,source);self.source=source
            if source['kind']=='t5edit':result['base_index']=source['base_index']
            return result
        if route == '/api/preview':
            if self.source is not None and self.source.get('kind') == 't5':return self.original(int(self.source['base_index']),data.get('textures'))
            return self.preview(data)
        if route == '/api/t5/costume':
            base=int(data['base_index']);result=self.original(base,data.get('textures'))
            self.source=dict(kind='t5',base_index=base,name=result['name'],path='');return result
        if route == '/api/t5/save':
            if self.source is None or self.source.get('kind')!='t5':raise ValueError('Abra uma roupa original do Tekken 5')
            return self.save_textures(data)
        if route == '/api/anim/banks':
            return original.banks(self.game(),int(data['base_index']))
        if route == '/api/anim/clip':
            return original.clip_transforms(self.game(),int(data['base_index']),int(data['bank']),int(data['clip']),bool(data.get('root')))
        if route == '/api/blender/edit':
            if self.source is None:raise ValueError('Escolha uma skin primeiro')
            from .blender import create
            base=int(data.get('base_index',28));settings=data.get('settings',{});source=self.source
            if not 0<=base<79:raise ValueError('Roupa base inválida')
            package=self.game().read(240+11*base)
            def edit_job():
                self.job['message']='Preparando modelo, texturas e pesos para o Blender 2.79…'
                return create(source,package,settings,base,self.home,self.config.get('blender'))
            return self.background_job(edit_job)
        if route == '/api/blender/open':
            from .blender import open_project
            try:
                project=json.loads((self.home/'last_blender_edit.json').read_text(encoding='utf8'))
                file=Path(project['blend']).resolve()
            except (OSError,ValueError,KeyError,TypeError):raise ValueError('Nenhuma edição do Blender para reabrir') from None
            if (self.home/'edits').resolve() not in file.parents or not file.is_file():raise ValueError('Projeto Blender não encontrado')
            open_project(project,self.config.get('blender'));return project
        if route == '/api/blender/reload':
            file=Path(data['output']).resolve();root=(self.home/'edits').resolve()
            if root not in file.parents or not file.name.endswith('.t5skin.json'):raise ValueError('Edição não pertence ao Studio')
            error=Path(str(file)+'.error')
            if error.is_file():raise ValueError('O Blender não exportou a última edição: '+error.read_text(encoding='utf8'))
            if not file.is_file():raise ValueError('Salve a edição no Blender antes de recarregar')
            source=load(file)
            result=self.preview(dict(base_index=source['base_index'],settings=dict(scale=1,yaw=0,offset=[0,0,0],retarget=False)),source)
            self.source=source;result['base_index']=source['base_index'];result['path']=str(file);return result
        if route == '/api/convert':
            if self.source is None: raise ValueError('Escolha uma skin')
            if self.source.get('kind')=='t5':raise ValueError('Roupas originais são salvas como mod de texturas')
            source = self.source; settings=data.get('settings',{});base=int(data['base_index']);char=int(data['character']);mode=data['mode']
            chars,_ = catalogue(self.game())
            if base not in [s['index'] for s in chars[char]['slots']]: raise ValueError('A roupa base não pertence ao personagem')
            edit=data.get('edit');current=None
            if edit:
                current=next((m for m in self.config['mods'] if m['id']==edit),None)
                if current is None:raise ValueError('O mod em edição não existe mais')
            if mode == 'add' and (current is None or current['enabled']):
                extra = sum(m['enabled'] and m['mode']=='add' and m['character']==char and m['id']!=edit for m in self.config['mods'])
                if not chars[char]['can_add'] or len(chars[char]['slots'])+extra >= 5: raise ValueError('Limite de cinco roupas alcançado')
            name = str(data.get('name') or source['name']).strip()[:100]
            package = self.game().read(240+11*base)
            if current:
                from .mods import update
                def edit_job():
                    self.job['message']='Reconvertendo o mod “%s”…'%current['name']
                    entry=update(self,current,lambda output:native_convert(source,package,settings,output),
                                 dict(name=name,source=source['path'],character=char,base_index=base,mode=mode,settings=settings))
                    return dict(entry,updated=True)
                return self.background_job(edit_job)
            def convert_job():
                self.job['message']='Convertendo pesos, texturas e pacotes VU…'
                key=secrets.token_hex(8);folder=self.home/'mods'/key
                report=native_convert(source,package,settings,folder/'skin.bin')
                mod=dict(id=key,name=name,source=source['path'],character=char,base_index=base,mode=mode,
                         enabled=True,asset=report['asset'],settings=settings,report=report)
                (folder/'mod.json').write_text(json.dumps(mod,ensure_ascii=False,indent=2),encoding='utf8')
                self.config['mods'].append(mod);self.save();return mod
            return self.background_job(convert_job)
        if route in ('/api/mod/open','/api/mod/delete-info','/api/mod/delete'):
            from .mods import inspect, delete
            mod=next((m for m in self.config['mods'] if m['id']==data.get('id')),None)
            if mod is None:raise ValueError('Mod inexistente')
            if route.endswith('open') and mod.get('kind')=='textures':
                base=int(mod['base_index']);textures=mod.get('settings',{}).get('textures',{})
                result=self.original(base,textures);self.source=dict(kind='t5',base_index=base,name=result['name'],path='')
                result.update(path='',base_index=base,mod=mod);return result
            if route.endswith('open'):
                if not str(mod['source']).startswith('t4:') and not Path(mod['source']).is_file():raise ValueError('Modelo de origem deste mod não encontrado: '+mod['source'])
                source=load(mod['source'],cache=self.home/'cache/sources',t4_iso_path=self.config.get('t4'))
                result=self.preview(dict(base_index=mod['base_index'],settings=mod.get('settings',{})),source)
                self.source=source;result.update(path=mod['source'],base_index=mod['base_index'],mod=mod);return result
            if route.endswith('delete-info'):return inspect(self.home,mod)
            if data.get('confirmed') is not True:raise ValueError('Confirme a exclusão dos arquivos do mod')
            return delete(self,mod,data.get('stamp'))
        if route == '/api/toggle':
            for m in self.config['mods']:
                if m['id']==data['id']:
                    enabled=bool(data['enabled'])
                    if enabled and m['mode']=='add':
                        char=m['character'];chars,_=catalogue(self.game())
                        extra=sum(x['enabled'] and x['mode']=='add' and x['character']==char and x['id']!=m['id'] for x in self.config['mods'])
                        if not chars[char]['can_add'] or len(chars[char]['slots'])+extra>=5:
                            raise ValueError('Limite de cinco roupas alcançado. Desative outra skin deste personagem.')
                    m['enabled']=enabled;break
            else: raise ValueError('Mod inexistente')
            self.save();return self.config['mods']
        if route == '/api/build':
            mods=[dict(character=m['character'],base_index=m['base_index'],mode=m['mode'],asset=m['asset'])
                  for m in self.config['mods'] if m['enabled']]
            if not mods: raise ValueError('Ative ao menos um mod')
            destination=data.get('output') or str(self.home/'builds'/('Tekken5_Skins_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.iso'))
            def build_job():
                def progress(message): self.job['message']=message
                return build_iso(self.config['iso'],destination,mods,progress)
            return self.background_job(build_job)
        if route == '/api/folder':
            if os.name=='nt': os.startfile(str(self.home))
            return {'path':str(self.home)}
        raise ValueError('Operação desconhecida')


def handler(studio):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def send(self,status,data,kind='application/json; charset=utf-8'):
            if isinstance(data,(dict,list)): data=json.dumps(data,ensure_ascii=False).encode('utf8')
            elif isinstance(data,str): data=data.encode('utf8')
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            try:
                self.end_headers();self.wfile.write(data)
            except ConnectionError:
                pass
        def do_GET(self):
            path=urlparse(self.path).path
            try:
                if path=='/':
                    html=(ROOT/'ui/index.html').read_text(encoding='utf8').replace('__TOKEN__',studio.token)
                    return self.send(200,html,'text/html; charset=utf-8')
                if path=='/health': return self.send(200,{'app':'Tekken5 Skin Studio'})
                if path=='/i18n.json': return self.send(200,i18n.catalog(studio.home,studio.config.get('lang','')))
                if path.startswith('/file/'):
                    file=Path(studio.files[path[6:]])
                elif path in ('/i18n.js','/app.js','/facial.js','/motion.js','/original.js','/style.css','/background.jpg'): file=ROOT/'ui'/path[1:]
                else: return self.send(404,{'error':'Não encontrado'})
                self.send(200,file.read_bytes(),mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            except (KeyError,OSError):self.send(404,{'error':'Arquivo ausente'})
        def do_POST(self):
            try:
                if self.headers.get('X-Studio-Token') != studio.token: return self.send(403,{'error':'Sessão inválida'})
                origin=self.headers.get('Origin')
                if origin and origin != 'http://127.0.0.1:%d'%self.server.server_port: return self.send(403,{'error':'Origem inválida'})
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<8*1024*1024: raise ValueError('Requisição inválida')
                data=json.loads(self.rfile.read(size));route=urlparse(self.path).path
                with studio.lock: result=studio.api(route,data)
                self.send(200,result)
            except Exception as e:self.send(400,{'error':str(e)})
    return Handler


def picker(kind):
    import tkinter as tk
    from tkinter import filedialog
    root=tk.Tk();root.withdraw();root.attributes('-topmost',True)
    if kind=='folder': value=filedialog.askdirectory(parent=root,title='Escolha a pasta')
    else:
        types={'iso':[('Tekken 5 USA 1.00','*.iso')],
               'texture':[('Texturas','*.png *.dds *.tga *.jpg *.bmp')],
               'source':[('Modelos XPS','*.xps *.mesh *.ascii'),('Todos','*.*')]}
        value=filedialog.askopenfilename(parent=root,title='Tekken 5 Skin Studio',filetypes=types.get(kind,types['source']))
    root.destroy();sys.stdout.reconfigure(encoding='utf8');print(value)


def main():
    p=argparse.ArgumentParser();p.add_argument('--home',default=str(ROOT.parents[1]));p.add_argument('--port',type=int,default=8795)
    p.add_argument('--no-browser',action='store_true');p.add_argument('--pick');args=p.parse_args()
    if args.pick:return picker(args.pick)
    studio=Studio(args.home)
    try: server=StudioServer(('127.0.0.1',args.port),handler(studio))
    except OSError:
        import urllib.request
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/health'%args.port,timeout=2) as r: health=json.load(r)
            if health.get('app')!='Tekken5 Skin Studio': raise ValueError('Porta ocupada por outro programa')
        except Exception: raise RuntimeError('A porta %d está ocupada; use --port.'%args.port)
        if not args.no_browser:webbrowser.open('http://127.0.0.1:%d'%args.port)
        return
    print('Tekken 5 Skin Studio: http://127.0.0.1:%d'%server.server_port,flush=True)
    if not args.no_browser:webbrowser.open('http://127.0.0.1:%d'%server.server_port)
    server.serve_forever()


if __name__=='__main__': main()
