"""
RuView Scan - Config Loader
(RF PROBE v2.0 から継承・拡張)
"""

import logging
import os
from pathlib import Path

import yaml

from src.errors import ConfigError

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "default.yaml"


def load_config(path: str = None) -> dict:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        raise ConfigError(
            str(config_path),
            "Config file not found"
        )

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(str(config_path), f"YAML parse error: {e}")

    if config is None:
        config = {}

    env_overrides = {
        "RUVIEW_CSI_SOURCE": ("csi", "source"),
        "RUVIEW_CSI_PORT": ("csi", "udp_port"),
        "RUVIEW_SERVER_HOST": ("server", "host"),
        "RUVIEW_SERVER_PORT": ("server", "port"),
        "RUVIEW_LOG_LEVEL": ("logging", "level"),
    }

    for env_key, config_path_tuple in env_overrides.items():
        env_val = os.environ.get(env_key)
        if env_val is not None:
            section, key = config_path_tuple
            if section not in config:
                config[section] = {}
            if env_val.isdigit():
                config[section][key] = int(env_val)
            elif env_val.lower() in ("true", "false"):
                config[section][key] = env_val.lower() == "true"
            else:
                config[section][key] = env_val
            logger.info(f"Env override: {env_key} -> {section}.{key}={env_val}")

    return config
