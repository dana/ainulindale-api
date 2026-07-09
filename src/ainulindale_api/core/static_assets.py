import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def mount_static_assets(app: FastAPI) -> None:
    # Resolve paths relative to the current file
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    app.mount(
        "/assets/common",
        StaticFiles(directory=os.path.join(base_dir, "static", "common")),
        name="static_common",
    )
    app.mount(
        "/assets/main",
        StaticFiles(directory=os.path.join(base_dir, "apps", "main_site", "static")),
        name="static_main",
    )
    app.mount(
        "/assets/eridian-echo",
        StaticFiles(directory=os.path.join(base_dir, "apps", "eridian_echo", "static")),
        name="static_eridian_echo",
    )
    app.mount(
        "/assets/ops",
        StaticFiles(directory=os.path.join(base_dir, "apps", "ops_console", "static")),
        name="static_ops",
    )
    app.mount(
        "/assets/share",
        StaticFiles(directory=os.path.join(base_dir, "apps", "share", "static")),
        name="static_share",
    )
