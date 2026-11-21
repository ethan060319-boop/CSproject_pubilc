"""Python bindings to the same C++ code used in the offline browser build."""
from ctypes import CDLL, c_char_p, c_double, c_int
from datetime import datetime, timedelta, timezone
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
from .campus import ROOT

SIGNATURES = {
    "reset_map": (None, []), "add_building": (None,[c_double]), "add_ring": (None,[]),
    "add_vertex": (None,[c_double,c_double]), "add_node": (None,[c_double,c_double]),
    "add_edge": (None,[c_int,c_int]), "set_time": (None,[c_double]),
    "solar_height_at": (c_double,[c_double]), "reference_shadow": (c_double,[]), "azimuth": (c_double,[]), "elevation": (c_double,[]), "shadow_path": (c_char_p,[]),
    "probe": (c_int,[c_double,c_double,c_int]), "solve": (c_int,[c_int,c_int,c_double]),
    "solve_between": (c_int,[c_int,c_double,c_int,c_double,c_double]),
    "route_x": (c_double,[c_int]), "route_y": (c_double,[c_int]),
    "route_node": (c_int,[c_int]), "route_length": (c_double,[]), "route_sun": (c_double,[]),
}
TAIPEI = timezone(timedelta(hours=8))

def compile_native(directory):
    compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        raise FileNotFoundError("找不到 C++ 編譯器。可直接開啟 index.html，或安裝支援 C++17 的 g++。")
    suffix = ".dll" if os.name=="nt" else (".dylib" if sys.platform=="darwin" else ".so")
    lib = Path(directory)/("campus_shade"+suffix)
    flags = ["-dynamiclib"] if sys.platform=="darwin" else ["-shared"]
    if os.name!="nt":
        flags.append("-fPIC")
    subprocess.run([compiler,"-std=c++17","-O2",*flags,str(ROOT/"shade/engine.cpp"),"-o",str(lib)],check=True)
    return lib

class Model:
    def __init__(self, library, campus):
        self.api = CDLL(str(library))
        self.lock = threading.Lock()
        self.n = len(campus["nodes"])
        self.edge_count = len(campus["edges"])
        for name,(result,args) in SIGNATURES.items():
            fn = getattr(self.api,name)
            fn.restype, fn.argtypes = result,args
        c = self.api
        c.reset_map()
        for b in campus["buildings"]:
            c.add_building(b["height"])
            for ring in b["rings"]:
                c.add_ring()
                for x,y in ring:
                    c.add_vertex(x,y)
        for x,y in campus["nodes"]:
            c.add_node(x,y)
        for a,b in campus["edges"]:
            c.add_edge(a,b)

    def route(self,start,end,alpha, *, on_edges=False):
        c=self.api
        count=c.solve_between(*start,*end,alpha) if on_edges else c.solve(start,end,alpha)
        if not count:
            return None
        return dict(nodes=[c.route_node(i) for i in range(count)],
                    points=[[c.route_x(i),c.route_y(i)] for i in range(count)],
                    length=c.route_length(),sun=c.route_sun())

    def state(self,query):
        when=query.get("at","")
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}",when):
            raise ValueError("請輸入有效的臺灣日期與時間")
        unix=datetime.strptime(when,"%Y-%m-%dT%H:%M").replace(tzinfo=TAIPEI).timestamp()
        point=route=None
        if "x" in query or "y" in query:
            point=(float(query["x"]),float(query["y"]))
            if not all(math.isfinite(v) and abs(v)<4000 for v in point):
                raise ValueError("座標超出地圖範圍")
        if "from" in query or "to" in query:
            start,end=int(query["from"]),int(query["to"])
            alpha=float(query.get("alpha",3))
            if not (0<=start<self.n and 0<=end<self.n and 1<=alpha<=10):
                raise ValueError("請檢查路線端點與避曬偏好")
            route=(start,end,alpha,False)
        if any(k in query for k in ("fromEdge","fromFraction","toEdge","toFraction")):
            if route is not None:
                raise ValueError("請選擇一種端點格式")
            a=(int(query["fromEdge"]),float(query["fromFraction"]))
            b=(int(query["toEdge"]),float(query["toFraction"]))
            alpha=float(query.get("alpha",3))
            if not (all(0<=edge<self.edge_count and 0<=frac<=1 for edge,frac in (a,b)) and 1<=alpha<=10):
                raise ValueError("路段或定位比例無效")
            route=(a,b,alpha,True)
        # The numeric model caches the current scene. Keep a request's time, point
        # and both paths together even when two browser tabs use different times.
        with self.lock:
            c=self.api
            c.set_time(unix)
            data=dict(elevation=c.elevation(),azimuth=c.azimuth(),referenceShadow=c.reference_shadow(),
                      path=c.shadow_path().decode("ascii"))
            midnight=unix-(int(when[11:13])*3600+int(when[14:16])*60)
            data["day"]=[c.solar_height_at(midnight+i*1800) for i in range(49)]
            if point:
                data["point"]=[c.probe(*point,0),c.probe(*point,1)]
            if route:
                s,e,a,on_edges=route
                data["routes"]=[self.route(s,e,w,on_edges=on_edges) for w in (1,a)]
        return data
