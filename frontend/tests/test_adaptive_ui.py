import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from adaptive_ui import validate_ui,validate_ui_delivery,ui_parameters,load_dataset
from presentation import validate_presentation,validate_delivery
from registry import TaskRegistry

VIEWS={'raw':{'task':{'shape':'mesh','dimensionality':2,'supportsExtrema':True,'fields':[{'id':'T'},{'id':'stress'}]}}}
def plot(ident='plot',field='T'):
    return {'id':ident,'type':'lineChart','title':field,'series':[{'label':field,'source':{'kind':'history','field':field,'statistic':'max'}}]}
def document(root=None,**kwargs):return {'version':1,'mode':'replace','root':root or plot(),**kwargs}

class AdaptiveUITests(unittest.TestCase):
    def test_generated_controls_default_to_settings_and_only_allow_declared_placement(self):
        root={'id':'operations','type':'controls','title':'任意操作组','ids':['mesh']}
        self.assertEqual(validate_ui(document(root))['root'],root)
        for placement in ['settings','inline']:
            self.assertEqual(validate_ui(document({**root,'placement':placement}))['root']['placement'],placement)
        with self.assertRaisesRegex(ValueError,'控件位置'):validate_ui(document({**root,'placement':'sidebar-js'}))

    def test_scientific_marks_axes_heatmaps_and_inline_tables_are_data_defined(self):
        roots=[{'id':'mixed','type':'chart','yAxis':{'scale':'log'},'references':[{'axis':'y','value':.005,'label':'停止容差'}],'series':[{'label':'偏差','mark':'scatter','marker':'square','source':{'kind':'study'},'x':'record','y':'response.error'}]}, {'id':'heat','type':'heatmapChart','source':{'kind':'dataset','dataset':'grid'},'x':'a','y':'b','value':'T','palette':'viridis','showValues':True,'valueDigits':2}, {'id':'results','type':'table','source':{'kind':'study','status':'all'},'columns':[{'id':'response.error','format':'scientific','digits':2}],'sort':{'column':'response.error','direction':'asc'},'highlight':{'column':'response.error','mode':'min'},'pageSize':20}]
        for root in roots:validate_ui(document(root,scope='overview',datasets={'grid':{'file':'grid.json'}}))
        for root in [{**roots[0],'yAxis':{'scale':'log','min':0}},{**roots[0],'series':[{'label':'bad','mark':'code','source':{'kind':'study'}}]},{**roots[2],'columns':[{'id':'x','format':'eval'}]},{**roots[2],'pageSize':10000}]:
            with self.subTest(root=root),self.assertRaises(ValueError):validate_ui(document(root))
        study={'parameters':[],'responses':[{'id':'error','goal':'min'}],'runs':[]}
        validate_ui_delivery(validate_ui(document(roots[0])),{},None,[],study=study)
        with self.assertRaisesRegex(ValueError,'研究'):validate_ui_delivery(validate_ui(document(roots[0])),{},None,[])

    def test_three_charts_are_layout_data_not_three_fixed_features(self):
        ui=document({'id':'plots','type':'grid','columns':3,'children':[plot('a'),plot('b','stress'),plot('c')]})
        config=validate_presentation({'ui':ui});validate_delivery(config,VIEWS,'raw')
        self.assertEqual(config['ui'],ui)
        self.assertEqual(len(ui['root']['children']),3)

    def test_unregistered_components_code_and_unbounded_trees_are_rejected(self):
        cases=[document({'id':'bad','type':'html','text':'<script/>'}),document({**plot(),'onClick':'fetch()'}),document({'id':'r','type':'grid','columns':5,'children':[plot()]}),document({'id':'r','type':'column','children':[plot(),plot()]})]
        node=plot()
        for i in range(10):node={'id':f'n{i}','type':'column','children':[node]}
        cases.append(document(node))
        for ui in cases:
            with self.subTest(ui=ui),self.assertRaises(ValueError):validate_ui(ui)

    def test_fields_and_views_must_actually_exist(self):
        for source in [{'kind':'history','field':'absent'},{'kind':'profile','field':'T','view':'absent'}]:
            ui=document({'id':'p','type':'metric','source':source})
            with self.assertRaisesRegex(ValueError,'不存在|尚未交付'):validate_delivery(validate_presentation({'ui':ui}),VIEWS,'raw')

    def test_point_history_parameters_are_actual_ui_bindings(self):
        ui=document({'id':'p','type':'lineChart','series':[{'label':'测点温度','source':{'kind':'probeHistory','field':'T','position':['p.sampleX','0','0']}}]})
        config=validate_presentation({'ui':ui,'controls':[{'id':'sampleX','type':'number','default':0}]})
        validate_delivery(config,VIEWS,'raw');self.assertEqual(ui_parameters(ui),{'sampleX'})
        with self.assertRaisesRegex(ValueError,'未定义参数'):validate_delivery({'ui':ui},VIEWS,'raw')

    def test_parameter_controls_without_effect_are_still_rejected(self):
        config=validate_presentation({'ui':document(),'controls':[{'id':'unused','type':'number','default':1}]})
        with self.assertRaisesRegex(ValueError,'尚未连接'):validate_delivery(config,VIEWS,'raw')

    def test_controls_and_button_actions_reference_known_parameters_and_fields(self):
        for root in [{'id':'p','type':'controls','ids':['missing']},{'id':'p','type':'button','label':'XY','action':{'type':'view','state':{'field':'absent'}}},{'id':'p','type':'button','label':'运行','action':{'type':'shell','command':'anything'}}]:
            with self.subTest(root=root),self.assertRaises(ValueError):
                ui=validate_ui(document(root));validate_ui_delivery(ui,VIEWS,'raw',[])
        ui=validate_ui(document({'id':'b','type':'button','label':'XY','action':{'type':'view','state':{'cameraView':'xy'}}}))
        validate_ui_delivery(ui,VIEWS,'raw',[])

    def test_multiple_main_model_mounts_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'一个主模型'):validate_ui(document({'id':'r','type':'row','children':[{'id':'a','type':'model'},{'id':'b','type':'model'}]}))

    def test_dataset_sources_are_declared_finite_and_inside_workspace(self):
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder);(work/'curve.json').write_text(json.dumps({'columns':['t','T'],'rows':[{'t':0,'T':300},{'t':1,'T':320}]}))
            ui=document({'id':'p','type':'table','source':{'kind':'dataset','dataset':'curve'}},datasets={'curve':{'file':'curve.json'}})
            validate_ui_delivery(validate_ui(ui),{},None,[],work)
            self.assertEqual(load_dataset(work,{'file':'curve.json'})['rows'][1]['T'],320)
            for path in ['../escape.json','/tmp/escape.json','x.html']:
                bad=copy.deepcopy(ui);bad['datasets']['curve']['file']=path
                with self.assertRaises(ValueError):validate_ui(bad)
            (work/'curve.json').write_text('{"columns":["t"],"rows":[{"t":NaN}]}')
            with self.assertRaisesRegex(ValueError,'有限数字'):load_dataset(work,{'file':'curve.json'})

    def test_agent_plans_are_rejected_instead_of_becoming_empty_successful_updates(self):
        with self.assertRaisesRegex(ValueError,'未知属性.*可执行配置'):
            validate_presentation({'taskClass':'display','status':'needs_tool_access','blocker':'请人工执行'})

    def test_csv_tables_keep_real_values_missing_cells_and_identifiers(self):
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder);path=work/'powers.csv'
            path.write_text('\ufeffid,label,value_W,note\n001,"燃料,体积源",0,\n002,外壁,3.00002e2,原始结果\n')
            original=path.read_bytes()
            ui=document({'id':'p','type':'table','source':{'kind':'dataset','dataset':'powers'}},datasets={'powers':{'file':'powers.csv'}})
            validate_ui_delivery(validate_ui(ui),{},None,[],work)
            table=load_dataset(work,{'file':'powers.csv'})
            self.assertEqual(table['rows'][0],{'id':'001','label':'燃料,体积源','value_W':0,'note':None})
            self.assertEqual(table['rows'][1]['value_W'],300.002)
            self.assertEqual(path.read_bytes(),original)
            mapped=document({'id':'m','type':'table','source':{'kind':'dataset','dataset':'powers'}},datasets={'powers':{'file':'powers.csv','columns':['id',{'id':'P','path':'value_W','unit':'W'}]}})
            clean=validate_ui(mapped);self.assertNotIn('rows',mapped['datasets']['powers']);self.assertEqual(clean['datasets']['powers']['rows'],'rows')
            table=load_dataset(work,clean['datasets']['powers']);self.assertEqual(table['rows'][1]['P'],300.002)
            with self.assertRaisesRegex(ValueError,'CSV 数据列不存在'):load_dataset(work,{'file':'powers.csv','rows':'rows','columns':[{'id':'invented'}]})
            for content in ['x,x\n1,2\n','x,y\n1\n','x\nNaN\n','x\n1e999\n']:
                path.write_text(content)
                with self.subTest(content=content),self.assertRaises(ValueError):load_dataset(work,{'file':'powers.csv'})

    def test_regular_terminal_records_map_to_charts_without_rewriting_source(self):
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder);raw={'target':2,'rows':[{'E':81.25,'interval':[75,87.5],'u':None}]}
            path=work/'report.json';path.write_text(json.dumps(raw));original=path.read_bytes()
            spec={'file':'report.json','rows':'rows','columns':[{'id':'E','unit':'GPa'},{'id':'lo','path':'interval.0'},{'id':'hi','path':'interval.1'},{'id':'u'}]}
            ui=document({'id':'interval','type':'intervalChart','series':[{'label':'区间','source':{'kind':'dataset','dataset':'report'},'xLow':'lo','xHigh':'hi','y':'E'}]},datasets={'report':spec})
            validate_ui_delivery(validate_ui(ui),{},None,[],work);table=load_dataset(work,spec)
            self.assertEqual(table['rows'],[{'E':81.25,'lo':75,'hi':87.5,'u':None}]);self.assertEqual(path.read_bytes(),original)

    def test_generated_components_validate_all_referenced_columns_before_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder);(work/'data.json').write_text(json.dumps({'columns':['x','value'],'rows':[]}))
            source={'kind':'dataset','dataset':'data'}
            roots=[{'id':'m','type':'metric','source':source,'column':'absent'},
                   {'id':'c','type':'chart','series':[{'label':'invalid','source':source,'y':'absent'}]},
                   {'id':'h','type':'heatmapChart','source':source,'x':'x','y':'value','value':'absent'},
                   {'id':'t','type':'table','source':source,'columns':['absent']},
                   {'id':'s','type':'table','source':source,'sort':{'column':'absent','direction':'asc'}},
                   {'id':'b','type':'table','source':source,'highlight':{'column':'absent','mode':'min'}},
                   {'id':'f','type':'table','source':{**source,'filter':[{'column':'absent','op':'eq','value':1}]}}]
            for root in roots:
                with self.subTest(root=root),self.assertRaisesRegex(ValueError,'absent.*实际列'):
                    validate_ui_delivery(validate_ui(document(root,datasets={'data':{'file':'data.json'}})),{},None,[],work)
            # An existing numeric column with no observations is valid, not a fabricated zero.
            validate_ui_delivery(validate_ui(document({'id':'m','type':'metric','source':source,'column':'value'},datasets={'data':{'file':'data.json'}})),{},None,[],work)
        study={'parameters':[{'id':'E'}],'responses':[{'id':'error','goal':'min'}],'runs':[]}
        best={'kind':'study','best':'error','select':'best'}
        validate_ui_delivery(validate_ui(document({'id':'m','type':'metric','source':best,'column':'parameter.E'})),{},None,[],study=study)
        with self.assertRaisesRegex(ValueError,'best.E.*实际列'):
            validate_ui_delivery(validate_ui(document({'id':'m','type':'metric','source':best,'column':'best.E'})),{},None,[],study=study)
        with self.assertRaisesRegex(ValueError,'statusCode'):
            validate_ui(document({'id':'t','type':'table','source':{'kind':'study','filter':[{'column':'status','op':'eq','value':'completed'}]}}))
        for source in [{'kind':'study','select':'best'},{'kind':'study','select':'newest','best':'error'},{'kind':'study','select':'best','best':'error','status':'failed'}]:
            with self.subTest(source=source),self.assertRaises(ValueError):validate_ui(document({'id':'t','type':'table','source':source}))

    def test_dataset_run_links_require_an_explicit_real_study_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder);path=work/'data.json';path.write_text(json.dumps({'columns':['case','x','value'],'rows':[{'case':'runA','x':1,'value':2}]}));original=path.read_bytes()
            source={'kind':'dataset','dataset':'data','runId':'case'}
            ui=validate_ui(document({'id':'p','type':'chart','series':[{'label':'real','source':source}]},datasets={'data':{'file':'data.json'}}))
            study={'parameters':[],'responses':[],'runs':[{'id':'runA'}]}
            validate_ui_delivery(ui,{},None,[],work,study);self.assertEqual(path.read_bytes(),original)
            for current in [None,{**study,'runs':[{'id':'other'}]}]:
                with self.subTest(study=current),self.assertRaisesRegex(ValueError,'工况关联'):validate_ui_delivery(ui,{},None,[],work,current)
            ui['root']['series'][0]['source']['runId']='missing'
            with self.assertRaisesRegex(ValueError,'不存在的数据列'):validate_ui_delivery(ui,{},None,[],work,study)

    def test_aside_is_a_full_component_tree_and_images_are_declared_local_files(self):
        import base64
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder);r=TaskRegistry(work/'tasks')
            try:
                task=r.prepare('补充面板');ident=task['task']['id'];workspace=Path(task['workspace']);(workspace/'plot.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGgkAAAAASUVORK5CYII='))
                root={'id':'primary','type':'text','text':'主区'};aside={'id':'supplement','type':'tabs','children':[{'id':'note','type':'text','title':'解读','text':'已有记录的结论'},{'id':'figure','type':'image','file':'plot.png','alt':'验证用像素图','caption':'组件验证，不是物理结果'}]};ui=document(root,aside=aside)
                r.dashboard.publish(ident,{'ui':ui});self.assertEqual(r.dashboard.ui_image(ident,'plot.png').read_bytes(),(workspace/'plot.png').read_bytes());self.assertIn('figure',[n['id'] for n in __import__('adaptive_ui').walk_ui(ui)])
                with self.assertRaisesRegex(ValueError,'尚未声明'):r.dashboard.ui_image(ident,'other.png')
                for file in ['../outside.png','/tmp/plot.png','plot.svg']:
                    bad=copy.deepcopy(ui);bad['aside']['children'][1]['file']=file
                    with self.assertRaises(ValueError):validate_ui(bad)
                duplicate=copy.deepcopy(ui);duplicate['aside']['children'][0]['id']='primary'
                with self.assertRaisesRegex(ValueError,'唯一'):validate_ui(duplicate)
                (workspace/'plot.png').write_text('not an image')
                with self.assertRaisesRegex(ValueError,'格式'):validate_ui_delivery(validate_ui(ui),{},None,[],workspace)
            finally:r.close()

    def test_dynamic_dataset_publish_read_observe_clear_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'tasks';r=TaskRegistry(root)
            try:
                prepared=r.prepare('动态图表');ident=prepared['task']['id'];work=Path(prepared['workspace']);(work/'curve.json').write_text(json.dumps({'columns':['t','T'],'rows':[{'t':0,'T':300}]}))
                ui=document({'id':'p','type':'lineChart','series':[{'label':'T','source':{'kind':'dataset','dataset':'curve'},'x':'t','y':'T'}]},datasets={'curve':{'file':'curve.json'}})
                before=r.snapshot(ident)['task']['modelVersion'];r.dashboard.publish(ident,{'ui':ui})
                task=r.snapshot(ident)['task'];self.assertEqual(task['modelVersion'],before);self.assertIn('curve.json',[f['path'] for f in r.snapshot(ident)['files']])
                self.assertEqual(r.dashboard.ui_dataset(ident,'curve')['rows'][0]['T'],300)
                revision=task['presentation']['uiRevision']
                with self.assertRaisesRegex(ValueError,'版本'):r.dashboard.ui_dataset(ident,'curve',revision-1)
                self.assertEqual(r.dashboard.ui_dataset(ident,'curve',revision)['rows'][0]['T'],300)
                original=r.dashboard.inspect(ident)['revision']
                self.assertFalse(r.dashboard.ui_state(ident,{'revision':revision-1,'panels':[],'errors':[]})['observed'])
                r.dashboard.ui_state(ident,{'revision':revision,'panels':['p'],'errors':[]});self.assertEqual(r.dashboard.inspect(ident)['revision'],original)
                r.dashboard.ui_state(ident,{'revision':revision,'panels':['p'],'errors':[{'id':'p','message':'列不存在'}]});self.assertNotEqual(r.dashboard.inspect(ident)['revision'],original)
                self.assertIn('lineChart',r.dashboard.inspect(ident)['uiCapabilities']['components'])
            finally:r.close()
            r=TaskRegistry(root)
            try:
                self.assertEqual(r.snapshot(ident)['task']['presentation']['ui'],ui)
                r.dashboard.publish(ident,{'ui':None});self.assertIsNone(r.snapshot(ident)['task']['presentation']['ui'])
                with self.assertRaises(ValueError):r.dashboard.ui_dataset(ident,'curve')
            finally:r.close()

if __name__=='__main__':unittest.main()
