"""Mastery Lab command line.

  python -m mastery_lab web  [--host 127.0.0.1] [--port 8765] [--db PATH]
  python -m mastery_lab mcp  [--db PATH]          # MCP server over stdio
  python -m mastery_lab seed [--db PATH]          # create DB + seed challenge only
"""

from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="mastery-lab", description="Mastery Lab — local learning loop POC")
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("web", help="run the local browser UI")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8765)
    w.add_argument("--db")
    m = sub.add_parser("mcp", help="run the MCP server on stdio")
    m.add_argument("--db")
    s = sub.add_parser("seed", help="initialise the database and seed challenge")
    s.add_argument("--db")
    args = p.parse_args(argv)

    from .db import DEFAULT_DB_PATH
    from .service import MasteryLab

    lab = MasteryLab(args.db or os.environ.get("MASTERY_LAB_DB") or DEFAULT_DB_PATH)

    if args.cmd == "web":
        import uvicorn

        from .web import create_app

        if args.host not in ("127.0.0.1", "localhost", "::1"):
            print(f"WARNING: binding to {args.host}. Mastery Lab has no authentication and is not "
                  "production-ready.", file=sys.stderr)
        print(f"Mastery Lab: http://{args.host}:{args.port}   (db: {lab.db_path})", file=sys.stderr)
        uvicorn.run(create_app(lab), host=args.host, port=args.port, log_level="warning")
    elif args.cmd == "mcp":
        from .mcp_server import build_server

        build_server(lab).run("stdio")
    else:
        print(f"Database ready at {lab.db_path}")


if __name__ == "__main__":
    main()
