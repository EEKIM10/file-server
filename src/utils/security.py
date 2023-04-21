import subprocess
import logging
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pathlib import Path


def verify_htpasswd(file: Path, username: str, password: str):
    """Verifies a user's ht password using htpasswd"""
    return subprocess.run(
        ("htpasswd", "-i", "-v", username, str(file.resolve().absolute())),
        capture_output=True,
        input=password,
        encoding="utf-8"
    ).returncode == 0


sec = HTTPBasic()


def http_basic(app, enable: bool = False) -> "Depends":
    def wrap(credentials: HTTPBasicCredentials = Depends(sec)):
        logger = app.state.logger
        config = app.state.config
        if "Server" in config:
            if "htpasswd-file" in config:
                htpasswd_file = config["Server"]["htpasswd-file"]
                if not htpasswd_file.exists():
                    logger.warning("ht password file not found! check your configuration.")
                    raise HTTPException(403, "password file not found")
                try:
                    verified = verify_htpasswd(htpasswd_file, credentials.username, credentials.password)
                    logger.debug("Authenticated: %s", verified)
                except FileNotFoundError:
                    logger.warning("Failed to perform htpasswd verification - is apache-tools installed?")
                    raise HTTPException(403, "Failed to load password file")
                else:
                    if not verified:
                        raise HTTPException(
                            401,
                            "No",
                            {
                                "WWW-Authenticate": "Basic"
                            }
                        )
                    return True
            else:
                logger.debug("htpassword not set.")
                return True
        else:
            logger.debug("Server block not configured")
            return True
    if not enable:
        return Depends(lambda: True)
    return Depends(wrap)
