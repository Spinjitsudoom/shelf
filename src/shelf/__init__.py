"""Shelf: a self-hosted music server for your own CD rips."""

import logging

__version__ = "1.0.0"


def main() -> None:
    import sys

    # The packaged app runs its measuring helpers as itself: `shelf --module shelf.sound ...`.
    if len(sys.argv) > 2 and sys.argv[1] == "--module":
        import runpy

        module, sys.argv = sys.argv[2], [sys.argv[2], *sys.argv[3:]]
        runpy.run_module(module, run_name="__main__", alter_sys=True)
        return

    import argparse

    import uvicorn

    from .app import create_app
    from .config import load_config

    parser = argparse.ArgumentParser(prog="shelf", description="Self-hosted music server")
    parser.add_argument("--config", help="path to config.toml (default: ./config.toml)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from pathlib import Path

    cfg = load_config(Path(args.config) if args.config else None)
    app = create_app(cfg)
    print(f"\n  Shelf is running at http://localhost:{cfg.port}\n")
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning", proxy_headers=True)
