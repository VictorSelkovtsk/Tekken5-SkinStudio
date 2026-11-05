import bpy,bmesh,json,sys,math,os,shutil,subprocess
from mathutils import Matrix,Vector
from bpy.app.handlers import persistent

C=Matrix(((.001,0,0,0),(0,0,-.001,0),(0,.001,0,0),(0,0,0,1)))


def metadata():return json.loads(bpy.data.texts['T5_STUDIO_DATA'].as_string())


def export_edit():
    scene=bpy.context.scene;data=metadata();rig=bpy.data.objects.get('T5_Skeleton')
    if rig is None or len(rig.data.bones)!=len(data['bones']):raise ValueError('Preserve o esqueleto T5 e seus ossos.')
    for b in rig.data.bones:
        index=int(b.get('t5_index',-1))
        if not 0<=index<len(data['bones']) or b.name!=data['bones'][index]['name']:
            raise ValueError('Preserve os nomes e os índices dos ossos T5.')
        parent=data['bones'][index]['parent'];expected_parent=data['bones'][parent]['name'] if parent>=0 else None
        if (b.parent.name if b.parent else None)!=expected_parent:
            raise ValueError('Preserve a hierarquia do esqueleto T5.')
        if max(abs(b.matrix_local[r][c]-data['bind'][str(index)][r][c]) for r in range(4) for c in range(4))>1e-5:
            raise ValueError('O esqueleto T5 deve manter a pose de repouso. Ajuste malha e pesos, sem mover ossos em Edit Mode.')
    if max(abs(rig.matrix_world[r][c]-(1 if r==c else 0)) for r in range(4) for c in range(4))>1e-5:
        raise ValueError('Preserve a transformação do esqueleto T5.')
    parts=[];max_loss=0.
    for obj in scene.objects:
        if obj.type!='MESH' or obj.hide_render or obj.get('t5_reference',False):continue
        mods=[(m,m.show_viewport) for m in obj.modifiers if m.type=='ARMATURE']
        for m,_ in mods:m.show_viewport=False
        scene.update()
        mesh=None
        try:
            mesh=obj.to_mesh(scene,True,'PREVIEW')
            if any(len(p.vertices)!=3 for p in mesh.polygons):
                bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.triangulate(bm,faces=list(bm.faces));bm.to_mesh(mesh);bm.free();mesh.update()
            mesh.calc_normals_split()
            if not mesh.uv_layers:raise ValueError('Malha sem UV: '+obj.name)
            transform=C.inverted()*obj.matrix_world;normal_matrix=transform.to_3x3().inverted().transposed()
            groups={g.index:g.name for g in obj.vertex_groups};bone_ids={b.name:int(b['t5_index']) for b in rig.data.bones};by_material={}
            for tri in mesh.polygons:
                material=obj.material_slots[tri.material_index].material if tri.material_index<len(obj.material_slots) else None
                if material is None:raise ValueError('Malha sem material: '+obj.name)
                image=next((s.texture.image for s in material.texture_slots if s and s.texture and s.texture.type=='IMAGE' and s.texture.image),None)
                if image is None:raise ValueError('Material sem textura difusa: '+material.name)
                texture=bpy.path.abspath(image.filepath)
                if not os.path.isfile(texture):raise ValueError('Textura ausente: '+texture)
                part=by_material.setdefault(material.name,dict(name=obj.name,texture=texture,alpha='texture' if material.use_transparency else 'opaque',positions=[],normals=[],uv0=[],weights=[],indices=[],faces=[],lookup={}))
                loops=list(tri.loop_indices)
                if transform.to_3x3().determinant()<0:loops.reverse()
                face=[]
                for li in loops:
                    loop=mesh.loops[li];vertex=mesh.vertices[loop.vertex_index];uv=mesh.uv_layers.active.data[li].uv
                    key=(loop.vertex_index,tuple(round(v,6) for v in loop.normal),tuple(uv))
                    if key in part['lookup']:face.append(part['lookup'][key]);continue
                    index=len(part['positions']);part['lookup'][key]=index;face.append(index)
                    weights={}
                    for group in vertex.groups:
                        name=groups.get(group.group)
                        if name in bone_ids and group.weight>0:weights[bone_ids[name]]=weights.get(bone_ids[name],0)+group.weight
                    if not weights:raise ValueError('Vértice sem peso: '+obj.name+' #'+str(vertex.index))
                    ordered=sorted(weights.items(),key=lambda p:-p[1]);total=sum(w for _,w in ordered);kept=ordered[:4];remaining=sum(w for _,w in kept)
                    max_loss=max(max_loss,1-remaining/total)
                    part['indices'].append([i for i,_ in kept]+[0]*(4-len(kept)))
                    part['weights'].append([w/remaining for _,w in kept]+[0]*(4-len(kept)))
                    part['positions'].append(list(transform*vertex.co));part['normals'].append(list((normal_matrix*loop.normal).normalized()))
                    part['uv0'].append([uv.x,1-uv.y])
                part['faces'].append(face)
            for part in by_material.values():part.pop('lookup');parts.append(part)
        finally:
            if mesh:bpy.data.meshes.remove(mesh)
            for m,enabled in mods:m.show_viewport=enabled
            scene.update()
    if not parts:raise ValueError('Nenhuma malha visível para exportar.')
    output=dict(format='T5SkinStudioEdit1',name=data['name'],base_index=data['base_index'],bones=data['bones'],meshes=parts,warnings=list(data.get('warnings',[])))
    if max_loss>1e-6:output['warnings'].append('Redução para quatro pesos: descarte máximo %.2f%%.'%(max_loss*100))
    path=data['edit_output'];temp=path+'.tmp'
    with open(temp,'w',encoding='utf8') as f:json.dump(output,f,ensure_ascii=False)
    os.replace(temp,path)
    scene['t5_last_export']='Salvo para o Studio: '+path
    scene['t5_export_error']=''
    return path


@persistent
def after_save(dummy):
    if 'T5_STUDIO_DATA' not in bpy.data.texts:return
    try:export_edit()
    except Exception as error:
        bpy.context.scene['t5_export_error']=str(error);print('T5 STUDIO EXPORT ERROR:',error)
        with open(metadata()['edit_output']+'.error','w',encoding='utf8') as f:f.write(str(error))
    else:
        error_path=metadata()['edit_output']+'.error'
        if os.path.exists(error_path):os.remove(error_path)


class T5_OT_Save(bpy.types.Operator):
    bl_idname='t5studio.save';bl_label='Salvar para o Studio'
    def execute(self,context):
        try:
            bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath,check_existing=False)
            if context.scene.get('t5_export_error'):raise ValueError(context.scene['t5_export_error'])
            self.report({'INFO'},'Salvo. Clique Recarregar edição no Studio.');return {'FINISHED'}
        except Exception as error:self.report({'ERROR'},str(error));return {'CANCELLED'}


def load_base_reference():
    data=metadata();folder=os.path.join(os.path.dirname(data['edit_output']),'base_t5')
    path=os.path.join(folder,'base_t5.json')
    cached=None
    if os.path.isfile(path):
        with open(path,encoding='utf8') as file:cached=json.load(file)
    if cached is None or cached.get('version',0)<2:
        root=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        python=os.path.join(root,'runtime','python','python.exe')
        if not os.path.isfile(python):python=shutil.which('python') or 'python'
        home=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(data['edit_output']))))
        config=os.path.join(home,'studio.json')
        if not os.path.isfile(config):config=os.path.join(root,'studio.json')
        if not os.path.isfile(config):raise ValueError('studio.json não encontrado; abra o projeto pelo Studio.')
        result=subprocess.run([python,'-m','tools.skins_t5.native','--config',config,'--base',str(data['base_index']),'--output',folder],
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,cwd=root,timeout=180,
                              creationflags=0x08000000 if os.name=='nt' else 0)
        if result.returncode:raise ValueError('Falha ao importar base T5: '+result.stderr[-1200:])
    with open(path,encoding='utf8') as file:base=json.load(file)
    if base['bones']!=data['bones']:raise ValueError('A base não corresponde ao esqueleto deste projeto.')
    return base


class T5_OT_ImportBase(bpy.types.Operator):
    bl_idname='t5studio.import_base';bl_label='Importar base original T5';bl_options={'REGISTER','UNDO'}
    include_accessories=bpy.props.BoolProperty(name='Incluir acessórios de customização',default=False)
    def invoke(self,context,event):return context.window_manager.invoke_props_dialog(self)
    def execute(self,context):
        try:
            if context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
            base=load_base_reference();rig=bpy.data.objects.get('T5_Skeleton')
            if rig is None:raise ValueError('Esqueleto T5 ausente')
            chosen=base['meshes'] if self.include_accessories else [m for m in base['meshes'] if m.get('base_body')]
            if not chosen:raise ValueError('Não foi possível identificar o corpo base; tente incluir os acessórios.')
            existing={obj.get('t5_native_key') for obj in context.scene.objects}
            chosen=[m for m in chosen if m['name']+'|'+m['texture'] not in existing]
            for obj in context.scene.objects:obj.select=False
            add_meshes(chosen,metadata()['bones'],rig,reference=True)
            rig.layers[1]=True;context.scene.layers[1]=True;context.scene.layers[0]=False
            self.report({'INFO'},'Base na camada 2. Separe as peças e use Adicionar partes à skin.');return {'FINISHED'}
        except Exception as error:self.report({'ERROR'},str(error));return {'CANCELLED'}


class T5_OT_UseBaseParts(bpy.types.Operator):
    bl_idname='t5studio.use_base_parts';bl_label='Adicionar partes selecionadas à skin';bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context):return context.mode=='OBJECT' and any(o.type=='MESH' and o.get('t5_reference') for o in context.selected_objects)
    def execute(self,context):
        for obj in context.selected_objects:
            if obj.type=='MESH' and obj.get('t5_reference'):
                obj['t5_reference']=False;obj.layers=[i==0 for i in range(20)]
        context.scene.layers[0]=True;context.scene.layers[1]=False
        self.report({'INFO'},'Partes adicionadas. Remova da skin as áreas substituídas e salve.');return {'FINISHED'}


class T5_PT_Edit(bpy.types.Panel):
    bl_label='Edição de skin T5';bl_space_type='VIEW_3D';bl_region_type='TOOLS';bl_category='T5 Skin Studio'
    def draw(self,context):
        layout=self.layout;layout.operator('t5studio.save',icon='FILE_TICK')
        layout.label('Edite malha, UVs e pesos.')
        layout.label('Preserve o esqueleto nativo.')
        layout.separator();layout.operator('t5studio.import_base',icon='IMPORT')
        layout.operator('t5studio.use_base_parts',icon='MESH_DATA')
        layout.label('Base na camada 2; skin na camada 1.')
        layout.label('Edit Mode: selecione faces e P para separar.')
        layout.label('A base só exporta após adicionar as partes.')
        active=context.active_pose_bone
        if active:
            bone=active.bone;box=layout.box();box.label(bone.get('t5_description',bone.name))
            import textwrap
            for line in textwrap.wrap(bone.get('t5_evidence',''),42):box.label(line)
            for line in textwrap.wrap(bone.get('t5_native_objects',''),42):box.label(line)
        if context.scene.get('t5_export_error'):layout.label(context.scene['t5_export_error'],icon='ERROR')


def register():
    for cls in (T5_OT_Save,T5_OT_ImportBase,T5_OT_UseBaseParts,T5_PT_Edit):bpy.utils.register_class(cls)
    bpy.app.handlers.save_post.append(after_save)


def add_meshes(parts,bones,rig,reference=False):
    scene=bpy.context.scene;created=[]
    for part in parts:
        mesh=bpy.data.meshes.new(part['name']);mesh.from_pydata([list((C*Vector(tuple(p)+(1,)))[:3]) for p in part['positions']],[],part['faces']);mesh.update()
        mesh.uv_textures.new(name='UVMap');uv=mesh.uv_layers[0]
        for loop in mesh.loops:
            u,v=part['uv0'][loop.vertex_index];uv.data[loop.index].uv=(u,1-v)
        for p in mesh.polygons:p.use_smooth=True
        mesh.use_auto_smooth=True;mesh.normals_split_custom_set_from_vertices([list((C.to_3x3()*Vector(n)).normalized()) for n in part['normals']])
        material=bpy.data.materials.new(part['name']);material.diffuse_color=(1,1,1);material.use_shadeless=True
        material.use_transparency=part['alpha']=='texture';material.alpha=0 if material.use_transparency else 1
        image=bpy.data.images.load(part['texture'],check_existing=True);tex=bpy.data.textures.new(part['name'],type='IMAGE');tex.image=image
        slot=material.texture_slots.add();slot.texture=tex;slot.texture_coords='UV';slot.use_map_color_diffuse=True;slot.use_map_alpha=material.use_transparency
        mesh.materials.append(material)
        for face in mesh.uv_textures[0].data:face.image=image
        obj=bpy.data.objects.new(part['name'],mesh);scene.objects.link(obj);obj.parent=rig
        groups=[obj.vertex_groups.new(name=b['name']) for b in bones]
        for vertex,(ids,weights) in enumerate(zip(part['indices'],part['weights'])):
            merged={}
            for i,w in zip(ids,weights):
                if w>0:merged[i]=merged.get(i,0)+w
            for i,w in merged.items():groups[i].add([vertex],w,'REPLACE')
        modifier=obj.modifiers.new('T5 skin weights','ARMATURE');modifier.object=rig
        obj['t5_reference']=reference
        if reference:
            obj.layers=[i==1 for i in range(20)]
            obj['t5_native_key']=part['name']+'|'+part['texture']
        obj.select=True;scene.objects.active=obj;created.append(obj)
    return created


def build(input_file,output):
    with open(input_file,encoding='utf8') as f:data=json.load(f)
    bpy.ops.wm.read_factory_settings(use_empty=True);scene=bpy.context.scene
    arm=bpy.data.armatures.new('T5_Rig');rig=bpy.data.objects.new('T5_Skeleton',arm);scene.objects.link(rig)
    scene.objects.active=rig;rig.select=True;rig.show_x_ray=True;arm.draw_type='STICK'
    bpy.ops.object.mode_set(mode='EDIT');bones=[arm.edit_bones.new(b['name']) for b in data['bones']]
    worlds=[C*Matrix(m) for m in data['worlds']]
    for i,bone in enumerate(bones):
        w=worlds[i];bone.head=w.translation;bone.tail=bone.head+w.col[1].to_3d().normalized()*.035;bone.align_roll(w.col[2].to_3d())
        parent=data['bones'][i]['parent']
        if parent>=0:bone.parent=bones[parent]
        bone.use_connect=False
        bone.layers=[j==(0 if i<=22 or 55<=i<=84 else 1) for j in range(32)]
    bpy.ops.object.mode_set(mode='OBJECT')
    for i,entry in enumerate(data['bones']):
        bone=arm.bones[entry['name']];bone['t5_index']=i
        bone['t5_description']=entry.get('label',entry['name'])
        bone['t5_evidence']=entry.get('evidence','')
        bone['t5_native_objects']=', '.join(entry.get('native_objects',[]))
    data['bind']={str(b['t5_index']):[list(row) for row in b.matrix_local] for b in arm.bones}
    rig.select=False
    add_meshes(data['meshes'],data['bones'],rig)
    if data.get('reference_meshes'):
        add_meshes(data['reference_meshes'],data['bones'],rig,reference=True);rig.layers[1]=True
    has_skin=bool(data['meshes'])
    data.pop('meshes');data.pop('worlds');data.pop('reference_meshes',None);text=bpy.data.texts.new('T5_STUDIO_DATA');text.write(json.dumps(data,ensure_ascii=False))
    text=bpy.data.texts.new('LEIA-ME');text.write('Edite a malha, UVs e pesos. Preserve os ossos nativos.\nCtrl+S exporta edited.t5skin.json quando aberto pelo Studio.\nDepois clique Recarregar edição na ferramenta e converta o mod.\nAo abrir o .blend manualmente, use o script blender279_edit.py para ativar o painel.\n')
    scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=1
    from mathutils import Quaternion
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                space=area.spaces.active;space.viewport_shade='TEXTURED';space.clip_end=100;space.region_3d.view_location=(0,0,.95);space.region_3d.view_distance=3
                space.region_3d.view_rotation=Quaternion((1,0,0),math.pi/2)
    register();bpy.ops.wm.save_as_mainfile(filepath=output,compress=True,check_existing=False)
    if has_skin and scene.get('t5_export_error'):raise RuntimeError(scene['t5_export_error'])


if __name__=='__main__':
    args=sys.argv[sys.argv.index('--')+1:]
    if args[0]=='build':build(args[1],args[2])
    elif args[0]=='resume':register()
