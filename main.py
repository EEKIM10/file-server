import datetime
import json
import os
import platform
import sys

import click
import logging
import configparser
from fastapi import FastAPI, Request, HTTPException, Header, Query, Path as QPath, __version__ as __fastapi_version__
from fastapi.responses import FileResponse, Response
from fastapi.middleware.gzip import GZipMiddleware
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from magic import Magic
from utils.logic import *

__version__ = "0.1.0"

app = FastAPI(title="File Server", version=__version__, docs_url=None, redoc_url=None)

app.mount("/__static__", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.add_extension('jinja2.ext.loopcontrols')


def serve(
        directory: Path,
        etag: str = None,
        last_modified: str = None,
        method: str = "GET",
        stat: os.stat_result = None
):
    logger = app.state.logger
    if not can_access(directory):
        logger.warning("File %r is not accessible.", directory)
        raise HTTPException(status_code=403, detail="File is not accessible")

    changed = has_changed(etag, last_modified, directory)
    if not changed:
        logger.debug("Serving file %r (304)", directory)
        response = Response(status_code=304)
    else:
        logger.debug("Serving file %r", directory)
        response = FileResponse(
            directory,
            media_type=mime_type_from_file_ext(
                directory, guess_on_unsure=True, magic=app.state.mime
            ),
            filename=directory.name,
            content_disposition_type="inline",
            method=method,
        )
    if "Server.custom-headers" in app.state.config:
        for key, value in app.state.config["Server.custom-headers"].items():
            response.headers[key] = value
    return response


@app.get("/{path:path}")
def root(
        req: Request,
        path: str = QPath(),
        etag: str = Header(None, alias="If-None-Match"),
        etag2: str = Header(None, alias="If-Range"),
        last_modified: str = Header(None, alias="If-Modified-Since"),
        show_hidden: bool = Query(False, alias="show-hidden"),
        sort: str = Query('none', regex="(name|size|modified|none)"),
        reverse_sort: bool = Query(False)
):
    logger = app.state.logger.getChild("root")
    path = path or ""
    directory = app.state.root / path
    logger.debug("Resolved %r to %r", path, directory)
    if not directory.exists():
        logger.debug("File or directory %r does not exist.", directory)
        raise HTTPException(status_code=404, detail="Directory or file found.")

    # if the path is above the root, raise 403 to prevent reverse navigation
    if not is_root_or_below(app, directory):
        logger.warning("File %r is not accessible (above root directory).", directory)
        raise HTTPException(status_code=403, detail="File is not accessible on the web server.")
    
    if not can_access(directory):
        logger.warning("File %r is not accessible.", directory)
        raise HTTPException(status_code=403, detail="File is not accessible.")
        
    if not directory.is_dir():
        return serve(directory, etag or etag2 or None, last_modified or etag2)

    files = []
    try:
        _ = list(directory.iterdir())
    except PermissionError:
        raise HTTPException(403, "Inaccessible")
    for file in directory.iterdir():
        file: Path
        try:
            is_symlink = file.is_symlink()
        except (OSError, PermissionError):
            is_symlink = False
        else:
            if is_symlink:
                if "Server" in app.state.config:
                    if app.state.config["Server"].getboolean("follow-symlinks") is False:
                        is_symlink = False
                    else:
                        old_file = file
                        try:
                            file = file.resolve(True)
                        except FileNotFoundError:
                            file = file.resolve(False)
                            logger.warning(
                                f"symlink %s pointed to %s, but it does not exist.",
                                old_file,
                                file
                            )
                            raise HTTPException(
                                404,
                                "The file requested is a dead symbolic link."
                            )
                        else:
                            del old_file

        try:
            stat = file.stat(follow_symlinks=is_symlink)
            is_dir = file.is_dir()
        except (OSError, PermissionError):
            stat = None
            is_dir = None

        ZIP_EXTENSIONS = [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"]
        if file.suffix in ZIP_EXTENSIONS:
            file_type = "zip"
        elif is_dir:
            file_type = "folder"
        else:
            file_type = "file"

        if stat:
            if is_dir:
                try:
                    size = "{:,}".format(len(list(file.iterdir())))
                except (OSError, PermissionError):
                    size = "?"
                unit = "items"
            else:
                try:
                    size, unit = bytes_to_human(stat.st_size)
                    size = round(size, 2)
                except (OSError, PermissionError, AttributeError):
                    size = "?"
                    unit = "B"
        else:
            size = "?"
            unit = "?"

        locked = False
        if stat:
            if not can_access(file):
                locked = True
            if is_dir:
                if not can_access(file):
                    locked = True
                elif not is_root_or_below(app, file):
                    locked = True
            else:
                if not can_access(file):
                    locked = True
                elif not is_not_special_file(file):
                    locked = True
                elif not is_root_or_below(app, file):
                    locked = True
        else:
            locked = True  # if we can't stat() it we can't access it either

        files.append(
            {
                "name": file.name,
                "href": file.relative_to(app.state.root).as_posix(),
                "type": file_type,
                "locked": locked,
                "size": size,
                "modified": stat.st_mtime if stat else 0,
                "unit": unit,
                "hidden": file.name.startswith("."),
                "size_raw": stat.st_size if stat else 0
            }
        )

    version = "%s on Python/%d.%d.%d, FastAPI/%s, %s %s" % (
        __version__,
        sys.version_info.major,
        sys.version_info.minor,
        sys.version_info.micro,
        __fastapi_version__,
        platform.architecture()[0],
        platform.system(),
    )

    if sort.lower() != "none":
        match sort.lower():
            case 'name':
                files.sort(key=lambda entry: entry["name"])
            case 'size':
                files.sort(key=lambda entry: entry["size_raw"])
            case 'modified':
                files.sort(key=lambda entry: entry["modified"])
            case _:
                pass

    if reverse_sort:
        files.reverse()

    kwargs = {
        "request": req,
        "files": files,
        "path": path,
        "root": app.state.root,
        "directory_str": os.path.sep + str(directory.relative_to(app.state.root).as_posix()),
        "show_hidden": show_hidden,
        "up": os.path.sep + str(directory.relative_to(app.state.root).as_posix()) + "/..",
        "server_version": version,
        "sort": sort.lower(),
        "reverse_sort": reverse_sort
    }
    if "Server" in app.state.config:
        if app.state.config["Server"].getboolean("hide-version"):
            kwargs["server_version"] = "<redacted>"
    response = templates.TemplateResponse(
        "file_list.html.jinja",
        kwargs
    )
    if "Server.custom-headers" in app.state.config:
        for key, value in app.state.config["Server.custom-headers"].items():
            response.headers[key] = value
    return response


@click.command()
@click.option("top", "--root", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000)
@click.option("--config", default="config.ini", type=click.Path(exists=True, dir_okay=False))
def main(top: str, host: str, port: int, config: str):
    global app, templates
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s: %(message)s")
    logger = logging.getLogger("main")
    logger.info("Starting server with root directory %r", top)

    _config_path = Path(config)
    if config and Path(config).exists() and can_access(Path(config)):
        config = configparser.ConfigParser(
            allow_no_value=True,
            interpolation=configparser.ExtendedInterpolation(),
            strict=False,
        )
        config.read(_config_path)
        logger.info("Loading config...")
        if "Server" in config:
            if "host" in config["Server"]:
                host = config["Server"]["host"]
            if "port" in config["Server"]:
                port = config["Server"].getint("port")

            if "root" in config["Server"]:
                top = config["Server"]["root"]
                if not Path(top).expanduser().resolve().exists():
                    logger.error("Root directory %r does not exist.", top)
                    return
                if not Path(top).expanduser().resolve().is_dir():
                    logger.error("Root directory %r is not a directory.", top)
                    return
                if not can_access(Path(top).expanduser().resolve()):
                    logger.error("Root directory %r is not accessible.", top)
                    return
                logger.info("Root directory set to %r", top)

            if "htpasswd-file" in config["Server"]:
                file = Path(config["Server"]["htpasswd-file"])
                if not file.exists():
                    logger.critical("htpasswd file does not exist.")

        if "GZip" in config:
            minimum_size_b = 5 * 1024 * 1024
            level = 5
            if "minimum_size" in config["GZip"]:
                minimum_size_mb = config["GZip"].getint("minimum_size_mb")
                minimum_size_b = minimum_size_mb * 1024 * 1024

            if "level" in config["GZip"]:
                level = config["GZip"].getint("level")
                if level < 1 or level > 9:
                    logger.error("GZip level must be between 1 and 9, inclusive.")
                    return

            if "enable" in config["GZip"]:
                if config["GZip"].getboolean("enable"):
                    logger.info("Enabling GZip")
                    app.add_middleware(GZipMiddleware, minimum_size=minimum_size_b, compresslevel=level)

        if "Logging" in config:
            if "level" in config["Logging"]:
                log_level = config["Logging"]["level"]
                logger.setLevel(log_level.upper())
                logger.info("Log level set to %r", log_level)
            else:
                log_level = logging.INFO

            if "path" in config["Logging"]:
                log_file = config["Logging"]["path"]
                if log_file:
                    handler = logging.FileHandler(log_file)
                    handler.setLevel(log_level.upper())
                    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s: %(message)s"))
                    logger.addHandler(handler)
                    logger.info("Log file set to %r", log_file)
        
        if "Server.fastapi-args" in config:
            kwargs = {"title": "File Server", "description": "A simple file server.", "version": __version__, "docs_url": None, "redoc_url": None}
            for key, value in config["Server.fastapi-args"].items():
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
                kwargs[key] = value
            app = FastAPI(title="File Server", version=__version__, docs_url=None, redoc_url=None)

            app.state.logger = logger
            app.mount("/__static__", StaticFiles(directory="static"), name="static")
            templates = Jinja2Templates(directory="templates")
            templates.env.add_extension('jinja2.ext.loopcontrols')
            app.add_api_route("/{path:path}", root, methods=["GET"])
    else:
        config = configparser.ConfigParser()

    app.state.root = Path(top).expanduser().resolve().absolute()
    app.state.mime = Magic(mime=True, mime_encoding=True)
    app.state.config = config
    app.state.logger = logger

    kwargs = {}

    if "Server.uvicorn-args" in config:
        for key, value in config["Server.uvicorn-args"].items():
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
            kwargs[key] = value
    uvicorn.run(app, host=host, port=port, **kwargs)


if __name__ == "__main__":
    main()
