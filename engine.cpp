// Local metric coordinates: x east, y north. The adapters only render these results.
#include "solar_model.hpp"
#include <array>
#include <limits>
#include <queue>
#include <string>
#include <utility>
#include <vector>

namespace {
struct Point {
    double x, y;
    Point operator+(Point b) const { return {x+b.x, y+b.y}; }
    Point operator-(Point b) const { return {x-b.x, y-b.y}; }
    Point operator*(double t) const { return {x*t, y*t}; }
};
using Ring = std::vector<Point>;
struct Box {
    double left = 1e20, bottom = 1e20, right = -1e20, top = -1e20;
    void add(Point p) {
        left = std::min(left,p.x); right = std::max(right,p.x);
        bottom = std::min(bottom,p.y); top = std::max(top,p.y);
    }
    bool contains(Point p) const {
        return left <= p.x && p.x <= right && bottom <= p.y && p.y <= top;
    }
};
struct Building { double height; Box box; std::vector<Ring> rings; };
struct Cast { Point offset; Box extent; };
struct Frame { ncu_solar::Angles sun; std::vector<Cast> casts; };
struct Edge { int a,b; double length,sun; };
struct Result { std::vector<int> nodes; std::vector<Point> points; double length=0, sun=0; };

std::vector<Building> buildings;
std::vector<Point> nodes;
std::vector<Edge> edges;
std::vector<std::vector<int>> adjacent;
Frame now, later;
double activeTime = std::numeric_limits<double>::quiet_NaN();
bool roadExposureReady = false;
std::string shadowPath;
Result result;
constexpr int nightCode = -1000000;

double cross(Point a, Point b) { return a.x*b.y-a.y*b.x; }
double distance(Point a, Point b) { return std::hypot(a.x-b.x,a.y-b.y); }
bool inRange(double a, double b, double v) {
    return std::min(a,b)-1e-8 <= v && v <= std::max(a,b)+1e-8;
}
bool onSegment(Point a, Point b, Point p) {
    return std::abs(cross(b-a,p-a)) <= 1e-7 &&
           inRange(a.x,b.x,p.x) && inRange(a.y,b.y,p.y);
}
bool intersects(Point a,Point b,Point c,Point d) {
    double abC=cross(b-a,c-a), abD=cross(b-a,d-a);
    double cdA=cross(d-c,a-c), cdB=cross(d-c,b-c);
    if (((abC>0 && abD<0)||(abC<0 && abD>0)) &&
        ((cdA>0 && cdB<0)||(cdA<0 && cdB>0))) return true;
    return onSegment(a,b,c)||onSegment(a,b,d)||onSegment(c,d,a)||onSegment(c,d,b);
}
// Even-odd membership retains concave footprints and interior courtyards.
bool inside(const Building& b, Point p) {
    if (!b.box.contains(p)) return false;
    bool in=false;
    for (const auto& ring:b.rings) {
        for (size_t i=0,j=ring.size()-1; i<ring.size(); j=i++) {
            Point a=ring[j], c=ring[i];
            if (onSegment(a,c,p)) return true;
            if ((a.y>p.y)!=(c.y>p.y) && p.x < (c.x-a.x)*(p.y-a.y)/(c.y-a.y)+a.x)
                in=!in;
        }
    }
    return in;
}
double shadowLength(double height,double elevation) {
    return elevation>0 ? height/std::tan(ncu_solar::radians(elevation)) : 0.0;
}
Frame makeFrame(double t) {
    Frame f{ncu_solar::calculate(t),{}};
    if (f.sun.elevation<=0) return f;
    const double az=ncu_solar::radians(f.sun.azimuth);
    const Point away{-std::sin(az),-std::cos(az)};
    for (const auto& b:buildings) {
        // All supported campus points and footprints are within 4 km of one another.
        const double reach=std::min(4000.0,shadowLength(b.height,f.sun.elevation));
        Point d=away*reach;
        Box extent=b.box;
        extent.add({b.box.left+d.x,b.box.bottom+d.y});
        extent.add({b.box.right+d.x,b.box.top+d.y});
        f.casts.push_back({d,extent});
    }
    return f;
}
bool castsOn(int i, const Frame& f, Point p) {
    const Cast& c=f.casts[i];
    if (!c.extent.contains(p)) return false;
    Point towardsSun=p-c.offset;
    for (const auto& ring:buildings[i].rings)
        for(size_t k=0,j=ring.size()-1;k<ring.size();j=k++)
            if(intersects(p,towardsSun,ring[j],ring[k])) return true;
    return false;
}
int classify(const Frame& f, Point p) {
    for (size_t i=0;i<buildings.size();++i)
        if(inside(buildings[i],p)) return static_cast<int>(i)+1;
    if(f.sun.elevation<=0) return nightCode;
    for(size_t i=0;i<buildings.size();++i)
        if(castsOn(static_cast<int>(i),f,p)) return -static_cast<int>(i)-1;
    return 0;
}
// All swept walls have one winding direction. A translated roof's inner rings
// have the opposite winding, so one nonzero SVG fill is the exact union.
void appendRing(const Point* points, size_t n, Point offset, bool positive) {
    if(n<3) return;
    double twiceArea=0;
    for(size_t i=0,j=n-1;i<n;j=i++) twiceArea+=cross(points[j],points[i]);
    if(std::abs(twiceArea)<1e-8) return;
    const bool forward=(twiceArea>0)==positive;
    for(size_t i=0;i<n;++i) {
        Point p=points[forward?i:n-1-i]+offset;
        shadowPath+=(i?'L':'M');
        shadowPath+=std::to_string(static_cast<int>(std::round(p.x*10)));
        shadowPath+=' ';
        shadowPath+=std::to_string(static_cast<int>(std::round(-p.y*10)));
    }
    shadowPath+='Z';
}
void drawShadows() {
    shadowPath.clear();
    for(size_t i=0;i<now.casts.size();++i) {
        Point d=now.casts[i].offset;
        const auto& rings=buildings[i].rings;
        for(size_t r=0;r<rings.size();++r) {
            const Ring& ring=rings[r];
            appendRing(ring.data(),ring.size(),d,r==0);
            for(size_t k=0,j=ring.size()-1;k<ring.size();j=k++) {
                std::array<Point,4> wall{ring[j],ring[k],ring[k]+d,ring[j]+d};
                appendRing(wall.data(),wall.size(),{0,0},true);
            }
        }
    }
}
double sunDistance(Point a,Point b) {
    if(now.sun.elevation<=0) return 0;
    const double length=distance(a,b);
    int count=std::max(1,static_cast<int>(std::ceil(length/2.0)));
    int lit=0;
    Point delta=b-a;
    for(int k=0;k<count;++k)
        if(classify(now,a+delta*((k+.5)/count))==0) ++lit;
    return length*lit/count;
}
void measureRoads() {
    if(roadExposureReady) return;
    for(auto& e:edges) e.sun=sunDistance(nodes[e.a],nodes[e.b]);
    roadExposureReady=true;
}
int shortestPath(const std::vector<Point>& points,const std::vector<Edge>& roadEdges,
                 const std::vector<std::vector<int>>& links,int start,int goal,double alpha) {
    result={};
    if(start<0 || goal<0 || static_cast<size_t>(std::max(start,goal))>=points.size() ||
       !std::isfinite(alpha) || alpha<1) return 0;
    std::vector<double> cost(points.size(),std::numeric_limits<double>::infinity());
    std::vector<int> previous(points.size(),-1);
    using Visit=std::pair<double,int>;
    std::priority_queue<Visit,std::vector<Visit>,std::greater<Visit>> pending;
    cost[start]=0; pending.push({0,start});
    while(!pending.empty()) {
        auto [best,u]=pending.top(); pending.pop();
        if(best>cost[u]) continue;
        if(u==goal) break;
        for(int id:links[u]) {
            const Edge& e=roadEdges[id];
            int v=(u==e.a)?e.b:e.a;
            double next=best+e.length+(alpha-1)*e.sun;
            if(next<cost[v]) {
                cost[v]=next; previous[v]=id; pending.push({next,v});
            }
        }
    }
    if(!std::isfinite(cost[goal])) return 0;
    for(int u=goal;;) {
        result.nodes.push_back(u);
        if(u==start) break;
        const Edge& e=roadEdges[previous[u]];
        result.length+=e.length; result.sun+=e.sun; u=(u==e.a)?e.b:e.a;
    }
    std::reverse(result.nodes.begin(),result.nodes.end());
    for(int i:result.nodes) result.points.push_back(points[i]);
    return static_cast<int>(result.nodes.size());
}

struct RoadStop { int edge; double fraction; int node=-1; };

// Split only the selected road pieces at the actual projected A/B positions.
// The caller's graph is local to this solve. A later pair cannot inherit these cuts.
void splitRoad(int id, RoadStop& start,RoadStop& goal,std::vector<Point>& points,
               std::vector<Edge>& roadEdges,std::vector<std::vector<int>>& links) {
    const Edge base=roadEdges[id];
    std::vector<std::pair<double,int>> cuts{{0,base.a},{1,base.b}};
    for(RoadStop* stop : {&start,&goal}) {
        if(stop->edge!=id) continue;
        auto existing=std::find_if(cuts.begin(),cuts.end(),[&](const auto& cut) {
            return std::abs(cut.first-stop->fraction)<1e-10;
        });
        if(existing!=cuts.end()) { stop->node=existing->second; continue; }
        stop->node=static_cast<int>(points.size());
        points.push_back(nodes[base.a]+(nodes[base.b]-nodes[base.a])*stop->fraction);
        links.emplace_back(); cuts.push_back({stop->fraction,stop->node});
    }
    if(cuts.size()==2) return;
    for(int n:{base.a,base.b}) {
        auto& list=links[n];list.erase(std::remove(list.begin(),list.end(),id),list.end());
    }
    std::sort(cuts.begin(),cuts.end());
    for(size_t i=1;i<cuts.size();++i) {
        int u=cuts[i-1].second, v=cuts[i].second, eid=static_cast<int>(roadEdges.size());
        double len=distance(points[u],points[v]);
        roadEdges.push_back({u,v,len,sunDistance(points[u],points[v])});
        links[u].push_back(eid);links[v].push_back(eid);
    }
}
} // namespace

extern "C" {
void reset_map() {
    buildings.clear(); nodes.clear(); edges.clear(); adjacent.clear();
    activeTime=std::numeric_limits<double>::quiet_NaN();
}
void add_building(double height) { buildings.push_back({height,{},{}}); }
void add_ring() { buildings.back().rings.emplace_back(); }
void add_vertex(double x,double y) {
    auto& b=buildings.back(); b.rings.back().push_back({x,y}); b.box.add({x,y});
}
void add_node(double x,double y) { nodes.push_back({x,y}); adjacent.emplace_back(); }
void add_edge(int a,int b) {
    int id=static_cast<int>(edges.size());
    edges.push_back({a,b,distance(nodes[a],nodes[b]),0});
    adjacent[a].push_back(id); adjacent[b].push_back(id);
}
void set_time(double unixSeconds) {
    if(activeTime==unixSeconds) return;
    activeTime=unixSeconds;
    now=makeFrame(unixSeconds); later=makeFrame(unixSeconds+1800);
    drawShadows(); roadExposureReady=false;
}
double solar_height_at(double t) { return ncu_solar::calculate(t).elevation; }
double reference_shadow() { return shadowLength(12,now.sun.elevation); }
double elevation() { return now.sun.elevation; }
double azimuth() { return now.sun.azimuth; }
const char* shadow_path() { return shadowPath.c_str(); }
int probe(double x,double y,int future) { return classify(future?later:now,{x,y}); }
int solve(int start,int goal,double alpha) {
    measureRoads();
    return shortestPath(nodes,edges,adjacent,start,goal,alpha);
}
int solve_between(int edgeA,double fractionA,int edgeB,double fractionB,double alpha) {
    result={};
    if(edgeA<0 || edgeB<0 || static_cast<size_t>(std::max(edgeA,edgeB))>=edges.size()
       || !(fractionA>=0 && fractionA<=1 && fractionB>=0 && fractionB<=1)) return 0;
    measureRoads();
    RoadStop a{edgeA,fractionA}, b{edgeB,fractionB};
    auto points=nodes;
    auto roadEdges=edges;
    auto links=adjacent;
    splitRoad(edgeA,a,b,points,roadEdges,links);
    if(edgeB!=edgeA) splitRoad(edgeB,a,b,points,roadEdges,links);
    return shortestPath(points,roadEdges,links,a.node,b.node,alpha);
}
double route_x(int i) { return result.points[i].x; }
double route_y(int i) { return result.points[i].y; }
int route_node(int i) { return result.nodes[i]; }
double route_length() { return result.length; }
double route_sun() { return result.sun; }
}
