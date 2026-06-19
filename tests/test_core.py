from __future__ import annotations
import importlib
import unittest
from _bootstrap import PACKAGE_NAME
continuity=importlib.import_module(f"{PACKAGE_NAME}.continuity_core")
production=importlib.import_module(f"{PACKAGE_NAME}.production_core")
runtime=importlib.import_module(f"{PACKAGE_NAME}.runtime_core")
collaboration=importlib.import_module(f"{PACKAGE_NAME}.collaboration_core")

class CoreTests(unittest.TestCase):
    def test_stable_digest(self): self.assertEqual(continuity.digest({"b":2,"a":1}),continuity.digest({"a":1,"b":2}))
    def test_lock(self): self.assertEqual(continuity.build_lock("project","demo",{"fps":24}),continuity.build_lock("project","demo",{"fps":24}))
    def test_diff(self): self.assertEqual(continuity.continuity_diff({"x":{"a":1}},{"x":{"a":2}})[0]["path"],"$.x.a")
    def test_storyboard(self): self.assertEqual(production.expand_storyboard([{"id":"a"},{"id":"b"}],{"hash":"m"},100,3)["take_count"],6)
    def test_gate(self): self.assertTrue(production.quality_gate({"identity":.9,"continuity":.9,"technical":.9},{"identity":.8})["passed"])
    def test_ranking(self): self.assertEqual(production.rank_takes([{"take_id":"b","metrics":{"identity":.8}},{"take_id":"a","metrics":{"identity":.8}}],{"identity":1,"continuity":0,"technical":0,"motion":0,"prompt":0})[0]["take_id"],"a")
    def test_waves(self): self.assertEqual([[x["task_id"] for x in w] for w in runtime.dependency_waves([{"id":"a"},{"id":"b","depends_on":["a"]},{"id":"c","depends_on":["a"]}],2)],[["a"],["b","c"]])
    def test_cycle(self):
        with self.assertRaises(continuity.ContinuityError): runtime.dependency_waves([{"id":"a","depends_on":["b"]},{"id":"b","depends_on":["a"]}])
    def test_merge(self):
        merged,conflicts=collaboration.three_way_merge({"a":1,"b":1},{"a":2,"b":1},{"a":1,"b":2}); self.assertEqual(merged,{"a":2,"b":2}); self.assertEqual(conflicts,[])
    def test_conflict(self): self.assertEqual(collaboration.three_way_merge({"a":1},{"a":2},{"a":3})[1][0]["path"],"$.a")
