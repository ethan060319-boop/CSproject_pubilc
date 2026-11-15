// map_loader.h
#ifndef MAP_LOADER_H
#define MAP_LOADER_H

// 節點結構
typedef struct VertexNode {
    double x;
    double y;
    struct VertexNode* prev;
    struct VertexNode* next;
} VertexNode;

typedef struct BuildingNode {
    int id;
    char name[100];
    double height;
    int vertex_count;
    VertexNode* vertices_head;
    struct BuildingNode* prev;
    struct BuildingNode* next;
} BuildingNode;

// 宣告所有function
//讀取檔案
void load_buildings(const char* filename, BuildingNode** head);
// 找特定高度的建築
void find_buildings_by_height(BuildingNode* head, double target_height);
// 更新特定建築的高度
void update_building_height(BuildingNode* head, int id, double new_height);
//有新增或修改建築物或id的話，將建築物名稱匯出到txt檔案 filename"building_names.txt"
void export_building_names_to_txt(BuildingNode* head, const char* filename);
//找特定建築物的位址
BuildingNode* get_building_by_name(BuildingNode* head, const char* target_name);
//找特定建築物的高度
double get_height_by_name(BuildingNode* head, const char* target_name);

#endif