#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include "cJSON.h"

// 儲存平面座標的頂點節點 (雙向鏈結)
typedef struct VertexNode {
    double x;
    double y;
    struct VertexNode* prev;
    struct VertexNode* next;
} VertexNode;

// 儲存建築物資訊的節點 (雙向鏈結)
typedef struct BuildingNode {
    int id;
    char name[100];      // 建築名稱
    double height;        // 建築高度 h
    int vertex_count;
    VertexNode* vertices_head; // 指向該建築第一個頂點
    struct BuildingNode* prev;
    struct BuildingNode* next;
} BuildingNode;

// 1. 讀取實體檔案轉為字串的底層函式
char* read_file_to_string(const char* filename) {
    FILE* file = fopen(filename, "r");
    if (!file) {
        printf("無法開啟檔案: %s\n", filename);
        return NULL;
    }
    fseek(file, 0, SEEK_END);
    long length = ftell(file);
    fseek(file, 0, SEEK_SET);

    char* data = (char*)malloc(length + 1); //結束字元
    if (data) {
        fread(data, 1, length, file);
        data[length] = '\0';
    }
    fclose(file);
    return data;
}

// 2. 將 JSON 轉為雙向鏈結串列 (原有的函式)
void load_buildings(const char* filename, BuildingNode** head) {
    char* json_data = read_file_to_string(filename);
    if (!json_data) return;

    cJSON* root = cJSON_Parse(json_data);//將字串轉回cjson格式，head是指向cjson的根節點
    if (!root) {
        printf("JSON 解析失敗: %s\n", cJSON_GetErrorPtr());
        free(json_data);
        return;
    }
    cJSON* buildings = cJSON_GetObjectItem(root, "buildings");//取得建築物陣列
    cJSON* building_item = NULL;//用來儲存建築物陣列的指標，類似tmp
    
    BuildingNode* current_tail = NULL;

    cJSON_ArrayForEach(building_item, buildings) {
        BuildingNode* new_b = (BuildingNode*)malloc(sizeof(BuildingNode));
        new_b->id = cJSON_GetObjectItem(building_item, "id")->valueint;//取得ID by int
        strcpy(new_b->name, cJSON_GetObjectItem(building_item, "name")->valuestring);//取得名稱 by string
        new_b->height = cJSON_GetObjectItem(building_item, "height")->valuedouble;//取得高度 by double
        new_b->vertex_count = cJSON_GetArraySize(cJSON_GetObjectItem(building_item, "vertices_xy"));//取得頂點數量 by int
        new_b->vertices_head = NULL;
        new_b->next = NULL;
        new_b->prev = current_tail;
        
        if (current_tail) current_tail->next = new_b;
        else *head = new_b; // 將第一棟建築的記憶體位址交給 main 函式的 head
        current_tail = new_b;

        cJSON* vertices = cJSON_GetObjectItem(building_item, "vertices_xy");//取得建築物頂點陣列
        cJSON* v_item = NULL;
        VertexNode* v_tail = NULL;

        cJSON_ArrayForEach(v_item, vertices) {
            VertexNode* new_v = (VertexNode*)malloc(sizeof(VertexNode));
            new_v->x = cJSON_GetObjectItem(v_item, "x")->valuedouble;
            new_v->y = cJSON_GetObjectItem(v_item, "y")->valuedouble;
            new_v->next = NULL;
            new_v->prev = v_tail;

            if (v_tail) v_tail->next = new_v;
            else new_b->vertices_head = new_v;
            v_tail = new_v;
        }
    }
    cJSON_Delete(root);
    free(json_data);
}





// 3. 尋找並讀取符合特定高度條件的建築
void find_buildings_by_height(BuildingNode* head, double target_height) {
    BuildingNode* current = head;
    printf("--- 尋找高度大於等於 %.2f 公尺的建築 ---\n", target_height);
    while (current != NULL) {
        if (current->height >= target_height) {
            printf("建築 ID: %d | 名稱: %s | 高度: %.2f m\n", current->id, current->name, current->height);
        }
        current = current->next; // 走到下一個節點
    }
}

// 4. 更新/覆寫特定建築的高度 (新增/修改)
void update_building_height(BuildingNode* head, int id, double new_height) {
    BuildingNode* current = head;
    while (current != NULL) {
        if (current->id == id) {
            current->height = new_height;
            printf("已將建築 ID %d 的高度更新為 %.2f m\n", id, new_height);
            return;
        }
        current = current->next;
    }
    printf("找不到建築 ID %d\n", id);
}

// 將所有建築 ID 與名稱匯出到 txt 檔案中，建立對照表
void export_building_names_to_txt(BuildingNode* head, const char* filename) {
    if (head == NULL) {
        printf("沒有建築資料可供匯出。\n");
        return;
    }

    // 嘗試開啟檔案準備寫入，"w" 模式代表若檔案不存在會自動建立，存在則會清空覆寫
    FILE *file = fopen(filename, "w");
    if (file == NULL) {
        printf("無法建立或開啟檔案: %s\n", filename);
        return;
    }

    // 印出標頭格式
    fprintf(file, "=== 建築物 ID 與名稱對照表 ===\n");
    fprintf(file, "ID\t|\t名稱\n");
    fprintf(file, "-----------------------------------\n");

    BuildingNode* current = head;
    int count = 0;
    
    // 走訪雙向鏈結串列
    while (current != NULL) {
        // 將 ID 和名字寫入 txt 檔案（\t 是 Tab 鍵，用來對齊）
        fprintf(file, "%d\t|\t%s\n", current->id, current->name);
        current = current->next;
        count++;
    }

    fclose(file); // 記得關閉檔案以釋放資源
    printf("✅ 成功匯出 %d 筆建築名稱對照表至「%s」\n", count, filename);
}

//透過名稱尋找建築，找到則回傳該節點指標，找不到則回傳 NULL
BuildingNode* get_building_by_name(BuildingNode* head, const char* target_name) {
    BuildingNode* current = head;
    while (current != NULL) {
        if (strcmp(current->name, target_name) == 0) {
            return current; // 回傳整包建築資料
        }
        current = current->next;
    }
    printf("警告：找不到名稱為「%s」的建築物。\n", target_name);
    return NULL;
}

// 直接透過名字拿高度
double get_height_by_name(BuildingNode* head, const char* target_name) {
    BuildingNode* target = get_building_by_name(head, target_name);
    if (target != NULL) {
        return target->height;
    }
    return -1.0; // 回傳 -1 代表沒找到
}