"""Time-unit scope matters to automatic exports, including probe functions."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from source_metadata import case_time_unit


class TimeUnitTests(unittest.TestCase):
    def check_unit(self,text,expected):
        with tempfile.TemporaryDirectory() as directory:
            case=Path(directory);(case/'system').mkdir()
            (case/'system/controlDict').write_text(text)
            self.assertEqual(case_time_unit(case),expected)

    def test_probe_include_does_not_hide_default_seconds(self):
        self.check_unit('endTime 50000; functions { #includeFunc probes\n }','s')

    def test_nested_user_time_is_not_the_model_unit(self):
        self.check_unit('functions { example { userTime {type days;} } }','s')
        self.check_unit('functions { example {userTime {type seconds;} } } userTime {type days;}','d')

    def test_top_level_include_cannot_be_assumed_irrelevant(self):
        self.check_unit('#include "control.inc"\nendTime 10;',None)
        self.check_unit('userTime {type days;} #include "override.inc"\n',None)

    def test_duplicate_or_unresolved_units_stay_unknown(self):
        for text in ['userTime {type days;} userTime {type seconds;}',
                     'userTime {type days;type seconds;}',
                     'userTime $timeConfig;',
                     'userTime { #include "time.inc"\n }',
                     'userTime {type $unit;}',
                     'userTime {type seconds;']:
            self.check_unit(text,None)


if __name__=='__main__':unittest.main()
