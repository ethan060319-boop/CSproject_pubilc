"""Focused regression checks. Run from the project root with unittest discovery."""
import math
from pathlib import Path
import tempfile
import unittest
from shade.campus import load_campus, walkable
from shade.native import Model, compile_native

STAMP = "2026-11-21T15:00"

class ShadeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Runtimes can keep a DLL open until process exit.
        import os
        cls.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True) if os.name=="nt" else tempfile.TemporaryDirectory()
        cls.binary=compile_native(cls.temp.name)
        cls.campus=load_campus()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_point_changes_in_half_an_hour(self):
        m=Model(self.binary,self.campus)
        out=m.state(dict(at=STAMP,x="-150.227",y="-14.035"))
        self.assertEqual(out["point"][0],0)
        self.assertEqual(self.campus["buildings"][-out["point"][1]-1]["name"],"第二行政中心")
        self.assertAlmostEqual(out["elevation"],24.006,delta=.03)
        self.assertAlmostEqual(out["azimuth"],231.758,delta=.03)
        self.assertTrue(out["path"].startswith("M"))

    def test_route_cost_and_night(self):
        m=Model(self.binary,self.campus)
        stops={p["name"]:p["node"] for p in self.campus["places"]}
        q={"at":STAMP,"from":stops["工程一館"],"to":stops["教學研究綜合大樓"],"alpha":4}
        short,cool=m.state(q)["routes"]
        self.assertGreater(cool["length"],short["length"])
        self.assertLess(cool["sun"],short["sun"]-100)
        self.assertLessEqual(cool["length"]+3*cool["sun"],short["length"]+3*short["sun"])
        allowed={frozenset(e) for e in self.campus["edges"]}
        for route in (short,cool):
            path=route["nodes"]
            self.assertEqual((path[0],path[-1]),(q["from"],q["to"]))
            self.assertTrue(all(frozenset((a,b)) in allowed for a,b in zip(path,path[1:])))
        same=m.state({**q,"alpha":1})["routes"]
        self.assertEqual(*same)
        dark=m.state({**q,"at":"2026-12-31T23:45","x":-150.227,"y":-14.035})
        self.assertEqual(dark["point"],[-1000000,-1000000])
        self.assertEqual(dark["path"],"")
        self.assertEqual(*dark["routes"])
        self.assertEqual(dark["routes"][0]["sun"],0)

    def test_courtyard_concavity_shadow_and_disconnected_routes(self):
        square=[[[0,0],[20,0],[20,20],[0,20]],[[5,5],[15,5],[15,15],[5,15]]]
        # A concave L leaves (36,16) outdoors at summer noon.
        elbow=[[[25,0],[40,0],[40,4],[29,4],[29,20],[25,20]]]
        campus={"buildings":[dict(rings=square,height=10),dict(rings=elbow,height=5)],
                "nodes":[[0,50],[5,50],[60,50]],"edges":[[0,1]]}
        m=Model(self.binary,campus)
        m.state({"at":"2026-06-21T12:00"})
        self.assertEqual(m.api.probe(2,2,0),1)
        self.assertEqual(m.api.probe(10,10,0),0)
        self.assertEqual(m.api.probe(36,16,0),0)
        s=m.state({"at":STAMP})
        az=math.radians(s["azimuth"])
        length=10/math.tan(math.radians(s["elevation"]))
        dx,dy=-math.sin(az)*length,-math.cos(az)*length
        self.assertEqual(m.api.probe(20+dx*.5,20+dy*.5,0),-1)
        self.assertEqual(m.api.probe(20+dx*1.05,20+dy*1.05,0),0)
        self.assertIsNone(m.route(0,2,4))
        self.assertEqual(m.route(1,1,4),dict(nodes=[1],points=[[5,50]],length=0,sun=0))

    def test_arbitrary_positions_on_roads(self):
        data={"buildings":[], "nodes":[[0,0],[10,0],[10,10],[50,50],[55,50]],
              "edges":[[0,1],[1,2],[3,4]]}
        m=Model(self.binary,data)
        m.state({"at":STAMP})
        cases=[((0,.20),(0,.23),.30),((0,.80),(0,.20),6),
               ((0,.50),(1,.75),12.5),((1,.75),(0,.50),12.5),
               ((1,.75),(1,.75),0),((0,1),(1,0),0)]
        for start,end,expected in cases:
            result=m.route(start,end,4,on_edges=True)
            self.assertAlmostEqual(result["length"],expected)
            self.assertAlmostEqual(result["sun"],expected)
        self.assertIsNone(m.route((0,.25),(2,.5),4,on_edges=True))
        self.assertEqual(m.route(0,2,1)["points"],[[0,0],[10,0],[10,10]])

    def test_recomputes_when_time_or_endpoints_change(self):
        m=Model(self.binary,self.campus)
        stops={p["name"]:p["node"] for p in self.campus["places"]}
        query={"at":STAMP,"from":stops["工程一館"],"to":stops["教學研究綜合大樓"],"alpha":4}
        pm=m.state(query)
        am=m.state({**query,"at":"2026-11-21T09:00"})
        self.assertNotEqual(am["routes"][1]["nodes"],pm["routes"][1]["nodes"])
        self.assertLess(am["referenceShadow"],pm["referenceShadow"])
        elsewhere=m.state({**query,"from":stops["總圖書館"],"to":stops["行政大樓"]})
        self.assertEqual(elsewhere["routes"][1]["nodes"][0],stops["總圖書館"])
        self.assertEqual(elsewhere["routes"][1]["nodes"][-1],stops["行政大樓"])
        self.assertEqual(m.state(query)["routes"],pm["routes"])

    def test_dates_access_and_stops(self):
        m=Model(self.binary,self.campus)
        with self.assertRaises(ValueError):
            m.state({"at":"2026-02-29T12:00"})
        with self.assertRaises(ValueError):
            m.state({"at":STAMP,"from":-1,"to":1})
        m.state({"at":"2028-02-29T12:00"})
        self.assertFalse(walkable({"highway":"footway","access":"private"}))
        self.assertTrue(walkable({"highway":"footway","access":"no","foot":"yes"}))
        self.assertFalse(walkable({"highway":"cycleway","foot":"no"}))
        for place in self.campus["places"]:
            self.assertLessEqual(m.api.probe(*self.campus["nodes"][place["node"]],0),0)

if __name__=="__main__":
    unittest.main()
