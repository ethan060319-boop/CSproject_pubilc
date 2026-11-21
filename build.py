"""Build the self-contained index.html. Only rebuilding C++/Wasm needs a compiler."""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from shade.campus import ROOT, load_campus

EXPORTS = ("reset_map add_building add_ring add_vertex add_node add_edge set_time solar_height_at reference_shadow elevation "
           "azimuth shadow_path probe solve solve_between route_x route_y route_node route_length route_sun").split()

def compile_wasm():
    zig = os.environ.get("ZIG") or shutil.which("zig")
    if not zig:
        try:
            import ziglang
            zig = str(Path(ziglang.__file__).with_name("zig.exe" if os.name=="nt" else "zig"))
        except ImportError:
            sys.exit("Rebuilding Wasm requires Zig 0.14.1. Run: python -m pip install ziglang==0.14.1")
    subprocess.run([zig,"c++","-target","wasm32-wasi","-std=c++17","-Oz","-fno-exceptions",
                    "-fno-rtti","-mexec-model=reactor","-Wl,--strip-all",
                    *["-Wl,--export="+name for name in EXPORTS],"shade/engine.cpp",
                    "-o","shade/engine.wasm"],cwd=ROOT,check=True)

def render(campus=None, native=False):
    page = (ROOT/"web/page.html").read_text(encoding="utf-8")
    model = json.dumps(campus if campus is not None else load_campus(),
                       ensure_ascii=False,separators=(",",":"),allow_nan=False).replace("<","\\u003c")
    for key, value in (
        ("@@STYLE@@", (ROOT/"web/style.css").read_text(encoding="utf-8")),
        ("@@APP@@", (ROOT/"web/app.js").read_text(encoding="utf-8")),
        ("@@MODE@@", "native" if native else "wasm"),
        ("@@WASM@@", "" if native else base64.b64encode((ROOT/"shade/engine.wasm").read_bytes()).decode()),
        ("@@DATA@@", model),
    ):
        page = page.replace(key,value)
    return page

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wasm",action="store_true",help="recompile the shared C++ engine")
    args=parser.parse_args()
    if args.wasm:
        compile_wasm()
    (ROOT/"index.html").write_text(render(),encoding="utf-8")
    print("Built index.html")
