"""Start the local Python + native C++ version of the campus map."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import os
import hashlib
import platform
from urllib.parse import parse_qsl,urlsplit
from build import render
from shade.campus import ROOT,load_campus
from shade.native import Model,compile_native

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",type=int,default=8000)
    port=parser.parse_args().port
    campus=load_campus()
    # A versioned per-user cache allows Windows to keep its loaded DLL open and
    # makes later launches instant. Publish compiled files only after a full build.
    cache=Path(os.environ.get("LOCALAPPDATA") or Path.home()/".cache")/"NCUShade"
    sources=(ROOT/"shade/engine.cpp").read_bytes()+(ROOT/"shade/solar_model.hpp").read_bytes()
    key=hashlib.sha256(sources+platform.platform().encode()+platform.machine().encode()).hexdigest()[:20]
    directory=cache/key
    directory.mkdir(parents=True,exist_ok=True)
    suffix=".dll" if os.name=="nt" else (".dylib" if platform.system()=="Darwin" else ".so")
    library=directory/("campus_shade"+suffix)
    if not library.exists():
        with tempfile.TemporaryDirectory(dir=directory) as temp:
            built=compile_native(temp)
            try:
                os.replace(built,library)
            except PermissionError:
                if not library.exists():
                    raise
    model=Model(library,campus)
    page=render(campus,native=True).encode()
    class Handler(BaseHTTPRequestHandler):
        def reply(self,status,mime,body):
            self.send_response(status)
            self.send_header("Content-Type",mime+"; charset=utf-8")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
        def do_GET(self):
            url=urlsplit(self.path)
            if url.path in {"/","/index.html"}:
                self.reply(200,"text/html",page)
            elif url.path=="/api/state":
                try:
                    data=model.state(dict(parse_qsl(url.query,keep_blank_values=True)))
                except (ValueError,KeyError,OverflowError):
                    self.reply(400,"application/json",b'{"error":"invalid simulation input"}')
                    return
                self.reply(200,"application/json",json.dumps(data,separators=(",",":")).encode())
            elif url.path=="/api/day":
                try:
                    data=model.day(dict(parse_qsl(url.query,keep_blank_values=True)))
                except (ValueError,KeyError,OverflowError):
                    self.reply(400,"application/json",b'{"error":"invalid day input"}')
                    return
                self.reply(200,"application/json",json.dumps(data,separators=(",",":")).encode())
            else:
                self.reply(404,"text/plain",b"Not found")
    with ThreadingHTTPServer(("127.0.0.1",port),Handler) as server:
        print(f"中大日影  http://127.0.0.1:{server.server_port}  (Ctrl+C 結束)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
if __name__=="__main__":
    main()
