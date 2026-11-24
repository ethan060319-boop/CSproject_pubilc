"""Prepare the team's map for both the native Python server and the offline map."""
from collections import defaultdict
import json
import math
import re
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
    # 這個地圖是給中大師生用的：校內道路在 OSM 常標成 access=private（私人產權、
    # 不對外開放），但對校內的人是可以走的；校內自行車道也允許行人通行。
    # 只有明確標 foot=no／access=no 等的路才排除。
    foot = tags.get("foot")
    if foot in {"no", "private", "use_sidepath"}:
        return False
    if tags.get("highway") in {"construction", "proposed", "motorway", "motorway_link"}:
        return False
    if foot in {"yes", "designated", "permissive", "official"}:
        return True
    return tags.get("access") not in {"no"} and tags.get("highway") not in {
        "trunk", "trunk_link", "bridleway", "raceway"}

def as_ring(coords):
    points = [list(latlon_to_xy(*p[:2])) for p in coords]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points

LEVEL_HEIGHT = 3.5
HEIGHTS_CSV = "building_heights.csv"

def ring_area(ring):
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(ring, ring[1:]+ring[:1])))/2

def footprint_area(rings):
    return max(0.0, ring_area(rings[0])-sum(ring_area(r) for r in rings[1:]))

def default_height(kind, name, area):
    """沒有任何高度資料時的估計值。小型附屬建物不該和教學大樓一樣高。"""
    if kind in {"garage", "shed", "roof", "kiosk", "toilets"} or area < 150:
        return 3.5, "default_small"      # 約 1 層：警衛亭、廁所、儲藏室
    if kind == "house" or (not name and area < 400):
        return 7.0, "default_small"      # 約 2 層：宿舍區小屋、附屬建物
    return 12.0, "default"               # 約 3–4 層：一般系館

def load_height_table(path):
    """讀取組員手動填寫的高度表。height_m 優先，其次 levels（每層 3.5 m）。"""
    table = {}
    if not path.exists():
        return table
    import csv
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (row["osm_id"].strip(), int(row.get("part") or 0))
            height = parse_number(row.get("height_m"))
            levels = parse_number(row.get("levels"))
            # data_source 留空＝組員實地填寫；ncu_report＝校方耐震評估清冊的樓層數
            source = (row.get("data_source") or "").strip() or "manual"
            if height and height > 0:
                table[key] = (height, source, None)
            elif levels and levels > 0:
                table[key] = (levels*LEVEL_HEIGHT, source, levels)
    return table

def load_name_table(path):
    """building_heights.csv 的 name 欄：組員可以替 OSM 沒名字的建築填上名字（或更正名字）。"""
    table = {}
    if not path.exists():
        return table
    import csv
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            if name:
                table[(row["osm_id"].strip(), int(row.get("part") or 0))] = name
    return table

def label_unnamed(buildings):
    """OSM 沒有名字的建築，用「最近的有名建築＋旁建築」當顯示用名稱，同區多棟就加流水號。
    只放在 label 欄位，不會出現在地圖地名和目的地搜尋裡。"""
    def center(b):
        r = b["rings"][0]
        return (sum(p[0] for p in r)/len(r), sum(p[1] for p in r)/len(r))
    named = [b for b in buildings if b["name"]]
    groups = defaultdict(list)
    for b in buildings:
        if b["name"] or not named:
            continue
        c = center(b)
        near = min(named, key=lambda n: math.dist(center(n), c))
        groups[re.sub(r"\(.*?\)", "", near["name"])].append(b)
    for near, members in groups.items():
        members.sort(key=lambda b: -b["area"])
        for k, b in enumerate(members, 1):
            b["label"] = f"{near}旁建築" + (f" {k}" if len(members) > 1 else "")

def map_buildings(features, saved, manual=None, names=None):
    # Match by stable OSM identifier; a multipolygon may have several outer parts.
    manual = manual or {}
    names = names or {}
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
            name = names.get((osm_id, index)) or tags.get("name", "")
            area = footprint_area(rings)
            if (osm_id, index) in manual:
                h, source, lv = manual[(osm_id, index)]
            elif stored.get("height_source") == "manual" and stored.get("height", 0) > 0:
                h, source, lv = stored["height"], "manual", None
            elif height is not None and height > 0:
                h, source, lv = height, "osm_height", levels
            elif levels is not None and levels > 0:
                h, source, lv = levels * LEVEL_HEIGHT, "osm_levels", levels
            else:
                (h, source), lv = default_height(tags["building"], name, area), None
            buildings.append(dict(osm=osm_id, part=index, name=name, kind=tags["building"],
                                  area=round(area), height=h, source=source,
                                  levels=int(lv) if lv and float(lv).is_integer() else lv, rings=rings))
    label_unnamed(buildings)
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
    """Drop segments that run more than INDOOR_TOLERANCE metres inside a footprint. Paths along a wall or in a courtyard are outdoors."""
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

    # OSM 的建築輪廓和道路都有幾十公分到一兩公尺的誤差，常有路「擦到」建築一角。
    # 只要碰到就整段剔除，會把整片路網切斷（例如環工所旁的路只擦進 0.3 m），
    # 所以改成量「在建築輪廓內的長度」，超過 INDOOR_TOLERANCE 才視為穿過建築。
    INDOOR_TOLERANCE = 2.0
    def blocked(a,b):
        x1,x2=sorted((a[0],b[0]))
        y1,y2=sorted((a[1],b[1]))
        length=math.dist(a,b)
        steps=max(1,math.ceil(length/.25))
        for left,bottom,right,top,boundary in footprints:
            if x2<left or right<x1 or y2<bottom or top<y1:
                continue
            indoor=sum(1 for k in range(steps)
                       if inside((a[0]+(b[0]-a[0])*(k+.5)/steps,a[1]+(b[1]-a[1])*(k+.5)/steps),boundary))
            if indoor*length/steps>INDOOR_TOLERANCE:
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
            if inside(p,boundary):   # 路擦進建築輪廓（容許 2 m）時，那些點不能當起終點
                return False
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

def _cross(o, a, b):
    return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])

def _segments_cross(a, b, c, d):
    return _cross(a,b,c)*_cross(a,b,d) < 0 and _cross(c,d,a)*_cross(c,d,b) < 0

def _inside(p, ring):
    parity = False
    for i in range(len(ring)):
        a, b = ring[i-1], ring[i]
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]:
            parity = not parity
    return parity

def bridge_gaps(nodes, edges, buildings, land, max_gap=20.0):
    """OSM 有些小路畫到主路前幾公尺就停了，沒有共用節點，路網因此斷成孤島，
    從孤島上出發就永遠算不出路線。這裡每次找「孤島上的點 → 另一塊路網」最短、
    且在 max_gap 公尺內的接線（不可穿過建築、水池或溪流）補上，直到接不上為止。
    回傳新增的接線數。"""
    obstacles = []   # (邊界線段清單, 可判斷「在裡面」的多邊形 或 None)
    for b in buildings:
        obstacles.append(([(r[i-1], r[i]) for r in b["rings"] for i in range(len(r))], b["rings"][0]))
    for v in land:
        pts = v["points"]
        if v["kind"] == "stream":
            obstacles.append(([(pts[i-1], pts[i]) for i in range(1, len(pts))], None))
        elif v["kind"] == "water":
            obstacles.append(([(pts[i-1], pts[i]) for i in range(len(pts))], pts))

    def blocked(a, b):
        mid = ((a[0]+b[0])/2, (a[1]+b[1])/2)
        for segs, poly in obstacles:
            if any(_segments_cross(a, b, c, d) for c, d in segs):
                return True
            if poly is not None and _inside(mid, poly):
                return True
        return False

    added = 0
    while True:
        parent = list(range(len(nodes)))
        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        degree = defaultdict(int)
        for a, b in edges:
            parent[find(a)] = find(b)
            degree[a] += 1
            degree[b] += 1
        sizes = defaultdict(int)
        for n in degree:
            sizes[find(n)] += 1
        main_root = max(sizes, key=sizes.get)
        best = None
        # 只從「孤島」出發找接點（孤島上任何一點都可以，因為原本的端點可能
        # 落在建築輪廓內已被剔除）；主路網內部的路不另外加接線
        for u in (n for n in degree if find(n) != main_root):
            p = nodes[u]
            for k, (a, b) in enumerate(edges):
                if find(a) == find(u):
                    continue
                A, B = nodes[a], nodes[b]
                dx, dy = B[0]-A[0], B[1]-A[1]
                L2 = dx*dx+dy*dy
                t = 0 if L2 == 0 else max(0, min(1, ((p[0]-A[0])*dx+(p[1]-A[1])*dy)/L2))
                q = (A[0]+t*dx, A[1]+t*dy)
                gap = math.dist(p, q)
                if gap <= max_gap and (best is None or gap < best[0]) and not blocked(p, q):
                    best = (gap, u, k, t, q)
        if best is None:
            return added
        _, u, k, t, q = best
        a, b = edges[k]
        if t < 1e-6:
            target = a
        elif t > 1-1e-6:
            target = b
        else:
            target = len(nodes)
            nodes.append([round(q[0], 3), round(q[1], 3)])
            edges[k] = [a, target]
            edges.append([target, b])
        edges.append([u, target])
        added += 1

def keep_component(nodes, edges, keep, stops):
    """只保留指定的節點（最大連通路網），重新編號。"""
    keep = sorted(keep)
    ids = {old: new for new, old in enumerate(keep)}
    return ([nodes[i] for i in keep],
            [[ids[a], ids[b]] for a, b in edges if a in ids and b in ids],
            {ids[i] for i in stops if i in ids})

def load_campus():
    raw = json.loads((ROOT/"export.geojson").read_text(encoding="utf-8"))
    saved = json.loads((ROOT/"buildings.json").read_text(encoding="utf-8"))["buildings"]
    bs = map_buildings(raw["features"], saved, load_height_table(ROOT/HEIGHTS_CSV), load_name_table(ROOT/HEIGHTS_CSV))
    roads, nodes, edges = road_graph(raw["features"])
    nodes, edges, outdoor_stops = outdoor_graph(bs,nodes,edges)
    land = json.loads((ROOT/"land.json").read_text(encoding="utf-8"))
    bridge_gaps(nodes, edges, bs, land)
    # 仍接不上的小段路（例如被溪流或建築隔開）不放進路網，起終點就不會吸附到孤島上
    nodes, edges, outdoor_stops = keep_component(nodes, edges, largest_component(nodes, edges), outdoor_stops)
    main = [i for i in range(len(nodes)) if i in outdoor_stops]
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
                land=land)
