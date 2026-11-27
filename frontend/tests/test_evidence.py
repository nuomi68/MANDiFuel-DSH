"""Synthetic numerical fixtures test evidence; none claims a solver result."""
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'lib'),str(ROOT/'frontend')]
from mandifuel_verify import verify_case
from mandifuel_verify.case import Case,Sources
from mandifuel_verify.checks import lame,sphere_release,stable_id
from mandifuel_verify.inputs import Unavailable
from registry import TaskRegistry

FIXTURE=Path(__file__).parent/'fixtures/radial-52'


def field(path,name,kind,dimensions,values,boundaries):
    cls={'scalar':'volScalarField','vector':'volVectorField','symmTensor':'volSymmTensorField'}[kind]
    def value(row):return str(row) if isinstance(row,(int,float)) else '('+' '.join(map(str,row))+')'
    text=f'FoamFile {{format ascii;class {cls};object {name};}}\ndimensions ['+' '.join(map(str,dimensions))+'];\n'
    text+='internalField nonuniform List<'+kind+'>\n'+str(len(values))+'\n(\n'+'\n'.join(value(v) for v in values)+'\n);\nboundaryField {\n'
    for patch,rows in boundaries.items():text+=patch+' {type calculated;value nonuniform List<'+kind+'> '+str(len(rows))+' ('+' '.join(value(v) for v in rows)+');}\n'
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text+'}\n')


def sphere_fixture(case,cells=8):
    mesh=case/'constant/polyMesh';mesh.mkdir(parents=True);(case/'system').mkdir();(case/'0').mkdir();(case/'1').mkdir()
    points=[];t=math.tan(.01)
    for i in range(cells+1):
        radius=1+i/cells;x=radius/math.sqrt(1+2*t*t)
        points.extend([(x,-x*t,-x*t),(x,x*t,-x*t),(x,x*t,x*t),(x,-x*t,x*t)])
    faces=[];owner=[];neighbour=[]
    for i in range(1,cells):faces.append(tuple(4*i+j for j in range(4)));owner.append(i-1);neighbour.append(i)
    patches=[]
    def patch(name,kind,items):
        start=len(faces)
        for face,own in items:faces.append(face);owner.append(own)
        patches.append((name,kind,len(faces)-start,start))
    patch('inner','patch',[(tuple(reversed(range(4))),0)])
    patch('outer','patch',[(tuple(4*cells+j for j in range(4)),cells-1)])
    for j in range(4):patch('wedge'+str(j),'wedge',[(tuple([4*i+j,4*i+(j+1)%4,4*(i+1)+(j+1)%4,4*(i+1)+j]),i) for i in range(cells)])
    def header(cls,obj):return f'FoamFile {{version 2.0;format ascii;class {cls};object {obj};}}\n'
    (mesh/'points').write_text(header('vectorField','points')+str(len(points))+'\n(\n'+'\n'.join('('+' '.join(map(str,p))+')' for p in points)+'\n)\n')
    (mesh/'faces').write_text(header('faceList','faces')+str(len(faces))+'\n(\n'+'\n'.join(str(len(f))+'('+' '.join(map(str,f))+')' for f in faces)+'\n)\n')
    for name,items in [('owner',owner),('neighbour',neighbour)]: (mesh/name).write_text(header('labelList',name)+str(len(items))+'\n(\n'+'\n'.join(map(str,items))+'\n)\n')
    (mesh/'boundary').write_text(header('polyBoundaryMesh','boundary')+str(len(patches))+'\n(\n'+'\n'.join(f'{n} {{type {k};nFaces {num};startFace {start};}}' for n,k,num,start in patches)+'\n)\n')
    (mesh/'cellZones').write_text(header('regIOobject','cellZones')+f'1\n(shell {{type cellZone;cellLabels List<label> {cells} ('+' '.join(map(str,range(cells)))+');})\n')
    (case/'system/controlDict').write_text('endTime 1;startTime 0;userTime {type seconds;}')
    (case/'system/fvSchemes').write_text('d2dt2Schemes {default steadyState;}ddtSchemes {default steadyState;}')
    (case/'constant/solverDict').write_text('mechanicsSolver smallStrain;thermalSolver none;rheologyOptions {thermalExpansion off;} materials {shell {material constant;rheologyModel elasticity;E E [1 -1 -2 0 0] 100000;nu .25;alpha 0;}}')
    (case/'0/D').write_text('internalField uniform (0 0 0);boundaryField {inner {type tractionDisplacement;traction uniform (0 0 0);pressure uniform 10;}outer {type tractionDisplacement;traction uniform (0 0 0);pressure uniform 2;}}')
    g=Case(case).geometry
    u=[];s=[]
    for p in g['centres']:
        displacement,rr,tt=lame(math.sqrt(sum(v*v for v in p)),1,2,10,2,100000,.25)
        u.append((displacement,0,0));s.append((rr,0,0,tt,0,tt))
    field(case/'1/D','D','vector',(0,1,0,0,0,0,0),u,{})
    field(case/'1/sigma','sigma','symmTensor',(1,-1,-2,0,0,0,0),s,{})


class EvidenceTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.work=Path(self.temp.name);self.case=self.work/'case';shutil.copytree(FIXTURE,self.case)
    def tearDown(self):self.temp.cleanup()
    def check(self,report,key):return next(c for c in report['checks'] if c['key']==key)
    def receipt(self,case=None,extra=''):
        case=case or self.case
        (case/'.mandifuel-execution.json').write_text(json.dumps({'status':'completed','exit_code':0,'terminal_marker':True,'final_time':'1','log':str(case/'log.offbeat')}))
        (case/'log.offbeat').write_text('Synthetic test log\nTime = 1\n'+extra+'\n end \n')
    def heat(self):
        g=Case(self.case).geometry;n=len(g['volumes']);power=2*sum(g['volumes']);patch=g['patches']['cladOuter'];area=sum(math.sqrt(sum(v*v for v in g['areas'][i])) for i in patch['faces'])
        boundaries={name:[(0,0,0)]*p['count'] for name,p in g['patches'].items()}
        boundaries['cladOuter']=[tuple(power/area*v/math.sqrt(sum(x*x for x in g['areas'][i])) for v in g['areas'][i]) for i in patch['faces']]
        field(self.case/'1/Q','Q','scalar',(1,-1,-3,0,0,0,0),[2]*n,{})
        field(self.case/'1/heatFluxVec','heatFluxVec','vector',(1,0,-3,0,0,0,0),[(0,0,0)]*n,boundaries)
        self.receipt(extra='Boundary power summary:\n'+''.join('\t'+name+': '+str(power if name=='cladOuter' else 0)+'\n' for name,p in g['patches'].items() if p['count']))
        return power
    def cesium(self):
        g=Case(self.case).geometry;n=len(g['volumes']);volume=sum(g['volumes'])
        for time,value in [('0',1),('1',.4)]:field(self.case/time/'Cs','Cs','scalar',(0,-3,0,0,1,0,0),[value]*n,{})
        field(self.case/'1/sourceCs','sourceCs','scalar',(0,-3,-1,0,1,0,0),[0]*n,{})
        self.receipt(extra=f'Fission products transport:\nInitial Cs amount: {volume}\nProduction of Cs: 0\nReleased Cs amount: {.6*volume}\nRemained Cs amount: {.4*volume}\nFraction of Cs release: .6\n')
    def test_heat_integrates_real_cell_volumes_and_oriented_boundary_areas(self):
        power=self.heat();r=verify_case(self.case)
        self.assertEqual(self.check(r,'heat.balance')['status'],'verified');self.assertEqual(self.check(r,'heat.native_balance')['status'],'verified')
        self.assertAlmostEqual(next(q for q in r['claims'] if q['key']=='heat.source')['value'],power)
        self.assertEqual(self.check(r,'execution')['status'],'verified')
    def test_changed_source_is_not_hidden_by_a_matching_solver_summary(self):
        self.heat()
        g=Case(self.case).geometry;field(self.case/'1/Q','Q','scalar',(1,-1,-3,0,0,0,0),[4]*len(g['volumes']),{})
        r=verify_case(self.case,checks=['heat']);self.assertEqual(self.check(r,'heat.balance')['status'],'failed')
    def test_transient_heat_is_not_claimed_to_be_steady_balance(self):
        self.heat();p=self.case/'system/fvSchemes';p.write_text(p.read_text().replace('steadyState','Euler'))
        r=verify_case(self.case,checks=['heat']);self.assertEqual(self.check(r,'heat')['status'],'not_applicable')
    def test_numerical_agreement_does_not_overwrite_a_failed_execution_receipt(self):
        self.heat();p=self.case/'.mandifuel-execution.json';receipt=json.loads(p.read_text());receipt['status']='failed';p.write_text(json.dumps(receipt))
        r=verify_case(self.case);self.assertEqual(self.check(r,'heat.balance')['status'],'verified');self.assertEqual(self.check(r,'execution')['status'],'not_verified')
        self.assertEqual(json.loads(p.read_text())['status'],'failed')
    def test_wrong_field_dimensions_cannot_pass(self):
        self.heat();p=self.case/'1/Q';p.write_text(p.read_text().replace('[1 -1 -3 0 0 0 0]','[0 0 0 0 0 0 0]'))
        self.assertEqual(self.check(verify_case(self.case,checks=['heat']),'heat')['status'],'not_verified')
    def test_cesium_all_domain_inventory_and_native_release_are_cross_checked(self):
        self.cesium();r=verify_case(self.case,checks=['cesium'])
        self.assertEqual(self.check(r,'cesium.balance')['status'],'verified');self.assertEqual(self.check(r,'cesium.initial')['status'],'verified')
        self.assertAlmostEqual(next(q['value'] for q in r['claims'] if q['key']=='cesium.release_fraction'),.6)
        self.assertEqual(self.check(r,'cesium.analytic')['status'],'not_applicable')
    def test_tiny_native_release_is_not_replaced_by_subtraction_noise(self):
        self.cesium()
        volumes = Case(self.case).geometry['volumes']
        initial = math.fsum(volumes)
        field(self.case/'1/Cs','Cs','scalar',(0,-3,0,0,1,0,0),[1-1e-8]*len(volumes),{})
        def evaluate(reported):
            self.receipt(extra=f'Fission products transport:\nInitial Cs amount: {initial}\nProduction of Cs: 0\nReleased Cs amount: {initial*1e-34}\nRemained Cs amount: {initial}\nFraction of Cs release: {reported}\n')
            return verify_case(self.case,checks=['cesium'])
        report=evaluate(1e-34)
        claims={c['key']:c['value'] for c in report['claims']}
        self.assertEqual(claims['cesium.release_fraction'],1e-34)
        self.assertTrue(math.isclose(claims['cesium.inventory_depletion'],1e-8,rel_tol=1e-6))
        deficit=next(c for c in report['claims'] if c['key']=='cesium.inventory_depletion')
        self.assertEqual(deficit['id'],stable_id(deficit['caseRoot'],'cesium.release_fraction'))
        self.assertEqual(len({c['id'] for c in report['claims']}),len(report['claims']))
        self.assertEqual(self.check(report,'cesium.native_fraction')['status'],'verified')
        corrupted=evaluate(1e-20)
        self.assertEqual(self.check(corrupted,'cesium.balance')['status'],'verified')
        self.assertEqual(self.check(corrupted,'cesium.native_fraction')['status'],'failed')
    def test_wrong_time_log_and_missing_source_never_get_invented(self):
        self.cesium();p=self.case/'log.offbeat';p.write_text(p.read_text().replace('Time = 1','Time = 2'))
        self.assertEqual(self.check(verify_case(self.case,checks=['cesium']),'cesium')['status'],'not_verified')
        self.cesium();(self.case/'1/sourceCs').unlink();self.assertEqual(self.check(verify_case(self.case,checks=['cesium']),'cesium')['status'],'not_verified')
    def test_initial_missing_data_is_explicit_and_does_not_zero_fill(self):
        self.cesium();(self.case/'0/Cs').unlink()
        r=verify_case(self.case,checks=['cesium']);self.assertEqual(self.check(r,'cesium.initial')['status'],'not_verified')
        self.assertEqual(self.check(r,'cesium.balance')['status'],'verified')
    def test_analytic_sphere_uses_spherical_not_cylindrical_lame(self):
        case=self.work/'shell';sphere_fixture(case);self.receipt(case)
        r=verify_case(case,checks=['sphere'])
        for key in ['sphere.displacement','sphere.radial_stress','sphere.hoop_stress']:self.assertEqual(self.check(r,key)['status'],'verified')
        d,rr,tt=lame(1,1,2,10,2,100000,.25);self.assertAlmostEqual(rr,-10);self.assertGreater(d,0)
        p=case/'constant/solverDict';p.write_text(p.read_text().replace('thermalExpansion off','thermalExpansion on'))
        self.assertEqual(self.check(verify_case(case,checks=['sphere']),'sphere')['status'],'not_applicable')
    def test_lame_detects_perturbed_stress_and_keeps_unverified_discretization(self):
        case=self.work/'shell';sphere_fixture(case);p=case/'1/sigma';p.write_text(p.read_text().replace('(-','(-9',1))
        r=verify_case(case,checks=['sphere']);self.assertTrue(any(c['status']=='failed' for c in r['checks']));self.assertEqual(self.check(r,'discretization')['status'],'not_verified')
    def test_source_fingerprints_invalidation_paths_and_read_only_cli(self):
        self.cesium();before={str(p.relative_to(self.case)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.case.rglob('*') if p.is_file()}
        r=verify_case(self.case);reader=Sources(self.work);reader.read(self.case/'1/Cs');self.assertTrue(reader.unchanged())
        p=self.case/'1/Cs';p.write_text(p.read_text()+'\n// changed\n');self.assertFalse(reader.unchanged())
        p.write_bytes(p.read_bytes().replace(b'\n// changed\n',b''))
        (self.work/'link').symlink_to(self.case/'1/Cs')
        with self.assertRaises(Unavailable):reader.read(self.work/'link')
        with self.assertRaises(Unavailable):reader.read(self.work/'../outside')
        output=self.work/'audit.json';run=subprocess.run([sys.executable,str(ROOT/'scripts/verify-results.py'),'--case',str(self.case),'--output',str(output)],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr);self.assertTrue(output.exists())
        # The only input modification above was the explicit fingerprint test.
        for p in self.case.rglob('*'):
            if p.is_file():self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),before[str(p.relative_to(self.case))])
        bad=subprocess.run([sys.executable,str(ROOT/'scripts/verify-results.py'),'--case',str(self.case),'--output',str(self.case/'1/Cs')],capture_output=True)
        self.assertNotEqual(bad.returncode,0)
    def test_sphere_release_series_and_pressure_boundary_conditions(self):
        self.assertEqual(sphere_release(0),0)
        for tau in [.001,.03,.2]:
            reference=1-6/math.pi**2*sum(math.exp(-n*n*math.pi**2*tau)/n**2 for n in range(1,5000))
            self.assertAlmostEqual(sphere_release(tau),reference,places=12)
        self.assertAlmostEqual(lame(2,1,2,10,2,100000,.25)[1],-2)


class EvidenceServiceTests(unittest.TestCase):
    setUp=EvidenceTests.setUp
    tearDown=EvidenceTests.tearDown
    cesium=EvidenceTests.cesium
    receipt=EvidenceTests.receipt
    def test_older_partial_mesh_override_invalidates_evidence_signature(self):
        from evidence import EvidenceService
        from workspace_watch import discover_cases
        self.cesium();service=object.__new__(EvidenceService);service.engine='test'
        rows=discover_cases(self.work);before=service.case_signature(self.work,rows)
        mesh=self.case/'.5/polyMesh';mesh.mkdir(parents=True)
        shutil.copyfile(self.case/'constant/polyMesh/points',mesh/'points')
        overridden=service.case_signature(self.work,rows);self.assertNotEqual(before,overridden)
        (mesh/'points').write_text((mesh/'points').read_text()+'\n// changed mesh\n')
        self.assertNotEqual(overridden,service.case_signature(self.work,rows))
        shutil.rmtree(mesh.parent);self.assertEqual(before,service.case_signature(self.work,rows))
    def test_service_runs_without_agent_and_keeps_cache_outside_solver_workspace(self):
        self.cesium();registry=TaskRegistry(self.work/'tasks')
        try:
            prepared=registry.prepare('普通终端求解');ident=prepared['task']['id'];work=Path(prepared['workspace']);shutil.copytree(self.case,work/'case')
            original={str(p.relative_to(work)):hashlib.sha256(p.read_bytes()).hexdigest() for p in work.rglob('*') if p.is_file()}
            registry.evidence.scan(ident,force=True)
            end=time.monotonic()+8
            while time.monotonic()<end:
                index=registry.evidence.index(ident)
                if index['claims'] and index['state']=='ready':break
                time.sleep(.05)
            self.assertTrue(index['claims']);self.assertEqual(index['state'],'ready')
            q=next(q for q in index['claims'] if q['key']=='cesium.inventory');detail=registry.evidence.index(ident,q['id']);self.assertTrue(detail['sources'])
            source=next(s for s in detail['sources'] if s['path'].endswith('/1/Cs'));preview=registry.evidence.index(ident,q['id'],source['id']);self.assertFalse(preview['changed'])
            with self.assertRaises(ValueError):registry.evidence.index(ident,'ev-'+'f'*20)
            self.assertTrue((work.parent/'evidence.json').exists());self.assertFalse((work/'evidence.json').exists())
            self.assertEqual({str(p.relative_to(work)):hashlib.sha256(p.read_bytes()).hexdigest() for p in work.rglob('*') if p.is_file()},original)
            p=work/'case/1/Cs';p.write_text(p.read_text()+'\n// newer\n');stale=registry.evidence.index(ident,q['id']);self.assertEqual(stale['claim']['status'],'stale')
            changed=registry.evidence.index(ident,q['id'],source['id']);self.assertTrue(changed['changed']);self.assertEqual(registry.snapshot(ident)['task']['status'],'queued')
        finally:registry.close()
    def test_agent_references_are_bound_to_real_claims_and_cannot_override_values(self):
        from adaptive_ui import validate_ui
        validate_ui({'version':1,'root':{'id':'summary','type':'evidence','claims':['ev-'+'a'*20]}})
        for node in [
            {'id':'bad','type':'text','text':'结论','evidence':[{}]},
            {'id':'bad','type':'evidence','claims':['ev-'+'a'*20],'value':98},
            {'id':'bad','type':'evidence','claims':['missing']},
        ]:
            with self.assertRaises(ValueError):validate_ui({'version':1,'root':node})
        registry=TaskRegistry(self.work/'tasks')
        try:
            ident=registry.prepare('独立计算')['task']['id']
            with self.assertRaisesRegex(ValueError,'不存在的核查'):
                registry.dashboard.publish(ident,{'ui':{'version':1,'root':{'id':'summary','type':'text','text':'结论','evidence':['ev-'+'a'*20]}}})
            from frontend_session import snapshot
            self.assertEqual(snapshot(registry.dashboard,ident,'evidence')['evidence']['claims'],[])
        finally:registry.close()


if __name__=='__main__':unittest.main()
