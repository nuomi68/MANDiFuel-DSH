"""Versioned source snapshots and time-bound finite-volume geometry."""
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import sys

from .inputs import Unavailable, dictionary

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'skills/extract-offbeat-results/scripts'))
import openfoam_parser as foam
import result_api

MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024


def stamp(path):
    s = path.stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


class Sources:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve(strict=True)
        self.records = {}; self.bytes = {}; self.total = 0

    def path(self, path):
        path = Path(path)
        if not path.is_absolute(): path = self.workspace/path
        if not path.is_relative_to(self.workspace) or '..' in path.relative_to(self.workspace).parts: raise Unavailable('证据路径越过工作区')
        # Reject symlinks even if their current destination is inside the workspace.
        if any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(self.workspace)):
            raise Unavailable('证据不能通过符号链接读取')
        if not path.resolve().is_relative_to(self.workspace): raise Unavailable('证据路径越过工作区')
        return path

    def read(self, path, role='原始输入或场文件'):
        path = self.path(path); name = str(path.relative_to(self.workspace))
        if name in self.bytes: return self.bytes[name]
        before = stamp(path)
        if before[2] > MAX_FILE or self.total + before[2] > MAX_TOTAL: raise Unavailable('原始证据超过本轮读取上限')
        parts=path.relative_to(self.workspace).parts
        fd=os.open(self.workspace,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                next_fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=next_fd
            handle=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
            with os.fdopen(handle,'rb') as stream:
                st=os.fstat(stream.fileno())
                if [st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns]!=before:raise Unavailable('源文件身份发生变化')
                data=stream.read(MAX_FILE+1)
                if len(data)>MAX_FILE:raise Unavailable('源文件超过读取上限')
        finally:os.close(fd)
        if stamp(path) != before: raise Unavailable('原始文件正在更新，请等待稳定保存')
        self.total += len(data); self.bytes[name] = data
        self.records[name] = {'id':hashlib.sha256(name.encode()).hexdigest()[:16], 'path':name,
                              'sha256':hashlib.sha256(data).hexdigest(), 'bytes':len(data), 'stamp':before, 'role':role}
        return data

    def text(self, path, role='原始输入或场文件'):
        try: return self.read(path, role).decode('ascii')
        except UnicodeDecodeError: raise Unavailable('当前核查只支持 ASCII 原始输入与场') from None

    def json(self, path):
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise Unavailable('执行回执存在重复字段：'+key)
                result[key]=value
            return result
        return json.loads(self.read(path, '原生执行回执'),object_pairs_hook=unique)

    def unchanged(self):
        for name, record in self.records.items():
            try:
                if stamp(self.path(name)) != record['stamp']: return False
            except (OSError, ValueError): return False
        return True


def vector_length(p): return math.sqrt(sum(x*x for x in p))
def dot(a, b): return sum(x*y for x, y in zip(a, b))


class Case:
    def __init__(self, case, workspace=None, time='latest'):
        raw = Path(case).absolute()
        self.sources = Sources(workspace or raw.parent)
        self.root = self.sources.path(raw)
        self.relative = str(self.root.relative_to(self.sources.workspace)) or '.'
        times = result_api.list_times(self.root)
        self.time = times[-1] if time == 'latest' else str(time)
        if self.time not in times: raise Unavailable('请求的保存时刻不存在')
        self.fields = {}; self._geometry = None; self._dicts = {}

    def has(self, relative): return self.sources.path(self.root/relative).is_file()

    def text(self, relative, role='原始输入或场文件'): return self.sources.text(self.root/relative, role)

    def inputs(self, relative):
        if relative not in self._dicts: self._dicts[relative] = dictionary(self.text(relative, '计算输入'))
        return self._dicts[relative]

    def field(self, name, *, time=None, dimensions=None, kind=None):
        time = time or self.time; key = (time, name)
        if key not in self.fields:
            parsed = foam.parse_field_text(self.text(f'{time}/{name}', '原始保存场'), source_path=f'{time}/{name}')
            if parsed.object_name != name: raise Unavailable('场对象名与文件名不符：' + name)
            values = tuple(tuple(float(v) for v in row) for row in foam.expand_internal_field(parsed, len(self.geometry['volumes'])))
            if any(not math.isfinite(v) for row in values for v in row): raise Unavailable('场包含非有限数值')
            self.fields[key] = (parsed, values)
        parsed, values = self.fields[key]
        if dimensions is not None and tuple(parsed.dimensions) != tuple(map(Decimal, dimensions)):
            raise Unavailable('场量纲不符合核查定义：' + name)
        if kind is not None and parsed.field_kind != kind: raise Unavailable('场类型不符合核查定义：' + name)
        return values

    def boundary(self, name, patch, *, dimensions=None):
        p = self.geometry['patches'][patch]
        values = foam.parse_boundary_values_text(self.text(f'{self.time}/{name}', '原始边界场'),
                  patch_name=patch, expected_count=p['count'], source_path=f'{self.time}/{name}')
        if dimensions is not None and tuple(values.dimensions) != tuple(map(Decimal, dimensions)):
            raise Unavailable('边界场量纲不符合核查定义：' + name)
        return tuple(tuple(float(v) for v in row) for row in values.values)

    @property
    def geometry(self):
        if self._geometry is not None: return self._geometry
        binding = result_api.describe_mesh(self.root, time=self.time)['primitive_sources']
        def text(name): return self.text(binding[name], '时刻绑定网格：' + name)
        points = foam.parse_points_text(text('points'))
        faces = foam.parse_faces_text(text('faces'))
        owner = foam.parse_label_list_text(text('owner'), expected_object='owner')
        neighbour = foam.parse_label_list_text(text('neighbour'), expected_object='neighbour')
        if max(owner, default=0) > 200000: raise Unavailable('核查网格超过 200000 个单元')
        geometry = foam.reconstruct_poly_mesh_geometry(points, faces, owner, neighbour)
        centres = [tuple(float(v) for v in row) for row in geometry.cell_centres]
        volumes = [float(v) for v in geometry.cell_volumes]
        fp = [foam._face_centre_and_area(points, face, face_label=i) for i, face in enumerate(faces)]
        face_centres = [tuple(float(v) for v in pair[0]) for pair in fp]
        area_vectors = [tuple(float(v) for v in pair[1]) for pair in fp]
        tokens = foam._ascii_tokens(text('boundary'), 'boundary')
        cursor, count = foam._counted_list_cursor(tokens, 'boundary'); patches = {}
        for _ in range(count):
            name = cursor.take().text.strip('"'); opening = cursor.index; cursor.expect('{')
            closing = foam._matching_index(tokens, opening, '{', '}', 'boundary')
            n = foam._unique_integer_entry(tokens, opening+1, closing, 'nFaces', 'boundary')
            start = foam._unique_integer_entry(tokens, opening+1, closing, 'startFace', 'boundary')
            kind = foam._token_entry(tokens, opening+1, closing, 'type', 'boundary', required=True)
            if name in patches or n < 0 or start < len(neighbour) or start+n > len(faces): raise Unavailable('边界拓扑无效')
            patches[name] = {'count':n, 'start':start, 'type':kind, 'faces':list(range(start, start+n))}
            cursor.index = closing+1
        foam._finish_counted_list(cursor)
        zones = {}
        if 'cellZones' in binding:
            zones = {z.name:list(z.cell_labels) for z in foam.parse_cell_zones_text(text('cellZones'))}
        self._geometry = {'points':[tuple(float(v) for v in p) for p in points], 'faces':faces, 'owner':owner,
                         'centres':centres, 'volumes':volumes, 'faceCentres':face_centres,
                         'areas':area_vectors, 'patches':patches, 'zones':zones, 'binding':binding}
        return self._geometry
