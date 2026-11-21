"""Prepare the team's map for both the native Python server and the offline map."""
from collections import defaultdict
import json
import math
from pathlib import Path
from read_geojson import REF_LAT, REF_LON, latlon_to_xy, parse_number

ROOT = Path(__file__).resolve().parents[1]
AREAS = [
    ("總圖書館周邊", "總圖書館", [-117, 0]),
    ("地球科學院周邊", "地球科學院", [-100, -104]),
    ("教學研究綜合大樓周邊", "教學研究綜合大樓", [-362, 24]),
    ("松苑餐廳周邊", "松苑餐廳", [-485, -125]),
]
LANDMARK_NAMES = ["總圖書館", "行政大樓", "地球科學院", "文學一館", "大禮堂", "工程一館",
                  "教學研究綜合大樓", "綜教館(語言中心)", "松苑餐廳", "中大會館", "依仁堂"]

def walkable(tags):
    foot = tags.get("foot")
    if foot in {"no", "private", "use_sidepath"}:
        return False
    if tags.get("highway") in {"construction", "proposed", "motorway", "motorway_link"}:
        return False
    if foot in {"yes", "designated", "permissive", "official"}:
        return True
    return tags.get("access") not in {"no", "private", "customers"} and tags.get("highway") not in {
        "cycleway", "trunk", "trunk_link", "bridleway", "raceway"}

def as_ring(coords):
    points = [list(latlon_to_xy(*p[:2])) for p in coords]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points

def map_buildings(features, saved):
    # Match by stable OSM identifier; a multipolygon may have several outer parts.
    parts = defaultdict(list)
    for b in saved:
        parts[b["osm_id"]].append(b)
    buildings = []
    for f in features:
        tags, geom = f["properties"], f["geometry"]
        if "building" not in tags or geom["type"] not in {"Polygon", "MultiPolygon"}:
            continue
        polygons = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        osm_id = tags.get("@id") or f.get("id")
        for index, polygon in enumerate(polygons):
            rings = [r for coord in polygon if len(r := as_ring(coord)) >= 3]
            if not rings:
                continue
            stored = parts[osm_id][index] if index < len(parts[osm_id]) else {}
            height = parse_number(tags.get("height"))
            levels = parse_number(tags.get("building:levels"))
            if stored.get("height_source") == "manual" and stored.get("height", 0) > 0:
                h, source = stored["height"], "manual"
            elif height is not None and height > 0:
                h, source = height, "osm_height"
            elif levels is not None and levels > 0:
                h, source = levels * 3.5, "osm_levels"
            else:
                h, source = 12, "default"
            buildings.append(dict(osm=osm_id, name=tags.get("name", ""), height=h,
                                  source=source, rings=rings))
    return buildings

def road_graph(features):
    roads, nodes, edges = [], [], []
    junctions, seen = {}, set()
    def vertex(pt):
        key = tuple(pt)
        if key not in junctions:
            junctions[key] = len(nodes)
            nodes.append(pt)
        return junctions[key]
    for f in features:
        tags, g = f["properties"], f["geometry"]
        if "highway" not in tags or g["type"] not in {"LineString", "MultiLineString"}:
            continue
        lines = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        allowed = walkable(tags)
        for line in lines:
            pts = [list(latlon_to_xy(*p[:2])) for p in line]
            roads.append(dict(kind=tags["highway"], name=tags.get("name",""), walk=allowed, points=pts))
            if not allowed:
                continue
            for a, b in zip(pts, pts[1:]):
                u, v = vertex(a), vertex(b)
                key = tuple(sorted((u,v)))
                if u == v or key in seen:
                    continue
                seen.add(key)
                # Intermediate snap positions are local to this OSM segment. A bridge
                # crossing another way on the map does not create an intersection.
                steps = max(1, math.ceil(math.dist(a,b)/8))
                prev = u
                for i in range(1,steps):
                    mid = [round(m+(n-m)*i/steps,3) for m,n in zip(a,b)]
                    edges.append([prev,len(nodes)])
                    prev = len(nodes)
                    nodes.append(mid)
                edges.append([prev,v])
    return roads, nodes, edges

def outdoor_graph(buildings, nodes, edges):
    """Drop segments that enter a footprint. Paths along a wall or in a courtyard are outdoors."""
    footprints = []
    for building in buildings:
        rings = building["rings"]
        x,y = zip(*rings[0])
        boundary = [(r[i-1],p) for r in rings for i,p in enumerate(r)]
        footprints.append((min(x),min(y),max(x),max(y),boundary))

    def side(a,b,p):
        return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])

    def inside(p,boundary):
        parity = False
        for a,b in boundary:
            if (abs(side(a,b,p)) < 1e-8 and min(a[0],b[0])<=p[0]<=max(a[0],b[0])
                    and min(a[1],b[1])<=p[1]<=max(a[1],b[1])):
                return False
            if (a[1]>p[1])!=(b[1]>p[1]) and p[0] < (b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]:
                parity = not parity
        return parity

    def blocked(a,b):
        x1,x2=sorted((a[0],b[0]))
        y1,y2=sorted((a[1],b[1]))
        for left,bottom,right,top,boundary in footprints:
            if x2<left or right<x1 or y2<bottom or top<y1:
                continue
            if any(side(a,b,c)*side(a,b,d)<0 and side(c,d,a)*side(c,d,b)<0 for c,d in boundary):
                return True
            mid=((a[0]+b[0])/2,(a[1]+b[1])/2)
            if any(inside(p,boundary) for p in (a,b,mid)):
                return True
        return False

    keep = [(a,b) for a,b in edges if not blocked(nodes[a],nodes[b])]
    used = sorted({n for edge in keep for n in edge})
    ids = {old:new for new,old in enumerate(used)}
    # Some OSM ways end exactly on a wall. For named "nearby road" presets, use an
    # outdoor position with at least half a metre of clearance from any outline.
    def clear_of_wall(p):
        for left,bottom,right,top,boundary in footprints:
            if not (left-.5<=p[0]<=right+.5 and bottom-.5<=p[1]<=top+.5):
                continue
            for a,b in boundary:
                dx,dy=b[0]-a[0],b[1]-a[1]
                length2=dx*dx+dy*dy
                t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length2)) if length2 else 0
                if math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)<.5:
                    return False
        return True
    outdoor_stops = {ids[n] for n in used if clear_of_wall(nodes[n])}
    return [nodes[n] for n in used], [[ids[a],ids[b]] for a,b in keep], outdoor_stops

def largest_component(nodes, edges):
    adj = [[] for _ in nodes]
    for a,b in edges:
        adj[a].append(b)
        adj[b].append(a)
    remaining = set(range(len(nodes)))
    largest = []
    while remaining:
        seed = remaining.pop()
        group, todo = [seed], [seed]
        while todo:
            for v in adj[todo.pop()]:
                if v in remaining:
                    remaining.remove(v)
                    group.append(v)
                    todo.append(v)
        if len(group) > len(largest):
            largest = group
    return sorted(largest)

def load_campus():
    raw = json.loads((ROOT/"export.geojson").read_text(encoding="utf-8"))
    saved = json.loads((ROOT/"buildings.json").read_text(encoding="utf-8"))["buildings"]
    bs = map_buildings(raw["features"], saved)
    roads, nodes, edges = road_graph(raw["features"])
    nodes, edges, outdoor_stops = outdoor_graph(bs,nodes,edges)
    main = [i for i in largest_component(nodes,edges) if i in outdoor_stops]
    places = []
    other_names = sorted({b["name"] for b in bs if b["name"]} - set(LANDMARK_NAMES))
    for name in LANDMARK_NAMES + other_names:
        matches = [b for b in bs if b["name"] == name]
        if not matches:
            continue
        pts = [p for b in matches for p in b["rings"][0]]
        center = [sum(p[i] for p in pts)/len(pts) for i in (0,1)]
        # The label explicitly says "附近道路", not an assumption about an entrance.
        near = min(main, key=lambda n: math.dist(nodes[n],center))
        places.append({"name":name,"node":near,"center":[round(v,2) for v in center]})
    return dict(buildings=bs,roads=roads,nodes=nodes,edges=edges,places=places,
                areas=[{"name":name,"anchor":label,"center":p,"radius":100} for name,label,p in AREAS],
                origin=[REF_LON,REF_LAT],timestamp=raw.get("timestamp","")[:10],
                land=json.loads((ROOT/"shade"/"land.json").read_text(encoding="utf-8")))
