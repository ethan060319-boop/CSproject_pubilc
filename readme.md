# 中央大學建築圖資讀取模組 (Map Loader)

這個模組負責將 OpenStreetMap 的 JSON 資料讀取進 C 語言以雙向鏈結串列儲存為資料庫，並提供查詢建築高度與座標的 FUNCTION，供後續陰影幾何與避曬地圖計算使用。

## 檔案說明
* `map_loader.c` / `map_loader.h`：讀取與查詢函式。
*  `read_geojson.py`/讀取建築物原始資料

* `cJSON.c` / `cJSON.h`：JSON 解析套件。
*  `buildings.json`/建築物所有資料
*  `export.geojson`/建築物原始資料
下列為https://overpass-turbo.eu/
中抓取資料的程式碼
```
[out:json][timeout:25];

// 1. 鎖定「國立中央大學」的校園範圍
area["name"="國立中央大學"]->.ncu;

// 2. 同時抓取校內的「道路」與「建築」
(
  way["highway"](area.ncu);
  way["building"](area.ncu);
  relation["building"](area.ncu);
);

// 3. 輸出結果與節點座標
out body;
>;
out skel qt;
```

## 使用方式

請在你的主程式引入標頭檔：
```c
#include "map_loader.h"