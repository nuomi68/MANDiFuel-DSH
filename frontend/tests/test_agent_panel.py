from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent_panel import validate_parameter,validate_program,expression_parameters,parameter_state,check_program_values,validate_view_state
from presentation import validate_presentation,validate_delivery


class AgentPanelTests(unittest.TestCase):
    def test_typed_view_constants_and_dynamic_bindings_work_together(self):
        program=validate_program({'options':{'cameraView':'xz','aspectMode':'fit','mesh':'p.showGrid'}})
        result=check_program_values(program,{'showGrid':False})
        self.assertEqual(result['options'],{'cameraView':'xz','aspectMode':'fit','mesh':False})
        self.assertEqual(expression_parameters(program['options']['aspectMode']),set())
    def test_literal_colors_are_normalized_without_allowing_code(self):
        program=validate_program({'style':{'background':'#FFFFFF'},'annotations':[{'id':'point','type':'point','position':['0','0','0'],'color':'#12ABCD'}]})
        check_program_values(program,{})
        self.assertEqual(expression_parameters(program['annotations'][0]['color']),set())
        with self.assertRaises(ValueError):validate_program({'style':{'background':'#FFFFFF; fetch("x")'}})
    def test_program_references_can_bind_controls_that_reuse_legacy_names(self):
        config=validate_presentation({'controls':[{'id':'mesh'},{'id':'cameraView'}],'rendering':{'program':{'options':{'mesh':'p.mesh','cameraView':'p.cameraView'}}}})
        self.assertTrue(all(c.get('parameter') for c in config['controls']));self.assertEqual(config['controls'][0]['default'],False);validate_delivery(config,{'raw':{'task':{'shape':'mesh'}}},'raw')
        plain=validate_presentation({'controls':[{'id':'mesh'}]});self.assertFalse(plain['controls'][0].get('parameter',False))
    def test_one_shot_view_requests_cannot_silently_lose_to_parameter_bindings(self):
        config=validate_presentation({'controls':[{'id':'orientation','type':'select','label':'方向','default':'xz','options':[{'value':'xz','label':'XZ'},{'value':'xy','label':'XY'}]}],'rendering':{'program':{'options':{'cameraView':'p.orientation'}}},'viewState':{'cameraView':'xy'}})
        with self.assertRaisesRegex(ValueError,'冲突'):validate_delivery(config,{'raw':{'task':{'shape':'mesh'}}},'raw')
        config['parameterValues']={'orientation':'xy'};validate_delivery(config,{'raw':{'task':{'shape':'mesh'}}},'raw')
    def test_agent_can_define_unregistered_parameter_ids(self):
        config=validate_presentation({'panelTitle':'形状尺寸','controls':[{'id':'upperBase','type':'number','label':'上底','unit':'mm','default':2,'min':.1,'group':'外形'},{'id':'lowerBase','type':'range','label':'下底','default':6,'min':.1,'max':10}],'rendering':{'program':{'vertex':['x*p.upperBase/p.lowerBase','y','z']}}})
        self.assertTrue(all(c['parameter'] for c in config['controls']));validate_delivery(config,{'raw':{'task':{'shape':'mesh'}}},'raw')
        with self.assertRaisesRegex(ValueError,'未定义参数'):validate_delivery({**config,'controls':config['controls'][:1]},{'raw':{'task':{'shape':'mesh'}}},'raw')
    def test_expression_language_rejects_code_and_private_access(self):
        self.assertEqual(expression_parameters('centerX+(x-centerX)*p.width/sizeX'),{'width'})
        for source in ['__import__("os")','p.__class__','p.width.real','x[0]','[x for x in y]','open("secret")','getattr(p,"width")','"a" "b"','"""a"""']:
            with self.subTest(source=source),self.assertRaises(ValueError):expression_parameters(source)
    def test_parameter_values_preserve_user_edits_and_accept_explicit_agent_updates(self):
        controls=[validate_parameter({'id':'someNewLength','type':'number','label':'长度','default':2,'min':1,'max':10})]
        old={'controls':controls,'parameterValues':{'someNewLength':5}}
        self.assertEqual(parameter_state(old,{'parameterValues':{'someNewLength':7}}),{'someNewLength':7})
        changed=[{**controls[0],'label':'新的长度标签'}];self.assertEqual(parameter_state(old,{'controls':changed}),{'someNewLength':5})
        with self.assertRaises(ValueError):parameter_state(old,{'parameterValues':{'someNewLength':0}})
    def test_parameter_schema_rejects_unsafe_ids_and_bad_defaults(self):
        for control in [{'id':'__proto__','type':'number'},{'id':'new','type':'executeScript'},{'id':'new','type':'number','default':float('nan')},{'id':'new','type':'number','default':2,'min':3}]:
            with self.subTest(control=control),self.assertRaises(ValueError):validate_parameter(control)
    def test_bad_math_is_reported_before_publishing_a_display_program(self):
        with self.assertRaisesRegex(ValueError,'不匹配'):check_program_values({'vertex':['x/p.width','y','z']},{'width':0})
        with self.assertRaisesRegex(ValueError,'数量'):validate_program({'vertex':['clamp(x,0)','y','z']})
        check_program_values({'style':{'palette':'select(p.warm,"inferno","viridis")'}},{'warm':True})

    def test_options_field_styles_and_annotations_share_arbitrary_parameters(self):
        controls=[{'id':key,'type':kind,'default':value} for key,kind,value in [('targetTime','number',10),('upperLimit','number',500),('showPoint','toggle',True),('pointX','number',0)]]
        program={'options':{'time':'p.targetTime','extrema':'p.showPoint'},'fields':{'T':{'range':['100','p.upperLimit'],'palette':'"inferno"'}},'annotations':[{'id':'sample','type':'probe','position':['p.pointX','0','0'],'visible':'p.showPoint','field':'T'}]}
        config=validate_presentation({'controls':controls,'rendering':{'program':program}})
        views={'raw':{'task':{'shape':'mesh','fields':[{'id':'T'}],'supportsExtrema':True,'supportsSlice':True}}}
        validate_delivery(config,views,'raw')
        self.assertEqual(check_program_values(validate_program(program),{'targetTime':10,'upperLimit':500,'showPoint':True,'pointX':0})['options']['time'],10)
        with self.assertRaisesRegex(ValueError,'下限'):check_program_values(program,{'targetTime':10,'upperLimit':50,'showPoint':True,'pointX':0})
        with self.assertRaisesRegex(ValueError,'字段'):validate_delivery(validate_presentation({'viewState':{'field':'absent'}}),views,'raw')
        with self.assertRaisesRegex(ValueError,'拓扑'):validate_delivery(validate_presentation({'viewState':{'displayMode':'slice'}}),{'raw':{'task':{'shape':'mesh','supportsSlice':False}}},'raw')

    def test_one_shot_view_directives_validate_types_ranges_and_actual_views(self):
        self.assertEqual(validate_view_state({'view':'raw','yaw':90,'time':10,'mesh':True})['yaw'],90)
        for state in [{'cameraView':[]},{'zoom':0},{'time':float('nan')},{'mesh':1},{'execute':'script'}]:
            with self.subTest(state=state),self.assertRaises(ValueError):validate_view_state(state)
        with self.assertRaisesRegex(ValueError,'尚未交付'):validate_delivery({'viewState':{'view':'absent'}},{'raw':{'task':{'shape':'mesh'}}},'raw')


if __name__=='__main__':unittest.main()
