"""Cấu hình và đường dẫn dùng chung trong project."""

import logging.config
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    with (PROJECT_ROOT / "config/project.yaml").open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def project_path(path: str) -> Path:
    return (PROJECT_ROOT / path).resolve()


def setup_logging() -> None:
    with (PROJECT_ROOT / "config/logging.yaml").open(encoding="utf-8") as file:
        logging.config.dictConfig(yaml.safe_load(file))
