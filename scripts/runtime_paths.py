"""
统一的运行时路径管理 — 支持两种运行模式：
1. 开发模式：BASE_DIR = scripts/../（仓库根目录）
2. Electron 打包模式：读取环境变量 AI_PM_BASE_DIR 指向用户数据目录

所有涉及「用户可写」数据的路径（jobs_data.json, logs/, config/, .chrome_profile/）
均应通过本模块获取，以确保打包后能在 userData 目录中读写。
"""
import os
from pathlib import Path


def _script_dir() -> Path:
    """返回 scripts/ 目录绝对路径（静态，不随 env 变化）"""
    return Path(__file__).resolve().parent


def get_base_dir() -> Path:
    """
    返回 BASE_DIR（用户可写数据根目录）
    优先级: AI_PM_BASE_DIR env > scripts/../（开发模式默认）
    """
    env = os.environ.get('AI_PM_BASE_DIR', '').strip()
    if env:
        p = Path(env).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    return _script_dir().parent


def get_script_dir() -> Path:
    """返回 scripts/ 绝对路径（只读，位于 app bundle 内）"""
    return _script_dir()


def get_log_dir() -> Path:
    p = get_base_dir() / 'logs'
    p.mkdir(exist_ok=True)
    return p


def get_config_dir() -> Path:
    """
    config 目录：
    - 开发模式 = BASE_DIR/config
    - 打包模式 = userData/workspace/config（可编辑，UI 会修改这里）
    """
    p = get_base_dir() / 'config'
    p.mkdir(exist_ok=True)
    return p


def get_config_file() -> Path:
    return get_config_dir() / 'keywords.json'


def get_data_file() -> Path:
    return get_base_dir() / 'jobs_data.json'


def get_status_file() -> Path:
    return get_base_dir() / 'run_status.json'


def get_profile_dir() -> Path:
    """Chrome 用户资料目录（Cookie 持久化）"""
    p = get_base_dir() / '.chrome_profile'
    p.mkdir(exist_ok=True)
    return p


def get_history_dir() -> Path:
    p = get_base_dir() / 'history'
    p.mkdir(exist_ok=True)
    return p


# ========= 快捷常量（向后兼容） =========
SCRIPT_DIR = get_script_dir()
BASE_DIR = get_base_dir()
LOG_DIR = get_log_dir()
CONFIG_DIR = get_config_dir()
CONFIG_FILE = get_config_file()
DATA_FILE = get_data_file()
STATUS_FILE = get_status_file()
PROFILE_DIR = get_profile_dir()
HISTORY_DIR = get_history_dir()


if __name__ == '__main__':
    print(f'[runtime_paths] BASE_DIR    = {BASE_DIR}')
    print(f'[runtime_paths] SCRIPT_DIR  = {SCRIPT_DIR}')
    print(f'[runtime_paths] CONFIG_DIR  = {CONFIG_DIR}')
    print(f'[runtime_paths] DATA_FILE   = {DATA_FILE}')
    print(f'[runtime_paths] LOG_DIR     = {LOG_DIR}')
    print(f'[runtime_paths] PROFILE_DIR = {PROFILE_DIR}')
