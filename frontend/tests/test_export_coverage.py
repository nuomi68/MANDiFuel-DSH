import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import subprocess
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from export_case import export_case,field_unit,display_patches
import export_case as exporter
from registry import validate_bundle
SOURCE=Path(__file__).resolve().parent/'fixtures/radial-52'
class ExportCoverageTests(unittest.TestCase):
    def test_named_tensor_components_keep_original_values_and_dimensions(self):
        with tempfile.TemporaryDirectory() as folder:
            case=Path(folder)/'case'
            for name in ['0','constant','system','1']:shutil.copytree(SOURCE/name,case/name)
            field=case/'1/strain';field.write_text('FoamFile {format ascii;class volSymmTensorField;object strain;} dimensions [0 0 0 0 0 0 0]; internalField uniform (0.002 0 0 -0.004 0 -0.004); boundaryField {}')
            raw=field.read_bytes();out=Path(folder)/'viewer.json'
            export_case(case,out,selectors=[{'selector':'strain:xx','label':'总应变 xx','symbol':'ε_xx'},'strain:yy'],write_handoff=False)
            bundle=json.loads(out.read_text());meta=bundle['task']['fields'][0]
            self.assertEqual((meta['label'],meta['symbol'],meta['unit'],meta['selector']),('总应变 xx','ε_xx','1','strain:xx'))
            self.assertEqual(set(bundle['data']['frames'][0]['fields']['strain_xx']),{0.002});self.assertEqual(set(bundle['data']['frames'][0]['fields']['strain_yy']),{-0.004});self.assertEqual(field.read_bytes(),raw)
            with self.assertRaisesRegex(ValueError,'字段选择'):export_case(case,out,selectors=[{'selector':[],'label':'无效'}],write_handoff=False)
    def test_display_accepts_zero_face_placeholder_without_changing_the_mesh_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'boundary';path.write_text('FoamFile {version 2.0;format ascii;class polyBoundaryMesh;object boundary;}\n2\n(\nwall {type wall;nFaces 6;startFace 10;}\ndefaultFaces {type empty;nFaces 0;startFace 16;}\n)\n');raw=path.read_bytes();patches=display_patches(path);self.assertEqual([(p.name,p.n_faces) for p in patches],[('wall',6)]);self.assertEqual(path.read_bytes(),raw)
            path.write_text(path.read_text().replace('defaultFaces','wall'))
            with self.assertRaisesRegex(ValueError,'重复'):display_patches(path)

    def test_selected_temperature_does_not_parse_every_unrelated_saved_field(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'viewer.json'
            with patch.object(exporter.result_api,'list_variables',side_effect=AssertionError('must inspect selected fields only')):export_case(SOURCE,out,selectors=['T'],write_handoff=False)
            self.assertEqual(json.loads(out.read_text())['task']['fields'][0]['id'],'T')
    def test_cli_radial_bands_preserve_the_physical_gap(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'rod.json';bands=[[0,.0041,40],[.00425,.00485,12]]
            subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'export_case.py'),'--case',str(SOURCE),'--fields','T','--shape','rod','--radius','.00485','--length','.12','--radial-bands',json.dumps(bands),'--output',str(out),'--no-handoff'],check=True,capture_output=True,text=True)
            bundle=json.loads(out.read_text());validate_bundle(bundle);self.assertEqual(bundle['task']['radialBands'],bands);self.assertGreater(bands[1][0],bands[0][1]);self.assertFalse((Path(folder)/'workbench.json').exists())
    def test_unknown_variable_units_are_derived_from_declared_dimensions(self):
        self.assertEqual(field_unit(None,(0,-3,0,0,1,0,0)),'mol/m³')
        self.assertEqual(field_unit(None,(0,2,-1,0,0,0,0)),'m²/s')
        self.assertEqual(field_unit(None,(0,0,0,0,0,0,0)),'1')
    def test_magnitude_and_components_share_real_geometry_and_units(self):
        with tempfile.TemporaryDirectory() as folder:
            case=Path(folder)/'case'
            for name in ['0','constant','system','1']:shutil.copytree(SOURCE/name,case/name)
            # Unit fixture for the derived-field operation; not a claimed solver result.
            (case/'1/D').write_text('FoamFile {version 2.0;format ascii;class volVectorField;object D;}\\ndimensions [0 1 0 0 0 0 0];\\ninternalField uniform (3 4 0);\\nboundaryField {}\\n'.replace('\\n','\n'))
            (case/'1/sigma').write_text('FoamFile {version 2.0;format ascii;class volSymmTensorField;object sigma;}\ndimensions [1 -1 -2 0 0 0 0];\ninternalField uniform (1 0 0 2 0 3);\nboundaryField {}\n'.replace('\n','\n'))
            (case/'1/diffCs').write_text('FoamFile {version 2.0;format ascii;class volScalarField;object diffCs;}\ndimensions [0 2 -1 0 0 0 0];\ninternalField uniform 2.5e-14;\nboundaryField {}\n')
            out=Path(folder)/'viewer.json'
            with patch.object(exporter.result_api,'read_field',wraps=exporter.result_api.read_field) as reader:
                export_case(case,out,selectors=['T','D:x','D:y','D:mag','sigma:principal_max','diffCs'],time='latest',write_handoff=False)
                self.assertEqual(reader.call_count,1)
            bundle=json.loads(out.read_text());validate_bundle(bundle)
            diffusion=next(f for f in bundle['task']['fields'] if f['id']=='diffCs');self.assertEqual(diffusion['unit'],'m²/s');self.assertLess(diffusion['range'][1]-diffusion['range'][0],1e-15)
            self.assertEqual(bundle['data']['frames'][0]['time'],1);fields=bundle['data']['frames'][0]['fields'];self.assertEqual(set(fields['sigma_principal_max']),{3});self.assertEqual(set(fields['D_mag']),{5});self.assertEqual(set(fields['D_x']),{3});self.assertEqual(set(fields['D_y']),{4})
            mesh=next(iter(bundle['data']['meshes'].values()));self.assertEqual(len(mesh['cellEdges']),52);self.assertEqual(mesh['dimensionality'],1);self.assertTrue(all(len(e)%2==0 for e in mesh['cellEdges']))
if __name__=='__main__':unittest.main()
