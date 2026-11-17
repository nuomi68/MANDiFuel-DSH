from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from field_catalog import saved_field_catalog


class FieldCatalogTests(unittest.TestCase):
    def test_saved_headers_offer_typed_components_without_assuming_temperature(self):
        with tempfile.TemporaryDirectory() as folder:
            time=Path(folder)/'10';time.mkdir()
            for name,kind,dimensions in [('motion','Vector','0 1 0 0 0 0 0'),('strain','SymmTensor','0 0 0 0 0 0 0'),('stress','SymmTensor','1 -1 -2 0 0 0 0')]:
                (time/name).write_text(f'FoamFile {{format ascii;class vol{kind}Field;object {name};}}\ndimensions [{dimensions}];\ninternalField deliberatelyIncomplete;')
            result=saved_field_catalog(folder,'10',['motion','strain','stress']);fields={f['name']:f for f in result['fields']}
            self.assertEqual(result['errors'],[])
            self.assertEqual(fields['motion']['unit'],'m');self.assertIn('motion:x',fields['motion']['selectors'])
            self.assertEqual(fields['strain']['unit'],'1');self.assertIn('strain:xx',fields['strain']['selectors']);self.assertNotIn('strain:von_mises',fields['strain']['selectors'])
            self.assertEqual(fields['stress']['unit'],'Pa');self.assertIn('stress:von_mises',fields['stress']['selectors'])
            # Header facts are not a claim that incomplete field values are usable.
            from export_case import foam
            with self.assertRaises(ValueError):foam.parse_field(time/'motion')

    def test_changed_saved_headers_refresh_the_catalog_and_invalid_objects_stay_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            time=Path(folder)/'10';time.mkdir();p=time/'output'
            p.write_text('FoamFile {format ascii;class volScalarField;object wrong;} dimensions [0 0 0 1 0 0 0]; internalField uniform 300;')
            result=saved_field_catalog(folder,'10',['output']);self.assertEqual(result['fields'],[]);self.assertEqual(result['errors'][0]['name'],'output')
            p.write_text(p.read_text().replace('wrong','output'))
            self.assertEqual(saved_field_catalog(folder,'10',['output'])['fields'][0]['unit'],'K')


if __name__=='__main__':unittest.main()
