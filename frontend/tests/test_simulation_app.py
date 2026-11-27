"""Set MANDIFUEL_APP_TEST_CASE to a completed, registered OFFBEAT rod to replay the solver tests."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
import sys
import unittest
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'lib'))
from mandifuel_app.runtime import Application, read, save_json
from mandifuel_app.thermal_rod import numeric
from mandifuel_app.definition import validate


class ContractTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('MANDIFUEL_SOLID_ROD_TEST_CASE'),'needs a completed solid rod benchmark')
    def test_reuse_solid_rod_and_recover_full_circle_heat_table(self):
        case=Path(os.environ['MANDIFUEL_SOLID_ROD_TEST_CASE']).resolve()
        reference=read(case.parent/'results'/'responses.json')['responses_W']
        with TemporaryDirectory() as store:
            app=Application(case.parent,case.name,store)
            with patch('mandifuel_app.runtime.run_case',side_effect=AssertionError('构建不应启动求解器')):
                state=app.create(dict(title='实心棒热流',parameters=[dict(id='power',label='线功率',binding='linearPower')],
                                      outputs=[dict(id='heat',label='热流',kind='heatFlow')]))
            self.assertEqual([r['id'] for r in state['runs']],['baseline'])
            rows=app.table('heat',['baseline'])['rows']
            for row,key in zip(rows,('fuel_heat_generation','fuel_outward_heat','cladding_inner_received_heat','cladding_outer_loss'),strict=True):
                self.assertAlmostEqual(row['value'],reference[key],places=5)
                self.assertTrue(row['direction'])

    def test_agent_selects_every_binding_and_view(self):
        defaults=dict(linearPower=20000,outerTemperature=573,gapConductance=5000)
        proposal=dict(title='边界试验',parameters=[dict(id='wall',label='壁温',binding='outerTemperature')],
                      outputs=[dict(id='tMin',label='最低温度',kind='statistic',field='T',region='cladding',reduction='min')])
        spec=validate(proposal,defaults)
        self.assertEqual([p['id'] for p in spec['parameters']],['wall'])
        self.assertEqual(spec['components'],[])
        self.assertEqual(spec['parameters'][0]['default'],573)
        with self.assertRaises(ValueError):
            validate({**proposal,'components':[dict(id='t',title='错误引用',type='table',output='unknown')]},defaults)
        with self.assertRaises(ValueError):
            validate({**proposal,'parameters':[]},defaults)
    def test_scope_and_numeric_types(self):
        with TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                Application(folder,'../unrelated',folder)
        for value in (False,'600',float('nan'),0,-10):
            with self.subTest(value=value),self.assertRaises(ValueError):
                numeric(value,'outerTemperature')
        self.assertEqual(numeric(0,'linearPower'),0)


@unittest.skipUnless(os.environ.get('MANDIFUEL_APP_TEST_CASE'),'requires a retained OFFBEAT case')
class SolverReplay(unittest.TestCase):
    def test_candidate_runs_only_with_all_readback_values(self):
        import shutil
        from mandifuel_app.thermal_rod import bind
        src=Path(os.environ['MANDIFUEL_APP_TEST_CASE']).resolve()
        with TemporaryDirectory() as tmp:
            work=Path(tmp)
            shutil.copytree(src,work/'base')
            app=Application(work,'base',work/'applications')
            app.create(dict(title='功率研究',parameters=[dict(id='power',binding='linearPower',label='功率')],
                            outputs=[dict(id='temperature',field='T',kind='field',label='温度')]))
            candidate=work/'candidate'
            for name in app.state()['spec']['templateSha256']:
                (candidate/name).parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(src/name,candidate/name)
            bind(candidate,{'linearPower':24000})
            draft=app.candidate('candidate')
            self.assertEqual(draft['values'],{'power':24000})
            with self.assertRaisesRegex(ValueError,'不一致'):
                app.run(1,uuid4().hex,{'power':16000},'candidate')
            request=uuid4().hex
            run=app.run(1,request,draft['values'],'candidate')
            self.assertEqual((run['status'],run['candidate'],run['inputs']['linearPower']),('completed','candidate',24000))
            bind(candidate,{'linearPower':22000})
            self.assertEqual(app.run(1,request,draft['values'],'candidate')['id'],request)
            with self.assertRaisesRegex(ValueError,'不一致'):
                app.run(1,uuid4().hex,draft['values'],'candidate')
            bind(candidate,{'outerTemperature':700})
            with self.assertRaisesRegex(ValueError,'未开放'):app.candidate('candidate')
            self.assertEqual(len(app.state()['runs']),2)
    def test_recompute_evolve_and_recover(self):
        src=Path(os.environ['MANDIFUEL_APP_TEST_CASE']).resolve()
        with TemporaryDirectory() as store:
            app=Application(src.parent,src.name,store)
            definition=dict(title='验证工况', parameters=[
                dict(id='linearPower',label='线功率',binding='linearPower'),
                dict(id='outerTemperature',label='外壁温度',binding='outerTemperature')],
                outputs=[dict(id='field',label='温度场',kind='field',field='T'),
                         dict(id='minT',label='包壳最低温度',kind='statistic',region='cladding',reduction='min',field='T')])
            first=app.create(definition);base=first['runs'][0]
            params={p['id']:p['default'] for p in first['spec']['parameters']}
            params['linearPower']*=.9
            request=uuid4().hex
            with ThreadPoolExecutor(max_workers=2) as executor:
                records=list(executor.map(lambda _:app.run(1,request,params),range(2)))
            self.assertEqual({r['id'] for r in records},{request})
            later=app.state()['runs'][-1]
            self.assertEqual(later['status'],'completed',later)
            self.assertEqual(len(app.state()['runs']),2)
            self.assertLess(later['peak'],base['peak'])
            with self.assertRaises(ValueError):
                app.run(1,request,{**params,'outerTemperature':params['outerTemperature']+1})
            next_inputs={**params,'outerTemperature':params['outerTemperature']+27}
            wall=app.run(1,uuid4().hex,next_inputs)
            self.assertAlmostEqual(wall['peak']-later['peak'],27,delta=.04)
            self.assertEqual(app.artifact(wall['id'],'result')['wallTemperature'],next_inputs['outerTemperature'])
            self.assertEqual(app.artifact(wall['id'],'raw')['sha256'],app.artifact(wall['id'],'result')['fieldSha256'])
            definition['parameters'].append(dict(id='hGap',label='气隙传热',binding='gapConductance'))
            revised=app.evolve(1,proposal=definition)['spec']
            self.assertEqual(len(revised['parameters'][-1]['bindings']),2)
            with self.assertRaises(ValueError):
                app.evolve(1,components=[])
            params={**next_inputs,'hGap':base['inputs']['gapConductance']*1.3}
            gap=app.run(2,uuid4().hex,params)
            self.assertLess(gap['peak'],wall['peak'])
            self.assertEqual(app.evolve(2,components=[dict(id='history',title='工况结果',type='table',output='minT',scope='history')])['spec']['version'],3)
            with patch('mandifuel_app.runtime.run_case',return_value={'status':'failed','exit_code':1}):
                failed=app.run(3,uuid4().hex,params)
            self.assertEqual(failed['status'],'failed')
            with self.assertRaises(ValueError):
                app.artifact(failed['id'],'field')
            reopened=Application(src.parent,src.name,store)
            self.assertEqual(reopened.state()['runs'][-2],gap)
            rows=reopened.table('minT',[gap['id']])['rows']
            self.assertEqual(rows[0]['hGap'],params['hGap'])
            self.assertEqual(rows[0]['value'],min(p['T'] for p in reopened.artifact(gap['id'],'result')['profile'] if p['region']=='cladding'))
            self.assertEqual(read(app.root/'versions/1.json'),first['spec'])
            self.assertEqual(reopened.artifact('baseline','result')['fuelMaxTemperature'],base['peak'])
            path=app.root/'runs'/failed['id']/'record.json'
            save_json(path,{**failed,'status':'running'})
            self.assertEqual(reopened.state()['runs'][-1]['status'],'interrupted')
