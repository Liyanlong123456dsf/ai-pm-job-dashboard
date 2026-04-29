#!/usr/bin/env python3
"""
BOSS 账号池管理

每个账号对应一个独立的 Chrome Profile 目录，Cookie 互不影响。
auto_daily.py 的每轮开始时通过 pick_next_account() 选一个 healthy 账号，
若登录检查失败则 mark_failure() 并切到下一个，直到成功或全部失效。

配置：config/boss_accounts.json
运行时状态：logs/account_pool_state.json
"""
import os
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict

SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
CONFIG_FILE = BASE_DIR / 'config' / 'boss_accounts.json'
STATE_FILE = BASE_DIR / 'logs' / 'account_pool_state.json'

# 兼容旧行为：没有 boss_accounts.json 时降级为单账号
LEGACY_PROFILE_DIR = '.chrome_profile'

logger = logging.getLogger('account_pool')
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [account_pool] %(levelname)s: %(message)s',
    )


# ============ IO helpers ============

def _safe_load_json(path: Path, default=None):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        logger.warning(f'读取 {path.name} 失败: {e}')
    return default if default is not None else {}


def _safe_write_json(path: Path, payload) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        return True
    except Exception as e:
        logger.warning(f'写入 {path.name} 失败: {e}')
        return False


def _now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
    except Exception:
        return None


# ============ 配置加载 ============

def load_config() -> dict:
    """加载账号池配置；不存在/无效时返回降级单账号配置"""
    cfg = _safe_load_json(CONFIG_FILE, default={})
    accounts = cfg.get('accounts') or []
    enabled = [a for a in accounts if a.get('enabled', True) and a.get('alias') and a.get('profile_dir')]
    if not enabled:
        # 降级：用旧的 .chrome_profile 作为唯一账号
        enabled = [{'alias': '默认', 'profile_dir': LEGACY_PROFILE_DIR, 'enabled': True}]
    settings = cfg.get('pool_settings') or {}
    return {
        'accounts': enabled,
        'settings': {
            'min_account_rest_min': int(settings.get('min_account_rest_min', 5) or 5),
            'all_failed_cooldown_min': int(settings.get('all_failed_cooldown_min', 60) or 60),
            'alert_throttle_min': int(settings.get('alert_throttle_min', 60) or 60),
            'recovery_check_min': int(settings.get('recovery_check_min', 30) or 30),
        },
    }


def is_multi_account_enabled() -> bool:
    """判断是否真正启用了多账号（>=2 个 enabled 账号）"""
    cfg = load_config()
    return len(cfg['accounts']) >= 2


# ============ 状态管理 ============

def _load_state() -> dict:
    state = _safe_load_json(STATE_FILE, default={})
    state.setdefault('accounts', {})
    state.setdefault('current_account', '')
    state.setdefault('last_alert_ts', 0)
    return state


def _save_state(state: dict):
    _safe_write_json(STATE_FILE, state)


def _ensure_account_entry(state: dict, alias: str) -> dict:
    entry = state['accounts'].get(alias)
    if not entry:
        entry = {
            'alias': alias,
            'status': 'healthy',         # healthy | failed | cooling_down
            'last_ok': '',
            'last_fail': '',
            'last_fail_detail': '',
            'fail_count': 0,
            'success_count': 0,
            'last_used': '',
        }
        state['accounts'][alias] = entry
    return entry


def get_account_profile_dir(alias: str) -> Optional[str]:
    cfg = load_config()
    for acc in cfg['accounts']:
        if acc['alias'] == alias:
            return acc['profile_dir']
    return None


# ============ 核心 API ============

def pick_next_account(exclude: Optional[List[str]] = None) -> Optional[dict]:
    """
    选一个账号执行下一轮。
    策略：
      1. 所有 healthy 账号中选 last_used 最久远的（负载均衡）
      2. 没有 healthy 时：选 last_fail 最久远的 failed 账号重试
      3. 都没有：返回 None
    exclude: 本轮已经尝试过的 alias 列表
    返回: {'alias': str, 'profile_dir': str, 'status': str} 或 None
    """
    exclude = set(exclude or [])
    cfg = load_config()
    state = _load_state()

    accounts = cfg['accounts']
    if not accounts:
        return None

    # 按配置确保每个账号都有 state entry
    for acc in accounts:
        _ensure_account_entry(state, acc['alias'])

    now = datetime.now()
    min_rest_sec = cfg['settings']['min_account_rest_min'] * 60

    def _score(alias_entry, prefer_healthy: bool):
        """分数越低越优先选"""
        alias = alias_entry['alias']
        entry = state['accounts'].get(alias, {})
        last_used_dt = _parse_dt(entry.get('last_used', '')) or datetime(2000, 1, 1)
        # 优先选 last_used 最久远的
        return last_used_dt

    # 候选列表（排除 exclude）
    candidates = [a for a in accounts if a['alias'] not in exclude]
    if not candidates:
        return None

    # 1) 先找 healthy 且休息时间足够的
    healthy = []
    for acc in candidates:
        entry = state['accounts'].get(acc['alias'], {})
        if entry.get('status') == 'healthy':
            last_used_dt = _parse_dt(entry.get('last_used', ''))
            if last_used_dt and (now - last_used_dt).total_seconds() < min_rest_sec:
                # 休息不够：仅在没有其它 healthy 时可用
                continue
            healthy.append(acc)

    if healthy:
        chosen = sorted(healthy, key=lambda a: _score(a, True))[0]
        return {
            'alias': chosen['alias'],
            'profile_dir': chosen['profile_dir'],
            'status': 'healthy',
        }

    # 2) 没有 healthy 可用：找所有 healthy（忽略休息时间）
    healthy_any = [a for a in candidates if state['accounts'].get(a['alias'], {}).get('status') == 'healthy']
    if healthy_any:
        chosen = sorted(healthy_any, key=lambda a: _score(a, True))[0]
        return {
            'alias': chosen['alias'],
            'profile_dir': chosen['profile_dir'],
            'status': 'healthy',
        }

    # 3) 所有账号都 failed：挑 last_fail 最久的重试（可能 Cookie 已恢复）
    recovery_min = cfg['settings']['recovery_check_min']
    retriables = []
    for acc in candidates:
        entry = state['accounts'].get(acc['alias'], {})
        last_fail_dt = _parse_dt(entry.get('last_fail', ''))
        if not last_fail_dt:
            retriables.append((acc, datetime(2000, 1, 1)))
            continue
        if (now - last_fail_dt).total_seconds() >= recovery_min * 60:
            retriables.append((acc, last_fail_dt))

    if retriables:
        retriables.sort(key=lambda x: x[1])  # last_fail 最久远的优先
        chosen = retriables[0][0]
        return {
            'alias': chosen['alias'],
            'profile_dir': chosen['profile_dir'],
            'status': 'retry_failed',
        }

    return None


def mark_success(alias: str):
    """标记账号登录成功"""
    if not alias:
        return
    state = _load_state()
    entry = _ensure_account_entry(state, alias)
    now_str = _now_str()
    was_failed = entry.get('status') == 'failed'
    entry['status'] = 'healthy'
    entry['last_ok'] = now_str
    entry['last_used'] = now_str
    entry['fail_count'] = 0
    entry['success_count'] = int(entry.get('success_count', 0) or 0) + 1
    state['current_account'] = alias
    _save_state(state)
    logger.info(f'✅ 账号 [{alias}] 标记为 healthy（success_count={entry["success_count"]}）')
    if was_failed:
        logger.info(f'🔁 账号 [{alias}] 从 failed 恢复为 healthy')
        try:
            from feishu_alert import send_account_recovered
            send_account_recovered(alias)
        except Exception as e:
            logger.debug(f'恢复通知发送失败（忽略）: {e}')


def mark_failure(alias: str, detail: str = ''):
    """标记账号登录失败"""
    if not alias:
        return
    state = _load_state()
    entry = _ensure_account_entry(state, alias)
    now_str = _now_str()
    entry['status'] = 'failed'
    entry['last_fail'] = now_str
    entry['last_fail_detail'] = (detail or '')[:200]
    entry['last_used'] = now_str
    entry['fail_count'] = int(entry.get('fail_count', 0) or 0) + 1
    _save_state(state)
    logger.warning(f'❌ 账号 [{alias}] 标记为 failed（fail_count={entry["fail_count"]}）: {detail[:100]}')


def get_failed_accounts() -> List[dict]:
    """返回当前所有 failed 状态的账号（供告警使用）"""
    state = _load_state()
    cfg = load_config()
    enabled = {a['alias'] for a in cfg['accounts']}
    result = []
    for alias, entry in state.get('accounts', {}).items():
        if alias in enabled and entry.get('status') == 'failed':
            result.append({
                'alias': alias,
                'last_fail': entry.get('last_fail', ''),
                'detail': entry.get('last_fail_detail', ''),
                'fail_count': entry.get('fail_count', 0),
            })
    return result


def all_failed() -> bool:
    """判断所有已启用账号是否都处于 failed 状态"""
    cfg = load_config()
    state = _load_state()
    for acc in cfg['accounts']:
        entry = state['accounts'].get(acc['alias'])
        if not entry or entry.get('status') != 'failed':
            return False
    return len(cfg['accounts']) > 0


def should_send_all_failed_alert() -> bool:
    """节流判断：是否应发送"全部失效"告警"""
    cfg = load_config()
    throttle_sec = cfg['settings']['alert_throttle_min'] * 60
    state = _load_state()
    last_ts = int(state.get('last_alert_ts', 0) or 0)
    now_ts = int(datetime.now().timestamp())
    return (now_ts - last_ts) >= throttle_sec


def mark_alert_sent():
    state = _load_state()
    state['last_alert_ts'] = int(datetime.now().timestamp())
    state['last_alert_at'] = _now_str()
    _save_state(state)


def get_summary() -> dict:
    """获取面向 UI / Electron 的账号池摘要"""
    cfg = load_config()
    state = _load_state()
    accounts_view = []
    for acc in cfg['accounts']:
        alias = acc['alias']
        entry = state['accounts'].get(alias, {})
        accounts_view.append({
            'alias': alias,
            'profile_dir': acc['profile_dir'],
            'status': entry.get('status', 'healthy'),
            'last_ok': entry.get('last_ok', ''),
            'last_fail': entry.get('last_fail', ''),
            'last_fail_detail': entry.get('last_fail_detail', ''),
            'last_used': entry.get('last_used', ''),
            'fail_count': entry.get('fail_count', 0),
            'success_count': entry.get('success_count', 0),
        })
    return {
        'enabled': len(cfg['accounts']) >= 2,
        'current_account': state.get('current_account', ''),
        'last_alert_at': state.get('last_alert_at', ''),
        'all_failed': all_failed(),
        'accounts': accounts_view,
    }


def reset_account(alias: str):
    """将账号状态强制重置为 healthy（一键登录后调用）"""
    state = _load_state()
    entry = _ensure_account_entry(state, alias)
    entry['status'] = 'healthy'
    entry['fail_count'] = 0
    entry['last_fail_detail'] = ''
    _save_state(state)
    logger.info(f'🔄 账号 [{alias}] 状态已重置为 healthy')


# ============ CLI ============

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description='BOSS 账号池管理')
    sub = parser.add_subparsers(dest='cmd')

    sub.add_parser('list', help='打印账号池摘要')
    sub.add_parser('pick', help='选一个账号（调试）')

    p_mark = sub.add_parser('mark', help='标记账号状态')
    p_mark.add_argument('alias')
    p_mark.add_argument('status', choices=['ok', 'fail'])
    p_mark.add_argument('--detail', default='')

    p_reset = sub.add_parser('reset', help='重置账号为 healthy')
    p_reset.add_argument('alias')

    args = parser.parse_args()

    if args.cmd == 'list':
        summary = get_summary()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == 'pick':
        acc = pick_next_account()
        if acc:
            print(json.dumps(acc, ensure_ascii=False, indent=2))
            return 0
        print('无可用账号')
        return 1

    if args.cmd == 'mark':
        if args.status == 'ok':
            mark_success(args.alias)
        else:
            mark_failure(args.alias, args.detail)
        return 0

    if args.cmd == 'reset':
        reset_account(args.alias)
        return 0

    parser.print_help()
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(_cli())
