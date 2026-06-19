from __future__ import annotations
import importlib
import json
import unittest
from _bootstrap import PACKAGE_NAME
package=importlib.import_module(PACKAGE_NAME); nodes=importlib.import_module(f"{PACKAGE_NAME}.nodes")

class NodeTests(unittest.TestCase):
    def test_registration(self): self.assertEqual(len(package.NODE_CLASS_MAPPINGS),14); self.assertEqual(set(package.NODE_CLASS_MAPPINGS),set(package.NODE_DISPLAY_NAME_MAPPINGS))
    def test_attributes(self):
        for name,cls in package.NODE_CLASS_MAPPINGS.items():
            with self.subTest(node=name): self.assertTrue(callable(cls.INPUT_TYPES)); self.assertTrue(cls.RETURN_TYPES); self.assertTrue(cls.FUNCTION); self.assertTrue(cls.CATEGORY.startswith("Continuity Director/"))
    def test_pipeline(self):
        project,_,_=nodes.CDProjectLock().build("demo","Demo","16:9",24,"en",""); manifest,_,_=nodes.CDManifestBuilder().build(project); chain,text,count=nodes.CDBatchDirector().direct(manifest,'[{"id":"shot-1"}]',2,100); self.assertEqual(count,2); self.assertEqual(json.loads(text)["hash"],chain["hash"]); plan,_,waves=nodes.CDExecutionPlan().plan(chain,2); self.assertEqual(waves,1); package_json,package_hash=nodes.CDExportPackage().export(manifest,chain,plan); self.assertEqual(json.loads(package_json)["hash"],package_hash)
