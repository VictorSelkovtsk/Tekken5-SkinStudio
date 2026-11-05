from pathlib import Path
from collections import OrderedDict
import json,secrets,shutil,subprocess,os
from .convert import prepared,skeleton,material_key
from .sources import worlds, REPO
import numpy as np
from PIL import Image


def editor(executable=None):
    bundled=REPO/'runtime/blender279/blender.exe'
    path=Path(executable or (bundled if bundled.is_file() else REPO/'out/tools/blender279/blender-2.79b-windows64/blender.exe'))
    if not path.is_file():raise ValueError('Blender 2.79 não encontrado. Configure o executável em Pastas e jogo.')
    return path


def open_project(project,executable=None):
    script=Path(__file__).with_name('blender279_edit.py')
    subprocess.Popen([str(editor(executable)),'--factory-startup',project['blend'],'--python',str(script),'--','resume'],cwd=project['folder'])


def textured_parts(source,settings,meshes,mapping,folder):
    groups=OrderedDict()
    for m in meshes:groups.setdefault(m['material_key'],[]).append(m)
    merged=[]
    for number,(key,items) in enumerate(groups.items()):
        config=settings.get('materials',{}).get(key,{})
        file=Path(config.get('texture') or items[0]['texture'] or '')
        if not file.is_file():raise ValueError('Textura ausente: '+str(file))
        image=np.array(Image.open(file).convert('RGBA'))
        color=config.get('color','#ffffff').lstrip('#')
        if len(color)!=6:raise ValueError('Cor de material inválida')
        tint=np.array([int(color[i:i+2],16)/255 for i in (0,2,4)])
        image[:,:,:3]=np.rint(image[:,:,:3]*tint).clip(0,255).astype(np.uint8)
        alpha=config.get('alpha',items[0].get('alpha','texture' if source['kind']=='xps' else 'opaque'))
        if alpha=='opaque':image[:,:,3]=255
        texture=folder/('texture_%02d.png'%number);Image.fromarray(image).save(texture)
        result={k:np.concatenate([m[k] for m in items]) for k in ('positions','normals','uv0','weights')}
        result['indices']=np.array([[mapping[int(i)] for i in row] for m in items for row in m['indices']],np.int32)
        faces=[];offset=0
        for m in items:faces.append(m['faces']+offset);offset+=len(m['positions'])
        result['faces']=np.concatenate(faces)
        result={k:v.tolist() for k,v in result.items()}
        result.update(name='Material %02d · %s'%(number+1,file.stem),texture=str(texture),alpha=alpha)
        merged.append(result)
    return merged


def create(source,package,settings,base,home,executable=None,start_editor=True):
    executable=editor(executable)
    target=skeleton(package);meshes,mapping=prepared(source,target,settings)
    folder=Path(home)/'edits'/secrets.token_hex(8);folder.mkdir(parents=True)
    try:merged=textured_parts(source,settings,meshes,mapping,folder)
    except Exception:
        shutil.rmtree(folder,ignore_errors=True);raise
    data=dict(format='T5SkinStudioEdit1',name=source['name']+' · Blender',base_index=base,bones=target,
              worlds=worlds(target).tolist(),meshes=merged,warnings=list(source.get('warnings',[])))
    input_file=folder/'input.t5skin.json';output=folder/'edited.t5skin.json';blend=folder/'model.blend'
    data['edit_output']=str(output);input_file.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
    script=Path(__file__).with_name('blender279_edit.py')
    result=subprocess.run([str(executable),'--factory-startup','-b','--python',str(script),'--','build',str(input_file),str(blend)],
                          capture_output=True,text=True,encoding='utf8',errors='replace',timeout=240,
                          creationflags=0x08000000 if os.name=='nt' else 0)
    (folder/'build.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf8')
    if result.returncode or not blend.is_file() or not output.is_file():raise ValueError('Falha ao preparar o Blender. Consulte '+str(folder/'build.log'))
    if start_editor:subprocess.Popen([str(executable),'--factory-startup',str(blend),'--python',str(script),'--','resume'],cwd=str(folder))
    project=dict(blend=str(blend),output=str(output),base_index=base,folder=str(folder))
    launcher='@echo off\r\nstart "" "'+str(executable)+'" --factory-startup "'+str(blend)+'" --python "'+str(script)+'" -- resume\r\n'
    (folder/'Editar esta skin.bat').write_text(launcher,encoding='utf8')
    (Path(home)/'last_blender_edit.json').write_text(json.dumps(project,indent=2),encoding='utf8')
    return dict(blender_project=project)
