import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from axisymmetric import revolve_mesh,dimensionality
from presentation import validate_delivery,validate_presentation,requested_delivery


def wedge(gap=False):
    points=[];faces=[];owners=[];centres=[]
    rectangles=[(1,2,0,1),(3,4,0,1)] if gap else [(1,2,0,1),(1,2,1,2)]
    for phi in [-.02,.02]:
        for cell,(r,s,z,zz) in enumerate(rectangles):
            start=len(points);points.extend([[x*math.cos(phi),x*math.sin(phi),y] for x,y in [(r,z),(s,z),(s,zz),(r,zz)]])
            faces.append(list(range(start,start+4)));owners.append(cell)
    for r,s,z,zz in rectangles:centres.append([(r+s)/2,0,(z+zz)/2])
    patches=[SimpleNamespace(name=n,patch_type='wedge',start_face=i*2,n_faces=2) for i,n in enumerate(['front','back'])]
    return points,faces,owners,patches,centres


class AxisymmetricTests(unittest.TestCase):
    def test_sweep_preserves_cell_mapping_and_meridional_gap(self):
        mesh=revolve_mesh(*wedge(gap=True),angle=270)
        self.assertEqual(set(mesh['cells']),{0,1});self.assertEqual(len(mesh['cellCenters']),2)
        self.assertNotIn('cellEdges',mesh)
        self.assertEqual(mesh['reconstruction']['angle'],270)
        for x,y,z in mesh['points']:
            self.assertTrue(any(abs(math.hypot(x,y)-r)<1e-10 for r in [1,2,3,4]))
            self.assertFalse(x>1e-10 and y>1e-10,'the omitted quarter must stay open')
    def test_full_turn_closes_and_wrong_axis_or_planar_mesh_is_rejected(self):
        mesh=revolve_mesh(*wedge(),angle=360);self.assertGreater(len(mesh['triangles']),0)
        with self.assertRaisesRegex(ValueError,'旋转轴'):revolve_mesh(*wedge(),axis='x')
        data=wedge();data[3][0].patch_type='empty'
        with self.assertRaisesRegex(ValueError,'wedge'):revolve_mesh(*data)
        for value in [0,361,float('nan'),True]:
            with self.assertRaises(ValueError):revolve_mesh(*wedge(),angle=value)
    def test_collapsed_axis_face_roundoff_does_not_reduce_dimension(self):
        points,faces,owners,patches,centres=wedge()
        start=len(points);points.extend([[0,0,0],[1e-10,0,0],[1e-10,0,1],[0,0,1]])
        faces.append(list(range(start,start+4)));patches.append(SimpleNamespace(name='axis',patch_type='empty',start_face=4,n_faces=1))
        self.assertEqual(dimensionality(points,faces,patches)[0],2)


class DeliveryValidationTests(unittest.TestCase):
    def test_camera_or_text_cannot_satisfy_reconstruction_requirement(self):
        config=validate_presentation({'deliveryRequirements':{'reconstruction':'axisymmetric-revolve','angle':270},'progress':{'summary':'完成','stages':[{'id':'render','label':'渲染','status':'done'}]}})
        with self.assertRaisesRegex(ValueError,'默认视图'):validate_delivery(config,{'raw':{'task':{'shape':'mesh'}}},'raw')
        views={'raw':{'task':{'shape':'mesh'}},'revolve':{'task':{'shape':'mesh','supportsExtrema':True,'reconstruction':{'type':'axisymmetric-revolve','axis':'z','angle':270}}}}
        validate_delivery(config,views,'revolve')
        with self.assertRaisesRegex(ValueError,'角度'):validate_delivery({**config,'deliveryRequirements':{'reconstruction':'axisymmetric-revolve','angle':180}},views,'revolve')
    def test_extrema_completion_needs_real_positions_and_enabled_control(self):
        config=validate_presentation({'deliveryRequirements':{'extrema':True},'progress':{'summary':'完成','stages':[{'id':'render','label':'渲染','status':'done'}]}})
        views={'raw':{'task':{'shape':'mesh','supportsExtrema':True}}}
        with self.assertRaisesRegex(ValueError,'极值'):validate_delivery(config,views,'raw')
        config['controls']=validate_presentation({'controls':[{'id':'extrema','default':True}]})['controls'];validate_delivery(config,views,'raw')
        with self.assertRaisesRegex(ValueError,'棒形'):validate_delivery(validate_presentation({'controls':[{'id':'axialScale'}]}),views,'raw')
    def test_explicit_followup_requirements_are_exposed(self):
        self.assertEqual(requested_delivery('三维渲染，旋转 3/4 圈，标注最大最小值'),{'reconstruction':'axisymmetric-revolve','angle':270,'extrema':True})
        self.assertEqual(requested_delivery('切换到三维视角'),{})
    def test_extrema_are_optional_and_cancellation_overrides_an_earlier_request(self):
        for request in ['不要标注最大最小值','最大最小值也不是必须渲染的','标注最大最小值；取消极值标注']:
            self.assertEqual(requested_delivery(request),{'extrema':False})
        self.assertEqual(requested_delivery('不用改颜色，标注最大最小值'),{'extrema':True})
        self.assertEqual(requested_delivery('提取最大最小值并保存结果表'),{})


if __name__=='__main__':unittest.main()
