"""Failure-injection tests for expensive-generation prerequisites."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from preflight import audit,geometry

ROOT=Path(__file__).resolve().parents[3]
SOURCE=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'


class PreflightTests(unittest.TestCase):
    def run_case(self,change):
        with tempfile.TemporaryDirectory() as tmp:
            dst=Path(tmp)
            plan=json.loads((SOURCE/'floor_plan.json').read_text())
            change(plan)
            (dst/'floor_plan.json').write_text(json.dumps(plan))
            (dst/'scene_contract.json').write_bytes((SOURCE/'scene_contract.json').read_bytes())
            return audit(dst)

    def test_baseline_connected(self):
        self.assertEqual(self.run_case(lambda p:None)['status'],'pass')

    def test_disconnected_private_office(self):
        result=self.run_case(lambda p:p['doors'].pop('private_1'))
        self.assertTrue(any('Unreachable' in s for s in result['failures']))

    def test_door_moved_off_boundary(self):
        result=self.run_case(lambda p:p['doors']['private_1'].update(shape='shapely.LineString([(4.2,3.35),(4.2,4.35)])'))
        self.assertTrue(any('attached' in s for s in result['failures']))

    def test_overlap_rejected(self):
        result=self.run_case(lambda p:p['rooms']['office_0/0'].update(shape='shapely.box(0,3,5,5.5)'))
        self.assertTrue(any('Overlapping' in s for s in result['failures']))

    def test_narrow_door_rejected(self):
        result=self.run_case(lambda p:p['doors']['private_1'].update(shape='shapely.LineString([(4,3.35),(4,3.85)])'))
        self.assertTrue(any('too narrow' in s for s in result['failures']))

    def test_code_expression_not_executed(self):
        with self.assertRaises(ValueError):geometry('__import__("os").system("false")')


if __name__=='__main__':unittest.main()
