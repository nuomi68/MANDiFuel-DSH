import sys,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'skills/extract-offbeat-results/scripts'))
import result_api

SOURCE=Path(__file__).resolve().parent/'fixtures/radial-52'

class ResultHistoryCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.case=Path(self.temp.name)/'case'
        for name in ['constant','system']:shutil.copytree(SOURCE/name,self.case/name)
        for t in ['1','2','3']:
            (self.case/t).mkdir();shutil.copy2(SOURCE/'1/T',self.case/t/'T')
    def tearDown(self):self.temp.cleanup()
    def scaled_points(self,target):
        points=result_api._backend.parse_points(self.case/'constant/polyMesh/points')
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text('FoamFile { version 2.0; format ascii; class vectorField; object points; }\n'+str(len(points))+'\n(\n'+'\n'.join('('+' '.join(str(2*v) for v in p)+')' for p in points)+'\n)\n')
    def test_static_history_reuses_geometry_and_matches_individual_reads(self):
        expected=[result_api.read_field(self.case,'T',time=t,include_volumes=True) for t in ['1','2','3']]
        with patch.object(result_api._backend,'reconstruct_poly_mesh_geometry',wraps=result_api._backend.reconstruct_poly_mesh_geometry) as reconstruct:
            actual=result_api.read_field(self.case,'T',time='all',include_volumes=True)
        self.assertEqual(tuple(expected),actual);self.assertEqual(reconstruct.call_count,1)
    def test_moving_mesh_uses_each_time_bound_geometry(self):
        self.scaled_points(self.case/'2/polyMesh/points')
        a,b,c=result_api.read_field(self.case,'T',time='all',include_volumes=True)
        self.assertEqual(a.values,b.values);self.assertEqual(b.coordinates,c.coordinates)
        for p,q in zip(a.coordinates,b.coordinates):
            for x,y in zip(p,q):self.assertAlmostEqual(y,2*x,places=12)
        for x,y in zip(a.volumes,b.volumes):self.assertAlmostEqual(y/x,8,places=8)
    def test_in_place_mesh_change_invalidates_the_local_history_cache(self):
        frames=result_api.iter_fields(self.case,'T',time='all',include_volumes=True);a=next(frames)
        self.scaled_points(self.case/'constant/polyMesh/points');b=next(frames)
        self.assertNotEqual(a.coordinates,b.coordinates)
        for x,y in zip(a.volumes,b.volumes):self.assertAlmostEqual(y/x,8,places=8)
        self.assertEqual(result_api.read_field(self.case,'T',time='1',include_volumes=True).coordinates,b.coordinates)
