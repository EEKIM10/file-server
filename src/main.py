import datetime
import os

import click
import logging
import configparser
from fastapi import FastAPI, Request, HTTPException, Header, Query, Path as QPath
from fastapi.responses import FileResponse, Response
from fastapi.middleware.gzip import GZipMiddleware
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from magic import Magic
from utils.logic import *

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.add_extension('jinja2.ext.loopcontrols')


def serve(directory: Path, etag: str = None, last_modified: str = None):
    logger = app.state.logger
    if not can_access(directory):
        logger.warning("File %r is not accessible.", directory)
        raise HTTPException(status_code=403, detail="Forbidden")

    changed = has_changed(etag, last_modified, directory)
    if not changed:
        logger.debug("Serving file %r (304)", directory)
        return Response(status_code=304)
    else:
        logger.debug("Serving file %r", directory)
        return FileResponse(
            directory,
            media_type=mime_type_from_file_ext(
                directory, guess_on_unsure=True, magic=app.state.mime
            ),
            filename=directory.name,
            content_disposition_type="inline",
        )


@app.get("/{path:path}")
def root(
        req: Request,
        path: str = QPath(),
        etag: str = Header(None, alias="If-None-Match"),
        last_modified: str = Header(None, alias="If-Modified-Since"),
        show_hidden: bool = Query(False, alias="show-hidden"),
):
    print(show_hidden)
    logger = app.state.logger.getChild("root")
    path = path or ""
    directory = app.state.root / path
    logger.info("Resolved %r to %r", path, directory)
    if not directory.exists():
        logger.debug("File or directory %r does not exist.", directory)
        raise HTTPException(status_code=404, detail="Directory or file found.")

    # if the path is above the root, raise 403 to prevent reverse navigation
    if not is_root_or_below(app, directory):
        logger.warning("File %r is not accessible (above root directory).", directory)
        raise HTTPException(status_code=403, detail="Forbidden")

    if not directory.is_dir():
        return serve(directory, etag, last_modified)

    files = []
    for file in directory.iterdir():
        file: Path
        try:
            stat = file.stat()
        except OSError:
            stat = None
        ZIP_EXTENSIONS = [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"]
        if file.suffix in ZIP_EXTENSIONS:
            file_type = "zip"
        elif file.is_dir():
            file_type = "folder"
        else:
            file_type = "file"

        if file.is_dir():
            try:
                size = "{:,}".format(len(list(file.iterdir())))
            except OSError:
                size = "?"
            unit = "items"
        else:
            try:
                size, unit = bytes_to_human(stat.st_size)
                size = round(size, 2)
            except (OSError, AttributeError):
                size = "?"
                unit = "B"

        locked = False
        if file.is_dir():
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
            }
        )

    return templates.TemplateResponse(
        "file_list.html.jinja",
        {
            "request": req,
            "files": files,
            "path": path,
            "root": app.state.root,
            "directory_str": os.path.sep + str(directory.relative_to(app.state.root).as_posix()),
            "show_hidden": show_hidden,
            "up": directory.parent.relative_to(app.state.root).as_posix(),
        }
    )


@click.command()
@click.option("top", "--root", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000)
@click.option("--config", default="config.ini", type=click.Path(exists=True, dir_okay=False))
def main(top: str, host: str, port: int, config: str):
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
                if not Path(top).exists():
                    logger.error("Root directory %r does not exist.", top)
                    return
                if not Path(top).is_dir():
                    logger.error("Root directory %r is not a directory.", top)
                    return
                if not can_access(Path(top)):
                    logger.error("Root directory %r is not accessible.", top)
                    return
                logger.info("Root directory set to %r", top)

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
                    handler.setLevel(log_level)
                    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s: %(message)s"))
                    logger.addHandler(handler)
                    logger.info("Log file set to %r", log_file)
    else:
        config = configparser.ConfigParser()

    app.state.root = Path(top)
    app.state.mime = Magic(mime=True, mime_encoding=True)
    app.state.config = config
    app.state.logger = logger
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
