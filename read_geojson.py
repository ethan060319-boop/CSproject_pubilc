import json
import math
import re

# 設定中央大學基準點經緯度 (作為平面座標的原點 0, 0)
REF_LAT = 24.9682
REF_LON = 121.1955

def parse_number(val_str):
    """從字串中提取數字 (例如將 '15 m' 或 '15.5' 轉為浮點數 15.0, 15.5)"""
    if val_str is None:
        return None
    match = re.search(r"[-+]?\d*\.?\d+", str(val_str))
    return float(match.group(0)) if match else None

def latlon_to_xy(lon, lat, ref_lon=REF_LON, ref_lat=REF_LAT):
    """將經緯度轉換為以基準點為中心的平面公尺座標 (X: 東向公尺, Y: 北向公尺)"""
    # 緯度 1 度約為 111,320 公尺；經度 1 度需乘上 cos(緯度)
    x = (lon - ref_lon) * 111320.0 * math.cos(math.radians(ref_lat))
    y = (lat - ref_lat) * 110574.0
    return round(x, 2), round(y, 2)

def process_geojson(input_path, output_path, default_height=12.0, level_height=3.5):
    with open(input_path, 'r', encoding='utf-8') as f:
        geo_data = json.load(f)

    cleaned_buildings = []
    b_index = 0

    # 名稱與高度改用和網頁同一套規則（shade/campus.py）：
    # building_heights.csv 的人工資料 > OSM height > OSM 樓層數 > 依面積估計；
    # OSM 沒有名字的建築，用「最近的有名建築＋旁建築（流水號）」命名，不再一律寫 Unknown。
    from campus import (ROOT, HEIGHTS_CSV, map_buildings,
                              load_height_table, load_name_table)
    try:
        with open(output_path, 'r', encoding='utf-8') as f:
            saved = json.load(f).get("buildings", [])
    except (OSError, ValueError):
        saved = []
    mapped = {(b["osm"], b["part"]): b for b in map_buildings(
        geo_data.get('features', []), saved,
        load_height_table(ROOT/HEIGHTS_CSV), load_name_table(ROOT/HEIGHTS_CSV))}

    for feature in geo_data.get('features', []):
        props = feature.get('properties', {})
        geom = feature.get('geometry', {})
        
        # 過濾掉不是建築物的圖資
        if 'building' not in props:
            continue

        # 1. 決定建築高度與是否為估計值
        raw_height = parse_number(props.get('height'))
        raw_levels = parse_number(props.get('building:levels'))

        if raw_height is not None:
            height = raw_height
            is_estimated = 0          # C 語言好處理的整數旗標 (0: 實際值, 1: 估計值)
            source_type = "osm_height"
        elif raw_levels is not None:
            height = raw_levels * level_height
            is_estimated = 1
            source_type = "osm_levels"
        else:
            height = default_height
            is_estimated = 1
            source_type = "default"

        # 2. 提取建築外輪廓 (支援 Polygon 與 MultiPolygon)
        geom_type = geom.get('type')
        coords = geom.get('coordinates', [])
        
        polygons = []
        if geom_type == 'Polygon' and len(coords) > 0:
            polygons.append(coords[0]) # coords[0] 為外環輪廓
        elif geom_type == 'MultiPolygon':
            for poly in coords:
                if len(poly) > 0:
                    polygons.append(poly[0])

        # 3. 整理頂點並轉換座標
        for part, ring in enumerate(polygons):
            info = mapped.get((props.get('@id') or feature.get('id'), part))
            if info:
                height, source_type = info["height"], info["source"]
                is_estimated = 0 if source_type == "osm_height" else 1
                name = info["name"] or info.get("label", "")
            else:
                name = props.get('name', '')
            # GeoJSON 的頭尾頂點通常會重複(用來閉合多邊形)，移除最後一個重複點方便 C 計算
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring = ring[:-1]

            vertices_xy = []
            vertices_lonlat = []
            for pt in ring:
                lon, lat = pt[0], pt[1]
                x, y = latlon_to_xy(lon, lat)
                vertices_xy.append({"x": x, "y": y})
                vertices_lonlat.append([lon, lat])

            # 至少要有 3 個頂點才能構成建築平面
            if len(vertices_xy) >= 3:
                cleaned_buildings.append({
                    "id": b_index,
                    "osm_id": props.get('@id', f"b_{b_index}"),
                    "name": name or f"未命名建築 {b_index}",
                    "osm_named": 1 if props.get('name') else 0,   # 0＝名稱是依位置自動產生的
                    "height": round(height, 2),
                    "is_estimated": is_estimated,
                    "height_source": source_type,
                    "vertex_count": len(vertices_xy),
                    "vertices_xy": vertices_xy,          # 給 C 語言算陰影幾何用 (單位: 公尺)
                    "vertices_lonlat": vertices_lonlat   # 保留原始經緯度供 Python 地圖對照
                })
                b_index += 1

    # 4. 輸出整理後的精簡 JSON
    output_data = {
        "ref_origin": {"lat": REF_LAT, "lon": REF_LON},
        "building_count": len(cleaned_buildings),
        "buildings": cleaned_buildings
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"處理完成！共匯出 {len(cleaned_buildings)} 棟建築至 {output_path}")

if __name__ == '__main__':
    # 將檔名替換為你從 Overpass Turbo 下載的檔案名稱
    process_geojson('export.geojson', 'buildings.json')