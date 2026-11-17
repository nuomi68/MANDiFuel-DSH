from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rendering import validate_rendering,merge_rendering
from presentation import validate_presentation,validate_delivery,default_controls


class RenderingTests(unittest.TestCase):
    def test_successive_instructions_preserve_scaling_and_field_styles(self):
        first=validate_rendering({'scale':[2,.5,1],'fields':{'T':{'range':[1200,1400]}}})
        second=validate_rendering({'palette':'viridis','fields':{'T':{'palette':'inferno'}}})
        merged=merge_rendering(first,second)
        self.assertEqual(merged['scale'],[2,.5,1]);self.assertEqual(merged['fields']['T'],{'range':[1200,1400],'palette':'inferno'})
        reset=merge_rendering(merged,{'reset':True});self.assertEqual(reset['scale'],[1,1,1]);self.assertEqual(reset['fields'],{})
    def test_arbitrary_valid_colors_and_reverse_are_supported(self):
        style={'palette':[[0,'#123456'],[.3,'#fedcba'],[1,'#000000']],'background':'#ffffff','opacity':.4,'reversePalette':True}
        self.assertEqual(validate_rendering(style),style)
    def test_bad_or_unsupported_instructions_fail_with_feedback(self):
        for style in [{'scale':[0,1,1]},{'scale':[True,1,1]},{'opacity':2},{'palette':'unknown'},{'palette':[[.1,'#000000'],[1,'#ffffff']]},{'background':'url(secret)'},{'fields':{'T':{'range':[1400,1200]}}},{'volumeRendering':True}]:
            with self.subTest(style=style),self.assertRaises(ValueError):validate_rendering(style)
        with self.assertRaisesRegex(ValueError,'变量'):validate_delivery({'rendering':{'fields':{'missing':{'palette':'gray'}}}},{'raw':{'task':{'fields':[{'id':'T'}]}}},'raw')
    def test_controls_accept_numeric_scale_color_and_custom_range(self):
        config=validate_presentation({'controls':[{'id':'scaleX','default':2},{'id':'background','default':'#ff8800'},{'id':'scale','default':'custom'},{'id':'colorMin','default':1200},{'id':'colorMax','default':1400}]})
        self.assertEqual(config['controls'][0]['type'],'number');self.assertEqual(config['controls'][1]['type'],'color')
    def test_default_panel_never_invents_feature_parameters(self):
        model={'shape':'mesh','fields':[{'id':'T'}]}
        def ids(rendering=None):return {c['id'] for c in default_controls(model,[],rendering)}
        self.assertFalse({'scaleX','scaleY','scaleZ'}&ids())
        self.assertFalse({'scaleX','scaleY','scaleZ'}&ids({'scale':[1,1,1]}))
        self.assertFalse({'scaleX','scaleY','scaleZ'}&ids({'scale':[2,1,1]}))
        self.assertFalse({'scaleX','scaleY','scaleZ'}&ids(validate_rendering({'showScaleControls':True})))
        reset=merge_rendering({'scale':[2,1,1],'showScaleControls':True},{'reset':True})
        self.assertFalse({'scaleX','scaleY','scaleZ'}&ids(reset))


if __name__=='__main__':unittest.main()
