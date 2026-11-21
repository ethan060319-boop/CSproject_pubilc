"use strict";
const $ = id => document.getElementById(id);
const campus = JSON.parse($("campusData").textContent);
const nss = "http://www.w3.org/2000/svg";
const nightCode = -1000000;
const stamp = (isoDate, minutes) => isoDate + "T" + clockText(minutes);
const clockText = minutes => String(Math.floor(minutes/60)).padStart(2,"0")+":"+String(minutes%60).padStart(2,"0");
const twParts = ms => {
    const local = new Date(ms + 8*3600000).toISOString();
    return {date:local.slice(0,10),minutes:Number(local.slice(11,13))*60+Number(local.slice(14,16))};
};
const toUnix = (date,minutes) => Date.parse(stamp(date,minutes)+":00+08:00")/1000;
const openedAt = twParts(Date.now());
const model = {
    ...openedAt, mode:null, area:0, routeRegion:null, alpha:4, picking:null, routeChoice:0,
    point:[-150.227,-14.035], pointLabel:"總圖書館西側步道",
    start:null, end:null
};
const camera = {x:0,y:0,scale:1};
let engine=null, scene=null, serial=0, playTimer=null, noticeTimer=null;
let dragging=null, resizeSize=null, autoFrame=true;
let selectedPoint=null, gpsRequest=0, activeOption=-1;

function icon(name) {
    const el=document.createElementNS(nss,"svg");
    el.setAttribute("class","ico"); el.setAttribute("aria-hidden","true");
    const use=document.createElementNS(nss,"use"); use.setAttribute("href","#i-"+name); el.append(use);
    return el;
}
function svg(tag,attrs={},text) {
    const el=document.createElementNS(nss,tag);
    for (const [key,val] of Object.entries(attrs)) el.setAttribute(key,val);
    if (text!==undefined) el.textContent=text;
    return el;
}
function html(tag,cls,text) {
    const el=document.createElement(tag); if(cls) el.className=cls;
    if(text!==undefined) el.textContent=text;
    return el;
}
function notify(message,timeout=3400) {
    clearTimeout(noticeTimer); const n=$("notice");
    n.textContent=message; n.hidden=!message;
    if(message && timeout) noticeTimer=setTimeout(()=>{n.hidden=true;},timeout);
}
function choose(select,value,label) {
    const option=document.createElement("option"); option.value=value; option.textContent=label; select.append(option);
}
function pathOf(pts,closed=false) {
    return pts.map(([x,y],i)=>(i?"L":"M")+x+" "+(-y)).join("")+(closed?"Z":"");
}
function bounds(pts) {
    let left=Infinity,right=-Infinity,top=-Infinity,bottom=Infinity;
    for(const [x,y] of pts){left=Math.min(left,x);right=Math.max(right,x);bottom=Math.min(bottom,y);top=Math.max(top,y);}
    return {left,right,bottom,top};
}
function nearestRoad(pt){
    let best=null;
    campus.edges.forEach(([u,v],edge)=>{
        const a=campus.nodes[u], b=campus.nodes[v], dx=b[0]-a[0], dy=b[1]-a[1];
        const f=Math.max(0,Math.min(1,((pt[0]-a[0])*dx+(pt[1]-a[1])*dy)/(dx*dx+dy*dy)));
        const xy=[a[0]+f*dx,a[1]+f*dy],dist=Math.hypot(xy[0]-pt[0],xy[1]-pt[1]);
        if(!best||dist<best.dist)best={edge,f,xy,raw:pt,dist,place:null};
    });
    return best;
}
function namedStop(name){
    const place=campus.places.find(p=>p.name===name);
    const edge=campus.edges.findIndex(([a,b])=>a===place.node||b===place.node);
    const xy=campus.nodes[place.node], raw=place.center;
    return {place:name,edge,f:campus.edges[edge][0]===place.node?0:1,xy,raw,dist:Math.hypot(raw[0]-xy[0],raw[1]-xy[1])};
}

async function bootWasm() {
    if(document.documentElement.dataset.engine==="native") return;
    const bytes=Uint8Array.from(atob($("wasmData").textContent.trim()),c=>c.charCodeAt(0));
    // The engine performs no file I/O. The linked C++ runtime declares these
    // WASI hooks for stderr handling; report BADF on this offline browser target.
    const wasi={fd_close:()=>8,fd_seek:()=>8,fd_write:()=>8};
    const {instance}=await WebAssembly.instantiate(bytes,{wasi_snapshot_preview1:wasi});
    const c=instance.exports; c._initialize(); c.reset_map();
    for(const b of campus.buildings){
        c.add_building(b.height);
        for(const r of b.rings){c.add_ring();for(const [x,y] of r)c.add_vertex(x,y);}
    }
    for(const [x,y] of campus.nodes)c.add_node(x,y);
    for(const [a,b] of campus.edges)c.add_edge(a,b);
    engine=c;
}
function wasmRoute(a,b,alpha) {
    const count=engine.solve_between(a.edge,a.f,b.edge,b.f,alpha);
    if(!count) return null;
    return {nodes:Array.from({length:count},(_,i)=>engine.route_node(i)),points:Array.from({length:count},(_,i)=>[engine.route_x(i),engine.route_y(i)]),length:engine.route_length(),sun:engine.route_sun()};
}
function getLocalScene(q) {
    const t=toUnix(model.date,model.minutes), midnight=t-model.minutes*60;
    engine.set_time(t);
    const pointer=engine.shadow_path(), bytes=new Uint8Array(engine.memory.buffer);
    const output={azimuth:engine.azimuth(), elevation:engine.elevation(),referenceShadow:engine.reference_shadow(),
        path:new TextDecoder().decode(bytes.subarray(pointer,bytes.indexOf(0,pointer))),
        day:Array.from({length:49},(_,i)=>engine.solar_height_at(midnight+i*1800))};
    if(q.has("x"))output.point=[engine.probe(...model.point,0),engine.probe(...model.point,1)];
    if(q.has("fromEdge"))output.routes=[wasmRoute(model.start,model.end,1),wasmRoute(model.start,model.end,model.alpha)];
    return output;
}
async function refresh() {
    const thisRequest=++serial;
    updateInputs();
    const q=new URLSearchParams({at:stamp(model.date,model.minutes)});
    if(model.mode==="point"){q.set("x",model.point[0]);q.set("y",model.point[1]);}
    else if(model.start&&model.end){
        for(const [prefix,stop] of [["from",model.start],["to",model.end]]){
            q.set(prefix+"Edge",stop.edge);q.set(prefix+"Fraction",stop.f);
        }
        q.set("alpha",model.alpha);
    }
    try {
        let next;
        if(document.documentElement.dataset.engine==="native"){
            const res=await fetch("api/state?"+q);
            if(!res.ok) throw new Error("計算服務未能讀取這組輸入");
            next=await res.json();
        }else{if(!engine)return;next=getLocalScene(q);}
        if(serial!==thisRequest)return;
        scene=next; $("shadow").setAttribute("d",scene.path);
        sunPanel(); results(); drawRoutes();
        if(autoFrame && model.mode==="route")frameRoute();
        else renderView();
    }catch(err){
        if(serial===thisRequest){stopPlay();scene=null;$("shadow").setAttribute("d","");$("routeLines").replaceChildren();
            $("pointTimes").replaceChildren();$("comparisons").replaceChildren();$("heightNote").textContent="";
            $("routeSummary").textContent="";renderWalk(null);navStatus();notify("模擬暫時無法更新，請重新載入頁面。",0);}
        console.error(err);
    }
}
function initMap() {
    const colors={grass:"#d6e3bc",wood:"url(#woodTexture)",water:"#bcdad6",pitch:"#d4dfbc",stream:"none"};
    const land=[...campus.land].sort((a,b)=>(a.kind==="stream")-(b.kind==="stream"));
    for(const v of land){
        const line=v.kind==="stream";
        $("land").append(svg("path",{d:pathOf(v.points,!line),fill:colors[v.kind],stroke:line?"#a6c9c4":v.kind==="water"?"#92b9b4":"#b9c9a8","stroke-width":line?2.2:.5,"stroke-linejoin":"round"}));
    }
    const walk=new Set(["footway","path","steps","pedestrian","cycleway"]);
    for(const pass of ["outline","fill"]){
        for(const v of campus.roads){
            const foot=walk.has(v.kind), width=foot?2.3: v.kind==="tertiary"?9:5.8;
            $("streets").append(svg("path",{d:pathOf(v.points),fill:"none",stroke:pass==="outline"?(foot?"#bfccb4":"#bec6b3"):"#fffdf0",
                "stroke-width":pass==="outline"?width+1:width,"stroke-linecap":"round","stroke-linejoin":"round"}));
        }
    }
    campus.buildings.forEach(b=>{
        b.bounds=bounds(b.rings[0]);
        $("footprints").append(svg("path",{d:b.rings.map(r=>pathOf(r,true)).join(""),fill:"#f3e8cd",stroke:"#968f74","stroke-width":.8,"stroke-linejoin":"round","fill-rule":"evenodd"}));
    });
    choose($("area"),"route","步行路線範圍");
    $("area").options[0].hidden=true;
    campus.areas.forEach((a,i)=>choose($("area"),i,a.name));
    const originSelect=$("start");
    choose(originSelect,"","點地圖上的目前位置");
    campus.places.forEach(place=>choose(originSelect,place.name,place.name+"附近"));
    choose(originSelect,"@map","地圖選取的位置");
    originSelect.lastElementChild.hidden=true;
    const counts=campus.buildings.reduce((s,b)=>(s[b.source]=(s[b.source]||0)+1,s),{});
    $("dataNote").textContent="小組的 OSM 建物與道路快照為 "+campus.timestamp+"，共 "+campus.buildings.length+
        " 棟建築。OSM 標註高度 "+(counts.osm_height||0)+" 棟，樓層換算 "+(counts.osm_levels||0)+
        " 棟（每層 3.5 m），人工估計 "+(counts.manual||0)+" 棟，其餘 "+(counts.default||0)+" 棟以 12 m 估算。虛線圈半徑 100 m，納入周邊建築可能投進圈內的陰影。";
}
function mapSize(){const r=$("map").getBoundingClientRect();return {w:Math.max(r.width,1),h:Math.max(r.height,1)};}
function frameArea(){
    const a=campus.areas[model.area],size=mapSize();
    camera.x=a.center[0];camera.y=a.center[1];
    camera.scale=Math.max(.65,Math.min(size.h/265,size.w/300));renderView();
}
function frameRoute(){
    const paths=scene?.routes?.filter(Boolean)||[];
    const stops=[model.start,model.end].filter(Boolean);
    const pts=stops.length===2 ? paths.flatMap(r=>r.points).concat(stops.flatMap(p=>[p.raw,p.xy]))
                              : campus.buildings.flatMap(b=>b.rings[0]);
    const box=bounds(pts),s=mapSize();
    camera.x=(box.left+box.right)/2; camera.y=(box.bottom+box.top)/2;
    camera.scale=Math.min(3.4,(s.w-86)/Math.max(45,box.right-box.left),(s.h-115)/Math.max(45,box.top-box.bottom));
    camera.scale=Math.max(.22,camera.scale); renderView();
}
function worldAt(clientX,clientY){
    const r=$("map").getBoundingClientRect();
    return [camera.x+(clientX-r.left-r.width/2)/camera.scale,camera.y-(clientY-r.top-r.height/2)/camera.scale];
}
function zoom(factor,focus=null){
    autoFrame=false;const old=camera.scale;
    camera.scale=Math.max(.24,Math.min(8,old*factor));
    if(focus){camera.x=focus[0]-(focus[0]-camera.x)*old/camera.scale;camera.y=focus[1]-(focus[1]-camera.y)*old/camera.scale;}
    renderView();
}
function renderView(){
    const box=mapSize(),s=camera.scale;
    camera.x=Math.max(-1110,Math.min(470,camera.x));camera.y=Math.max(-480,Math.min(590,camera.y));
    const width=box.w/s,height=box.h/s;
    $("map").setAttribute("viewBox",[camera.x-width/2,-camera.y-height/2,width,height].join(" "));
    const a=campus.areas[model.area];
    $("studyCircle").replaceChildren(svg("circle",{cx:a.center[0],cy:-a.center[1],r:100,fill:"none",stroke:"#678354","stroke-width":1.5,"stroke-dasharray":"6 5","vector-effect":"non-scaling-stroke"}));
    const useCircle=model.mode==="point" || model.routeRegion!==null;
    $("studyCircle").style.display=useCircle && $("showArea").checked?"":"none";
    $("rangeLegend").hidden=!useCircle;
    $("showArea").parentElement.hidden=!useCircle;
    $("shadowGroup").style.display=$("showShade").checked?"":"none";
    const bar=[5,10,20,25,50,100,200,500].filter(n=>n*s<=85).pop()||5;
    $("scaleLabel").textContent=bar+" m";$("scaleBar").style.width=(bar*s)+"px";
    drawLabels(width,height);drawMarks();
}
function drawLabels(width,height){
    const layer=$("mapLabels");layer.replaceChildren();if(!$("showLabels").checked)return;
    const s=camera.scale, candidates=[];
    const names=new Set(campus.places.slice(0,11).map(p=>p.name));
    for(const b of campus.buildings)if(b.name){
        const box=b.bounds,name=b.name.replace(/\(.*?\)/g,""),x=(box.left+box.right)/2,y=(box.top+box.bottom)/2;
        candidates.push({name,x,y,rank:names.has(b.name)?4:2,kind:"building"});
    }
    for(const v of campus.land)if(v.name && ["water","grass","pitch"].includes(v.kind)){
        const b=bounds(v.points);
        candidates.push({name:v.name,x:(b.left+b.right)/2,y:(b.top+b.bottom)/2,rank:3,kind:v.kind});
    }
    candidates.sort((a,b)=>b.rank-a.rank||Math.hypot(a.x-camera.x,a.y-camera.y)-Math.hypot(b.x-camera.x,b.y-camera.y));
    const used=[], seenLabels=[];const fs=Math.min(14,Math.max(10,10+1.7*s));
    for(const p of candidates){
        const px=(p.x-camera.x+width/2)*s,py=(camera.y+height/2-p.y)*s,w=p.name.length*fs;
        if(px<w/2+3||px>width*s-w/2-3||py<16||py>height*s-10||(px<190&&py<60)||(px>width*s-55&&py<68))continue;
        const b=[px-w/2-3,py-fs*.7,px+w/2+3,py+fs*.7];
        if(used.some(q=>q[0]<b[2]&&q[2]>b[0]&&q[1]<b[3]&&q[3]>b[1]))continue;
        if(seenLabels.some(q=>q.name===p.name&&Math.hypot(px-q.x,py-q.y)<96))continue;
        seenLabels.push({name:p.name,x:px,y:py});used.push(b);const color=p.kind==="water"?"#3b7577":p.kind==="building"?"#424e40":"#557947";
        layer.append(svg("text",{x:p.x,y:-p.y,"font-size":fs/s,"font-weight":p.rank===4?700:550,
            "text-anchor":"middle","dominant-baseline":"central",fill:color,stroke:"#fcfcf0","stroke-width":2.7/s,"paint-order":"stroke"},p.name));
    }
}
function mapPin(xy,label,color,point=false){
    const s=camera.scale,g=svg("g",{transform:"translate("+xy[0]+","+(-xy[1])+") scale("+(1/s)+")"});
    g.append(svg("circle",{r:point?11:9,fill:color,opacity:.18}));
    if(point){
        g.append(svg("circle",{r:5,fill:color,stroke:"#fffef8","stroke-width":2}));
        const w=label.length*13+23;
        g.append(svg("path",{d:"M0 -8v-7",stroke:color,"stroke-width":2}));
        g.append(svg("rect",{x:-w/2,y:-41,width:w,height:26,rx:7,fill:color,stroke:"#fffef4","stroke-width":1.5}));
        g.append(svg("text",{x:0,y:-23,"text-anchor":"middle",fill:"#fffef5","font-size":13,"font-weight":680},label));
    }else{
        g.append(svg("circle",{cy:-10,r:11,fill:color,stroke:"#fffef9","stroke-width":2}));
        g.append(svg("text",{y:-6.3,"text-anchor":"middle",fill:"white","font-size":12,"font-weight":750},label));
    }
    return g;
}
function drawMarks(){
    const g=$("mapMarks");g.replaceChildren();
    if(model.mode==="point"){g.append(mapPin(model.point,"查詢點","#224e3c",true));return;}
    for(const [stop,label,color] of [[model.start,"A","#245342"],[model.end,"B","#aa632c"]]){
        if(!stop)continue;
        if(stop.dist>1){
            g.append(svg("path",{d:pathOf([stop.raw,stop.xy]),stroke:color,"stroke-width":1.6,"stroke-dasharray":"3 3","vector-effect":"non-scaling-stroke"}));
            g.append(svg("circle",{cx:stop.raw[0],cy:-stop.raw[1],r:3/camera.scale,fill:"#fffef5",stroke:color,"stroke-width":1.2/camera.scale}));
        }
        g.append(mapPin(stop.xy,label,color));
    }
}
function drawRoutes(){
    const g=$("routeLines");g.replaceChildren();if(model.mode!=="route"||!scene?.routes)return;
    const active=scene.routes[model.routeChoice], other=scene.routes[1-model.routeChoice];
    for(const [r,color,width,dash] of [[other,"#965c2a",3,"5 5"],[active,"#fffef4",7.5,""],[active,"#13735a",5,""]]){
        if(!r)continue;
        g.append(svg("path",{d:pathOf(r.points),fill:"none",stroke:color,"stroke-width":width,
            "stroke-dasharray":dash,"stroke-linecap":"round","stroke-linejoin":"round","vector-effect":"non-scaling-stroke"}));
    }
}
function updateInputs(){
    $("date").value=model.date;$("clock").value=clockText(model.minutes);$("minutes").value=model.minutes;
    $("weight").value=model.alpha;$("alpha").textContent=model.alpha+" 倍";
    $("area").value=(model.mode==="route" && model.routeRegion===null)?"route":model.area;
    $("play").replaceChildren(icon(playTimer?"pause":"play"),document.createTextNode(playTimer?"暫停":"播放"));
    $("play").setAttribute("aria-pressed",String(Boolean(playTimer)));
}
function sunPanel(){
    const {azimuth:az,elevation:alt,day}=scene;
    const dir=["北","東北","東","東南","南","西南","西","西北"][Math.round(az/45)%8];
    $("altitude").textContent=alt.toFixed(1)+"°";$("bearing").textContent=az.toFixed(1)+"°";$("bearingName").textContent=dir;
    const castDir=["北","東北","東","東南","南","西南","西","西北"][(Math.round(az/45)+4)%8];
    $("castLength").textContent=alt>0?scene.referenceShadow.toLocaleString("zh-TW",{maximumFractionDigits:1})+" m · 向"+castDir:"無直射日光";
    $("daybadge").textContent=alt>0?"日照時段":"夜間";$("daybadge").classList.toggle("night",alt<=0);
    const y=a=>76-68*Math.max(0,a)/90;
    const line=day.map((a,i)=>(i?"L":"M")+(320*i/48).toFixed(2)+" "+y(a).toFixed(2)).join("");
    $("dayline").setAttribute("d",line);$("dayfill").setAttribute("d",line+"L320 76H0Z");
    const x=320*model.minutes/1440;
    $("cursorline").setAttribute("d","M"+x+" 4V76");$("sunDot").setAttribute("cx",x);$("sunDot").setAttribute("cy",y(alt));
    $("sunChart").setAttribute("aria-label","當日太陽高度曲線，所選時刻高度角 "+alt.toFixed(1)+" 度");
}
function statusOf(code){
    if(code===nightCode)return {label:"夜間",icon:"moon",cls:"night"};
    if(code===0)return {label:"有日照",icon:"sun",cls:"sun"};
    if(code>0)return {label:"建築內",icon:"building",cls:"indoor",building:campus.buildings[code-1]};
    return {label:"有遮蔭",icon:"shade",cls:"shaded",building:campus.buildings[-code-1]};
}
function heightText(b){
    if(!b)return "";
    const source={osm_height:"OSM 標註",osm_levels:"依樓層估算，每層 3.5 m",manual:"人工估計",default:"缺高度資料，採預設值"};
    return (b.name||"未命名建築")+" "+b.height+" m（"+source[b.source]+"）";
}
function results(){
    if(model.mode==="point"){
        const [x,y]=model.point, [lon0,lat0]=campus.origin;
        const lat=lat0+y/110574,lon=lon0+x/(111320*Math.cos(lat0*Math.PI/180));
        $("coords").textContent=lat.toFixed(5)+"° N · "+lon.toFixed(5)+"° E";
        const facts=scene.point.map(statusOf);
        $("pointName").textContent=model.pointLabel || (scene.point[0]>0 && facts[0].building.name) || "所選點位";
        const times=$("pointTimes");times.replaceChildren();
        facts.forEach((s,i)=>{
            const m=(model.minutes+30*i)%1440,after=i===1&&model.minutes+30>=1440;
            const group=html("div","pointBox "+s.cls),when=html("span","",i?"半小時後":"所選時刻");
            when.append(html("b","",(after?"次日 ":"")+clockText(m)));
            const state=html("span","condition");state.append(icon(s.icon),document.createTextNode(s.label));
            group.append(when,state);times.append(group);
        });
        const notes=[];
        facts.forEach((s,i)=>{
            if(s.building && !(i && s.building===facts[0].building)){
                const prefix=s.cls==="indoor"?"建築高度":i?"半小時後投影來源":"目前投影來源";
                notes.push(prefix+" · "+heightText(s.building));
            }
        });
        if(!notes.length)notes.push(facts[0].cls==="night"?"太陽位於地平線下。":"這個點在所選時刻沒有被模型中的建築遮住。");
        $("heightNote").textContent=notes.join("　／　");return;
    }
    routeResults();
}

const compass = ["北","東北","東","東南","南","西南","西","西北"];
const routeNames = ["最快步行","避曬步行"];
function estimatedTime(length){
    if(length<0.01)return "0 分鐘";
    const seconds=Math.max(10,Math.round(length/75*60/10)*10);
    const minutes=Math.floor(seconds/60), remainder=seconds%60;
    return (minutes?minutes+" 分":"")+(remainder?(minutes?" ":"")+remainder+" 秒":"鐘");
}
function stopLabel(stop){
    return stop?.place?stop.place+"附近":stop?.label||"地圖選取的位置";
}
function walkingLegs(points){
    if(points.length<2)return [];
    // Simplify for directions only. Distances come from the unsimplified road path.
    const along=[0], keep=[0];
    for(let i=1;i<points.length;i++){
        along.push(along[i-1]+Math.hypot(points[i][0]-points[i-1][0],points[i][1]-points[i-1][1]));
    }
    function corners(start,end){
        const [x,y]=points[start], dx=points[end][0]-x, dy=points[end][1]-y;
        const squared=dx*dx+dy*dy;
        let split=-1, widest=2.5;
        for(let i=start+1;i<end;i++){
            const ex=points[i][0]-x, ey=points[i][1]-y;
            const f=squared?Math.max(0,Math.min(1,(ex*dx+ey*dy)/squared)):0;
            const d=Math.hypot(ex-f*dx,ey-f*dy);
            if(d>widest){widest=d;split=i;}
        }
        if(split!==-1){corners(start,split);corners(split,end);}
        else keep.push(end);
    }
    corners(0,points.length-1);
    const legs=[];
    for(let i=1;i<keep.length;i++){
        const a=keep[i-1], b=keep[i], length=along[b]-along[a];
        if(length<0.01)continue;
        const bearing=(Math.atan2(points[b][0]-points[a][0],points[b][1]-points[a][1])*180/Math.PI+360)%360;
        const prev=legs.at(-1);
        const turn=prev?(bearing-prev.bearing+540)%360-180:0;
        if(prev&&Math.abs(turn)<32){prev.length+=length;continue;}
        const action=!prev?"出發":Math.abs(turn)>150?"迴轉":turn>0?"右轉":"左轉";
        legs.push({action,bearing,direction:compass[Math.round(bearing/45)%8],length});
    }
    return legs;
}
function renderWalk(route){
    const list=$("walkList");list.replaceChildren();
    $("walkGuide").hidden=!route;
    if(!route)return;
    $("walkTitle").textContent=routeNames[model.routeChoice]+"走法";
    if(route.length<0.01){list.append(html("li","","起終點在同一處路面，已抵達。"));return;}
    for(const leg of walkingLegs(route.points)){
        list.append(html("li","",leg.action+"，往"+leg.direction+"走約 "+Math.max(1,Math.round(leg.length))+" 公尺"));
    }
    list.append(html("li","","抵達 B · "+stopLabel(model.end)));
}
function navStatus(){
    const route=scene?.routes?.[model.routeChoice];
    const all=Boolean(model.start&&model.end);
    $("viewSteps").hidden=!route||!all;
    $("navLegend").hidden=!route||!all||model.mode!=="route";
    const which=model.picking||(!model.start?"start":!model.end?"end":null);
    if(which==="start")$("navInstruction").textContent="點一下地圖上你現在的位置，設定起點 A";
    else if(which==="end")$("navInstruction").textContent=(model.start?"起點已設定，":"")+"點地圖或搜尋要去的目的地 B";
    else if(route)$("navInstruction").textContent=routeNames[model.routeChoice]+"　約 "+estimatedTime(route.length)+" · "+Math.round(route.length)+" 公尺";
    else $("navInstruction").textContent=scene?.routes?"這兩點之間沒有相通的步道":"正在計算步行路線…";
}
function selectRoute(index){
    model.routeChoice=index;
    for(const [i,card] of [...$("comparisons").querySelectorAll("button")].entries()){
        card.setAttribute("aria-pressed",String(i===index));
    }
    drawRoutes();renderWalk(scene?.routes?.[index]);navStatus();
}
function routeResults(){
    const root=$("comparisons");root.replaceChildren();
    $("routeTime").textContent=clockText(model.minutes)+" · 避曬偏好 "+model.alpha+" 倍";
    $("swap").disabled=!model.start||!model.end;
    $("clearRoute").hidden=!model.start&&!model.end;
    const snapText=[["A",model.start],["B",model.end]].filter(([,p])=>p)
        .map(([side,p])=>side+" 距路面 "+Math.round(p.dist)+" m");
    $("snapNote").textContent=snapText.length?snapText.join(" · ")+"。距離從步道起算。":"";
    navStatus();
    if(!scene?.routes){
        root.append(html("p","routePrompt",!model.start?"選好起點與目的地後，這裡會顯示步行時間與每個轉彎。":"再選目的地，就能查看走法。"));
        $("routeSummary").textContent="";renderWalk(null);return;
    }
    const [a,b]=scene.routes;
    if(!a||!b){$("routeSummary").textContent="兩處位在不同的路網，請在相通的校園步道上重新選點。";renderWalk(null);return;}
    const night=scene.elevation<=0,grid=html("div","compareGrid");
    [a,b].forEach((r,i)=>{
        const card=html("button","compareBox"),head=html("span","compareHead");
        card.type="button";card.setAttribute("aria-pressed",String(i===model.routeChoice));
        card.onclick=()=>selectRoute(i);
        head.append(html("i","lineSample"),document.createTextNode(routeNames[i]));
        const m=Math.round(r.length),sun=Math.round(r.sun),shaded=Math.max(0,m-sun);
        card.append(head,html("strong","","約 "+estimatedTime(r.length)),html("span","walkDistance",m+" 公尺"),
            html("small","",night?"夜間無直射日光":"日照 "+sun+" m · 遮蔭 "+shaded+" m"));
        if(!night&&r.length>0)card.append(html("small","cost","遮蔭 "+Math.round(100*(r.length-r.sun)/r.length)+"% · 偏好成本 "+Math.round(r.length+(model.alpha-1)*r.sun)+" 等效公尺"));
        grid.append(card);
    });
    root.append(grid);
    const same=a.nodes.length===b.nodes.length&&a.nodes.every((v,i)=>v===b.nodes[i]);
    if(a.length<0.01)$("routeSummary").textContent="兩個端點對應到同一處路面。";
    else if(night)$("routeSummary").textContent="夜間沒有直射日光，兩種偏好都選最短路線。";
    else if(same)$("routeSummary").textContent=model.alpha===1?"偏好為 1 倍，兩條路線相同。":"這個時刻，最快路線也是目前偏好下的最佳避曬路線。";
    else $("routeSummary").textContent="改走避曬路線，約多走 "+Math.max(0,Math.round(b.length-a.length))+" m，少曬 "+Math.max(0,Math.round(a.sun-b.sun))+" m。";
    renderWalk(scene.routes[model.routeChoice]);
}
function stopPlay(){
    if(playTimer){clearInterval(playTimer);playTimer=null;}
    updateInputs();
}
function changeMinutes(delta){
    const next=twParts((toUnix(model.date,model.minutes)+delta*60)*1000);
    if(next.date<$("date").min||next.date>$("date").max){stopPlay();notify("已到可選日期邊界。");return;}
    model.date=next.date;model.minutes=next.minutes;refresh();
}
function setMode(mode,recompute=true){
    if(mode===model.mode)return;
    closePointActions();closePlaces();resetGPS();
    model.mode=mode;model.picking=null;model.routeRegion=null;autoFrame=true;scene=null;
    $("area").options[0].hidden=mode!=="route";
    document.querySelector("h1").textContent=mode==="route"?"校園步行導航":"校園避曬地圖";
    document.body.classList.toggle("route-on",mode==="route");
    for(const [id,on] of [["navPoint",mode==="point"],["navRoute",mode==="route"]]){
        $(id).classList.toggle("active",on);$(id).setAttribute("aria-pressed",String(on));
    }
    $("headHint").textContent=mode==="point"?"點一下地圖，看看哪裡有陰影。":"直接點地圖，或輸入目的地名稱。";
    $("navBar").hidden=mode!=="route";$("navLegend").hidden=true;
    $("routeSetup").hidden=mode!=="route";$("routeTeaser").hidden=mode==="route";
    $("routeResult").hidden=mode!=="route";$("pointResult").hidden=mode==="route";
    $("layerMenu").hidden=true;$("layersB").setAttribute("aria-expanded","false");notify("");
    $("routeLines").replaceChildren();
    setPicking(mode==="route"?(!model.start?"start":!model.end?"end":null):null,false);
    if(mode==="point")frameArea();else frameRoute();
    if(recompute)refresh();
}
function setPicking(which,scroll=false){
    model.picking=which;
    for(const [id,side] of [["pickA","start"],["pickB","end"]]){
        $(id).classList.toggle("active",which===side);$(id).setAttribute("aria-pressed",String(which===side));
    }
    closePointActions();
    if(model.mode==="route")navStatus();
    if(scroll && window.matchMedia("(max-width:720px)").matches)$("mapWrap").scrollIntoView({block:"center"});
}
function setEndpoint(side,stop){
    model[side]=stop;
    if(side==="start"){
        resetGPS();
        const select=$("start"), custom=select.lastElementChild;
        custom.hidden=!stop||Boolean(stop.place);
        if(stop&&!stop.place)custom.textContent=stopLabel(stop);
        select.value=stop?(stop.place||"@map"):"";
    }else{
        $("end").value=stop?(stop.place||stopLabel(stop)):"";
        closePlaces();
    }
}
function endpointChanged(){
    const next=!model.start?"start":!model.end?"end":null;
    model.routeChoice=0;scene=null;
    if(!next){model.routeRegion=null;autoFrame=true;}
    else autoFrame=false;
    setPicking(next);notify("");
    $("routeLines").replaceChildren();routeResults();drawMarks();refresh();
}
function hideGPSMessage(){
    $("gpsMessage").textContent="";$("gpsMessage").hidden=true;
}
function resetGPS(){
    gpsRequest++;$("gps").disabled=false;hideGPSMessage();
}
function gpsMessage(text){
    $("gpsMessage").textContent=text;$("gpsMessage").hidden=false;
}
function useGPS(){
    if(!navigator.geolocation){gpsMessage("這個瀏覽器無法定位，請點地圖設定起點。");return;}
    const request=++gpsRequest;
    $("gps").disabled=true;gpsMessage("正在取得裝置位置…");
    const fail=message=>{
        if(request!==gpsRequest)return;
        $("gps").disabled=false;gpsMessage(message);
    };
    navigator.geolocation.getCurrentPosition(({coords})=>{
        if(request!==gpsRequest)return;
        const [lon,lat]=campus.origin;
        const raw=[(coords.longitude-lon)*111320*Math.cos(lat*Math.PI/180),(coords.latitude-lat)*110574];
        const stop=nearestRoad(raw);
        if(!stop||stop.dist>100){
            fail("定位結果離中央大學步道超過 100 公尺，請在校園地圖上點選起點。");return;
        }
        stop.label="裝置目前位置";
        setEndpoint("start",stop);endpointChanged();
        gpsMessage("已用裝置定位設為 A，精度約 "+Math.round(coords.accuracy)+" 公尺。可點「我在這裡」微調。");
    },err=>fail(err.code===1?"未取得定位權限，請在地圖上點一下你的位置。":"目前無法取得位置，請在地圖上點選起點。"),
    {enableHighAccuracy:true,timeout:10000,maximumAge:30000});
}
function closePointActions(){
    selectedPoint=null;$("mapActions").hidden=true;
}
function showPointActions(pt){
    const near=nearestRoad(pt);
    if(!near||near.dist>100){closePointActions();return false;}
    selectedPoint=near;
    const p=campus.places.find(p=>Math.hypot(p.center[0]-pt[0],p.center[1]-pt[1])<=18);
    if(p)near.label=p.name+"附近";
    $("actionName").textContent=near.label||"所選地圖位置";
    $("mapActions").hidden=false;return true;
}
function usePoint(side){
    const stop=selectedPoint;
    if(!stop)return;
    if(model.mode!=="route")setMode("route");
    setEndpoint(side,stop);endpointChanged();
}
function pickPoint(pt){
    closePlaces();notify("");
    if(model.mode==="route"){
        const which=model.picking||(!model.start?"start":!model.end?"end":null);
        if(!showPointActions(pt)){notify("此處離校園步道超過 100 公尺，請改點附近道路。");return;}
        if(which)usePoint(which);
        return;
    }
    const a=campus.areas[model.area], offered=showPointActions(pt);
    if(Math.hypot(pt[0]-a.center[0],pt[1]-a.center[1])>a.radius){
        notify(offered?"此處可設為路線端點。遮蔭查詢請點圈內。":"遮蔭查詢請點 100 公尺示範圈內。");return;
    }
    model.point=pt;model.pointLabel="";refresh();
}
function closePlaces(){
    $("placeOptions").hidden=true;$("end").setAttribute("aria-expanded","false");
    $("end").removeAttribute("aria-activedescendant");activeOption=-1;
}
function chooseDestination(name){
    setEndpoint("end",namedStop(name));endpointChanged();$("end").blur();
}
function showPlaces(){
    const list=$("placeOptions"), field=$("end");
    const key=field.value.trim().toLocaleLowerCase();
    const names=campus.places.map(p=>p.name).filter(name=>!key||name.toLocaleLowerCase().includes(key));
    list.replaceChildren();activeOption=-1;field.removeAttribute("aria-activedescendant");
    if(!names.length)list.append(html("div","noMatches","沒有符合的地點，可改用地圖選目的地。"));
    names.forEach((name,i)=>{
        const option=html("button","",name);option.type="button";option.id="destOption"+i;option.tabIndex=-1;
        option.setAttribute("role","option");option.setAttribute("aria-selected","false");
        option.onmousedown=ev=>ev.preventDefault();
        option.onclick=()=>chooseDestination(name);
        list.append(option);
    });
    list.hidden=false;field.setAttribute("aria-expanded","true");
}
function searchKeys(event){
    if(event.isComposing)return;
    if(event.key==="Escape"){closePlaces();event.stopPropagation();return;}
    if(!["Enter","ArrowUp","ArrowDown"].includes(event.key))return;
    if($("placeOptions").hidden)showPlaces();
    const options=$("placeOptions").querySelectorAll("button");
    if(!options.length)return;
    event.preventDefault();
    if(event.key==="Enter"){options[Math.max(0,activeOption)].click();return;}
    if(activeOption>=0)options[activeOption].setAttribute("aria-selected","false");
    activeOption=activeOption<0?(event.key==="ArrowDown"?0:options.length-1):
        (activeOption+(event.key==="ArrowDown"?1:-1)+options.length)%options.length;
    options[activeOption].setAttribute("aria-selected","true");
    $("end").setAttribute("aria-activedescendant",options[activeOption].id);
    options[activeOption].scrollIntoView({block:"nearest"});
}
function setArea(){
    closePointActions();
    if($("area").value==="route"){model.routeRegion=null;autoFrame=true;frameRoute();return;}
    model.area=Number($("area").value);autoFrame=model.mode==="point";
    if(model.mode==="route")model.routeRegion=model.area;
    const a=campus.areas[model.area],place=campus.places.find(p=>p.name===a.anchor);
    model.point=model.area===0?[-150.227,-14.035]:[...campus.nodes[place.node]];
    model.pointLabel=model.area===0?"總圖書館西側步道":a.anchor+"附近道路";
    frameArea();refresh();
}
function bind(){
    $("help").onclick=()=>$("guide").showModal();$("closeHelp").onclick=()=>$("guide").close();
    $("guide").onclick=e=>{if(e.target===$("guide")){const r=$("guide").getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$("guide").close();}};
    $("navPoint").onclick=()=>setMode("point");$("navRoute").onclick=$("tryRoute").onclick=()=>setMode("route");
    $("date").onchange=()=>{const d=$("date");if(!d.value||!d.validity.valid){updateInputs();return;}const next=d.value;stopPlay();model.date=next;refresh();};
    function readClock(){const v=$("clock").value.trim(),m=/^(\d{1,2}):?(\d{2})$/.exec(v);
        if(!m||Number(m[1])>23||Number(m[2])>59){updateInputs();notify("時間請輸入 00:00 至 23:59。");return;}
        stopPlay();model.minutes=Number(m[1])*60+Number(m[2]);refresh();}
    $("clock").oninput=()=>{
        if (/^([01][0-9]|2[0-3]):?[0-5][0-9]$/.test($("clock").value))readClock();
    };
    $("clock").onblur=()=>{if($("clock").value!==clockText(model.minutes))readClock();};
    $("clock").onkeydown=e=>{if(e.key==="Enter"){readClock();$("clock").blur();}};
    $("minutes").oninput=()=>{const v=Number($("minutes").value);stopPlay();model.minutes=v;refresh();};
    $("earlier").onclick=()=>{stopPlay();changeMinutes(-30);};$("later").onclick=()=>{stopPlay();changeMinutes(30);};
    $("now").onclick=()=>{stopPlay();Object.assign(model,twParts(Date.now()));refresh();};
    $("play").onclick=()=>{if(playTimer){stopPlay();return;}playTimer=setInterval(()=>changeMinutes(10),900);changeMinutes(10);};
    $("area").onchange=setArea;
    $("zoomIn").onclick=()=>zoom(1.35);$("zoomOut").onclick=()=>zoom(1/1.35);
    $("recenter").onclick=()=>{autoFrame=true;model.routeRegion=null;updateInputs();model.mode==="route"?frameRoute():frameArea();};
    $("layersB").onclick=()=>{const m=$("layerMenu");m.hidden=!m.hidden;$("layersB").setAttribute("aria-expanded",String(!m.hidden));};
    for(const id of ["showShade","showArea","showLabels"])$(id).onchange=renderView;
    document.addEventListener("keydown",e=>{if(e.key==="Escape"){
        $("layerMenu").hidden=true;$("layersB").setAttribute("aria-expanded","false");closePointActions();closePlaces();
        setPicking(!model.start?"start":!model.end?"end":null);notify("");}});
    $("start").onchange=()=>{
        const name=$("start").value;if(name==="@map")return;
        setEndpoint("start",name?namedStop(name):null);endpointChanged();
    };
    $("end").onfocus=showPlaces;
    $("end").oninput=()=>{
        if(model.end){model.end=null;endpointChanged();}
        showPlaces();
    };
    $("end").onblur=closePlaces;$("end").onkeydown=searchKeys;
    $("gps").onclick=useGPS;
    $("fromHere").onclick=()=>usePoint("start");$("toHere").onclick=()=>usePoint("end");
    $("closeActions").onclick=closePointActions;
    $("viewSteps").onclick=()=>{
        $("walkTitle").focus({preventScroll:true});$("walkGuide").scrollIntoView({block:"center"});
    };
    $("swap").onclick=()=>{const a=model.start;setEndpoint("start",model.end);setEndpoint("end",a);endpointChanged();};
    $("demoRoute").onclick=()=>{
        setEndpoint("start",namedStop("工程一館"));setEndpoint("end",namedStop("教學研究綜合大樓"));endpointChanged();
    };
    $("clearRoute").onclick=()=>{
        setEndpoint("start",null);setEndpoint("end",null);model.routeRegion=null;autoFrame=true;
        endpointChanged();autoFrame=true;frameRoute();
    };
    $("weight").oninput=()=>{model.alpha=Number($("weight").value);refresh();};
    $("pickA").onclick=()=>setPicking("start",true);$("pickB").onclick=()=>setPicking("end",true);
    const map=$("map");
    map.addEventListener("wheel",ev=>{ev.preventDefault();zoom(Math.exp(-Math.sign(ev.deltaY)*.14),worldAt(ev.clientX,ev.clientY));},{passive:false});
    map.addEventListener("pointerdown",ev=>{
        if(!ev.isPrimary||ev.button!==0)return;
        dragging={id:ev.pointerId,px:ev.clientX,py:ev.clientY,x:camera.x,y:camera.y,moved:false};
        map.setPointerCapture(ev.pointerId);
    });
    map.addEventListener("pointermove",ev=>{
        if(!dragging||ev.pointerId!==dragging.id)return;
        const dx=ev.clientX-dragging.px,dy=ev.clientY-dragging.py;
        if(Math.hypot(dx,dy)>4)dragging.moved=true;
        if(dragging.moved){map.classList.add("dragging");autoFrame=false;
            camera.x=dragging.x-dx/camera.scale;camera.y=dragging.y+dy/camera.scale;renderView();}
    });
    map.addEventListener("pointerup",ev=>{
        if(!dragging||ev.pointerId!==dragging.id)return;
        const moved=dragging.moved;dragging=null;map.classList.remove("dragging");
        if(!moved)pickPoint(worldAt(ev.clientX,ev.clientY));
    });
    map.addEventListener("pointercancel",()=>{dragging=null;map.classList.remove("dragging");});
    map.addEventListener("keydown",ev=>{
        const k=ev.key,step=24/camera.scale;
        if(!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown","Enter","+","=","-"].includes(k))return;
        ev.preventDefault();if(k==="Enter"){pickPoint([camera.x,camera.y]);return;}
        if(k==="+"||k==="="||k==="-"){zoom(k==="-"?1/1.3:1.3);return;}
        autoFrame=false;if(k==="ArrowLeft")camera.x-=step;if(k==="ArrowRight")camera.x+=step;
        if(k==="ArrowUp")camera.y+=step;if(k==="ArrowDown")camera.y-=step;renderView();
    });
    new ResizeObserver(()=>{
        const s=mapSize();if(resizeSize&&s.w===resizeSize.w&&s.h===resizeSize.h)return;
        resizeSize=s;if(autoFrame){model.mode==="route"?frameRoute():frameArea();}else renderView();
    }).observe($("mapWrap"));
}
async function startApp(){
    initMap();bind();setMode(location.hash==="#shade"?"point":"route",false);
    try{await bootWasm();await refresh();}catch(err){notify("無法載入計算核心，可用 Python 版開啟地圖。",0);console.error(err);}
}
startApp();
