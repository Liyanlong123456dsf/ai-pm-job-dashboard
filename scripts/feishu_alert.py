#!/usr/bin/env python3
"""
飞书自定义机器人 webhook 告警模块

用途：
  - BOSS 爬取账号池全部失效时，向用户手机推送飞书卡片通知
  - 支持签名校验（可选）
  - 节流：同一类型告警 60 分钟内最多发 1 次

配置：
  在 .env 或系统环境变量中设置：
    FEISHU_ALERT_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/<token>
    FEISHU_ALERT_SECRET=<可选，机器人签名校验密钥>
"""
import os
import sys
import time
import json
import base64
import hmac
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # 调用端需自行处理

SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# 节流状态文件
ALERT_STATE_FILE = LOG_DIR / 'feishu_alert_state.json'

logger = logging.getLogger('feishu_alert')
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [feishu_alert] %(levelname)s: %(message)s',
    )

# 默认节流间隔（秒）
DEFAULT_THROTTLE_SEC = 3600


def _load_env_file():
    """尽量加载 BASE_DIR/.env，如果存在"""
    env_file = BASE_DIR / '.env'
    if not env_file.exists():
        return
    try:
        for raw in env_file.read_text(encoding='utf-8').splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception as e:
        logger.warning(f'加载 .env 失败: {e}')


_load_env_file()


def get_webhook() -> str:
    return os.environ.get('FEISHU_ALERT_WEBHOOK', '').strip()


def get_secret() -> str:
    return os.environ.get('FEISHU_ALERT_SECRET', '').strip()


def _gen_sign(secret: str, timestamp: int) -> str:
    """生成飞书自定义机器人签名"""
    string_to_sign = f'{timestamp}\n{secret}'
    hmac_code = hmac.new(
        string_to_sign.encode('utf-8'),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(hmac_code).decode('utf-8')


def _load_alert_state() -> dict:
    try:
        if ALERT_STATE_FILE.exists():
            return json.loads(ALERT_STATE_FILE.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


def _save_alert_state(state: dict):
    try:
        ALERT_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8'
        )
    except Exception as e:
        logger.warning(f'写入告警状态失败: {e}')


def _should_send(alert_key: str, throttle_sec: int) -> bool:
    """节流判断：同一 key 在 throttle_sec 秒内只发一次"""
    state = _load_alert_state()
    last_ts = state.get(alert_key, {}).get('last_sent_ts', 0)
    now_ts = int(time.time())
    if now_ts - int(last_ts or 0) < max(0, int(throttle_sec)):
        return False
    return True


def _mark_sent(alert_key: str):
    state = _load_alert_state()
    entry = state.get(alert_key, {}) or {}
    entry['last_sent_ts'] = int(time.time())
    entry['last_sent_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    entry['total_sent'] = int(entry.get('total_sent', 0) or 0) + 1
    state[alert_key] = entry
    _save_alert_state(state)


def _post_webhook(payload: dict, timeout: int = 10) -> tuple:
    """发送原始 payload 到飞书 webhook。返回 (ok, detail)"""
    if requests is None:
        return False, 'requests 模块未安装'
    webhook = get_webhook()
    if not webhook:
        return False, 'FEISHU_ALERT_WEBHOOK 未配置'

    secret = get_secret()
    body = dict(payload)
    if secret:
        ts = int(time.time())
        body['timestamp'] = str(ts)
        body['sign'] = _gen_sign(secret, ts)

    try:
        resp = requests.post(webhook, json=body, timeout=timeout)
        if resp.status_code != 200:
            return False, f'HTTP {resp.status_code}: {resp.text[:200]}'
        data = resp.json() if resp.content else {}
        code = data.get('code', data.get('StatusCode', 0))
        if code and code != 0:
            return False, f'飞书错误 code={code}: {data.get("msg", "")[:200]}'
        return True, 'ok'
    except Exception as e:
        return False, f'请求异常: {e}'


# ============ 高层 API ============

def send_text(content: str, alert_key: str = 'generic', throttle_sec: int = 0) -> bool:
    """发送纯文本消息（开发/调试用）"""
    if throttle_sec and not _should_send(alert_key, throttle_sec):
        logger.info(f'[节流] {alert_key}: 跳过发送')
        return False
    ok, detail = _post_webhook({
        'msg_type': 'text',
        'content': {'text': content[:2000]},
    })
    if ok:
        _mark_sent(alert_key)
        logger.info(f'✅ 飞书文本通知已发送: {alert_key}')
    else:
        logger.warning(f'❌ 飞书文本通知失败 [{alert_key}]: {detail}')
    return ok


def send_account_pool_alert(failed_accounts: list, throttle_sec: int = DEFAULT_THROTTLE_SEC) -> bool:
    """
    BOSS 账号池全部失效时发送卡片告警
    failed_accounts: [{'alias': '主账号', 'last_fail': '2026-04-22 ...', 'detail': '...'}, ...]
    """
    alert_key = 'boss_pool_all_failed'
    if not _should_send(alert_key, throttle_sec):
        logger.info(f'[节流] {alert_key}: {throttle_sec}s 内已发送过，跳过')
        return False

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = [f'**检测时间**: {now_str}', '', '**失效账号**:']
    for acc in (failed_accounts or []):
        alias = acc.get('alias', '?')
        last_fail = acc.get('last_fail', '?')
        detail = (acc.get('detail') or '')[:80]
        lines.append(f'- `{alias}` | 失效于 {last_fail} | {detail}')

    lines.append('')
    lines.append('**操作指引**:')
    lines.append('1. 打开 AI PM 控制台（桌面 Electron 快捷方式）')
    lines.append('2. 进入「账号池」面板')
    lines.append('3. 点击对应账号的「扫码登录」按钮')
    lines.append('4. Chrome 会打开 BOSS 直聘，扫码完成即可')
    lines.append('')
    lines.append('登录成功后自动恢复爬取，无需重启程序。')

    card = {
        'msg_type': 'interactive',
        'card': {
            'config': {'wide_screen_mode': True, 'enable_forward': True},
            'header': {
                'title': {'tag': 'plain_text', 'content': '⚠️ BOSS 爬取需要登录'},
                'template': 'red',
            },
            'elements': [
                {
                    'tag': 'div',
                    'text': {'tag': 'lark_md', 'content': '\n'.join(lines)},
                },
                {
                    'tag': 'action',
                    'actions': [
                        {
                            'tag': 'button',
                            'text': {'tag': 'plain_text', 'content': '打开 BOSS 直聘'},
                            'type': 'primary',
                            'url': 'https://www.zhipin.com/web/geek/job?query=AI产品经理',
                        }
                    ],
                },
            ],
        },
    }
    ok, detail = _post_webhook(card)
    if ok:
        _mark_sent(alert_key)
        logger.info(f'✅ 账号池失效告警已发送（{len(failed_accounts or [])} 个失效账号）')
    else:
        logger.warning(f'❌ 账号池失效告警发送失败: {detail}')
    return ok


def _format_salary_summary(jobs: list) -> dict:
    """从 jobs 列表中提取统计：城市 TOP3、档位分布、平均薪资"""
    from collections import Counter
    city_ctr = Counter()
    tier_ctr = Counter()
    avgs = []
    for j in jobs:
        city = (j.get('city') or '').split('·')[0].split(' ')[0].rstrip('市').rstrip('省').strip()
        if city:
            city_ctr[city] += 1
        tier = (j.get('tier') or '').strip()
        if tier:
            tier_ctr[tier] += 1
        if j.get('avg'):
            try:
                avgs.append(float(j['avg']))
            except Exception:
                pass
    avg_sal = round(sum(avgs) / len(avgs), 1) if avgs else 0
    top_cities = city_ctr.most_common(3)
    return {
        'avg_salary': avg_sal,
        'top_cities': top_cities,
        'tier_dist': dict(tier_ctr),
    }


def _get_feishu_doc_url() -> str:
    """从 logs/feishu_doc.json 读取文档 URL，不存在返回空"""
    doc_state_file = LOG_DIR / 'feishu_doc.json'
    if not doc_state_file.exists():
        return ''
    try:
        state = json.loads(doc_state_file.read_text(encoding='utf-8'))
        doc_id = state.get('document_id', '')
        if doc_id:
            return f'https://bytedance.feishu.cn/docx/{doc_id}'
    except Exception:
        pass
    return ''


def send_daily_report_alert(status: Optional[dict] = None,
                            min_new: int = 1,
                            top_n: int = 5,
                            throttle_sec: int = 0) -> bool:
    """
    岗位日报卡片：每次飞书文档同步成功后调用，把本轮新增的 Top N 岗位推到手机飞书。

    参数：
      status: 可选，daily_update 传入的 run_status.json 对象；未传则从磁盘读取
      min_new: 新增岗位数下限，低于此阈值直接跳过不推送（默认 1）
      top_n: 卡片中展示的岗位条数上限（默认 5）
      throttle_sec: 节流间隔秒数，默认 0 不节流（由上游靠"新增>0"控制频率）
    """
    alert_key = 'daily_report'
    if throttle_sec and not _should_send(alert_key, throttle_sec):
        logger.info(f'[节流] {alert_key}: {throttle_sec}s 内已发送过，跳过')
        return False

    # 读 run_status.json（如未传入）
    if status is None:
        status_file = BASE_DIR / 'run_status.json'
        if status_file.exists():
            try:
                status = json.loads(status_file.read_text(encoding='utf-8'))
            except Exception:
                status = {}
        else:
            status = {}

    added = int(status.get('added', 0) or 0)
    if added < max(1, int(min_new)):
        logger.info(f'[日报] 本轮新增 {added} 条 < 阈值 {min_new}，不推送')
        return False

    # 读 jobs_data.json
    jobs_file = BASE_DIR / 'jobs_data.json'
    if not jobs_file.exists():
        logger.warning(f'[日报] jobs_data.json 不存在，跳过')
        return False
    try:
        data = json.loads(jobs_file.read_text(encoding='utf-8'))
    except Exception as e:
        logger.warning(f'[日报] 读取 jobs_data.json 失败: {e}')
        return False
    all_jobs = data.get('jobs', []) if isinstance(data, dict) else data
    meta = data.get('meta', {}) if isinstance(data, dict) else {}

    # 筛选本轮新增：优先用 is_new 标记
    new_jobs = [j for j in all_jobs if j.get('is_new')]

    # 健壮性：若 is_new 数量远大于本轮真实新增（老版 merger.py 有污染 bug），
    # 信任 status['added']，改用 _crawled_at 降序取 Top N
    contamination_threshold = max(added * 5, 50)
    if len(new_jobs) > contamination_threshold:
        logger.info(
            f'[日报] is_new 标记数({len(new_jobs)}) 远大于本轮新增({added})，'
            f'使用 _crawled_at 降序兜底'
        )
        new_jobs = sorted(
            [j for j in all_jobs if j.get('_crawled_at')],
            key=lambda x: x.get('_crawled_at', ''),
            reverse=True,
        )[:max(top_n * 2, 20)]  # 取稍多一些供薪资排序

    if not new_jobs:
        # 终极兜底：按 _crawled_at 或原顺序取 top_n
        new_jobs = sorted(
            [j for j in all_jobs if j.get('_crawled_at')],
            key=lambda x: x.get('_crawled_at', ''),
            reverse=True,
        )[:top_n] or all_jobs[:top_n]

    if not new_jobs:
        logger.info('[日报] 没有可展示的新岗位，跳过')
        return False

    # 按薪资降序，取 TopN
    new_jobs_sorted = sorted(new_jobs, key=lambda x: -(x.get('avg') or 0))[:max(1, int(top_n))]

    # 统计
    stats = _format_salary_summary(new_jobs)
    all_stats = _format_salary_summary(all_jobs)

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    # ------- 头部统计 -------
    duration_sec = int(status.get('duration_sec') or 0)
    dur_str = f'{duration_sec // 60}分{duration_sec % 60}秒' if duration_sec else '—'
    total = status.get('total') or meta.get('total') or len(all_jobs)

    header_lines = [
        f'**📅 时间**: {now_str}',
        f'**📊 总岗位**: {total} · **本轮新增**: {added} · **耗时**: {dur_str}',
    ]
    if stats['top_cities']:
        city_str = ' · '.join(f'{c}({n})' for c, n in stats['top_cities'])
        header_lines.append(f'**🏙 新增城市 TOP3**: {city_str}')
    if stats['avg_salary'] > 0:
        header_lines.append(f'**💰 新增岗均薪**: {stats["avg_salary"]}K · **总体均薪**: {all_stats["avg_salary"]}K')

    # ------- Top N 岗位 -------
    job_blocks = []
    for i, j in enumerate(new_jobs_sorted, 1):
        title = (j.get('title') or '').strip()[:60]
        company = (j.get('company') or '').strip()[:30]
        salary = (j.get('salary') or '').strip()[:20]
        city = (j.get('city') or '').split('·')[0].strip()[:10]
        tier = (j.get('tier') or '').strip()
        exp = (j.get('exp') or '').strip()
        cats = (j.get('cats') or [])[:2]
        url = (j.get('url') or '').strip()

        # 第一行：标题（带链接）+ 薪资
        if url and url.startswith('http'):
            line1 = f'**{i}. [{title}]({url})** · `{salary}`'
        else:
            line1 = f'**{i}. {title}** · `{salary}`'

        # 第二行：公司 · 城市 · 经验 · 档位
        meta_parts = [company]
        if city:
            meta_parts.append(city)
        if exp:
            meta_parts.append(exp)
        if tier:
            meta_parts.append(f'`{tier}`')
        line2 = ' · '.join([p for p in meta_parts if p])

        # 第三行：方向标签
        line3 = ''
        if cats:
            line3 = '🏷 ' + '、'.join(cats[:2])

        block_text = line1 + '\n' + line2
        if line3:
            block_text += '\n' + line3
        job_blocks.append(block_text)

    # ------- 组装卡片 -------
    elements = [
        {
            'tag': 'div',
            'text': {'tag': 'lark_md', 'content': '\n'.join(header_lines)},
        },
        {'tag': 'hr'},
        {
            'tag': 'div',
            'text': {'tag': 'lark_md',
                     'content': f'**🔥 本轮新增 TOP{len(new_jobs_sorted)} 高薪岗位**\n\n' + '\n\n'.join(job_blocks)},
        },
    ]

    # ------- 底部操作按钮 -------
    actions = []
    doc_url = _get_feishu_doc_url()
    if doc_url:
        actions.append({
            'tag': 'button',
            'text': {'tag': 'plain_text', 'content': '📄 查看完整飞书文档'},
            'type': 'primary',
            'url': doc_url,
        })
    actions.append({
        'tag': 'button',
        'text': {'tag': 'plain_text', 'content': '🔍 搜 BOSS 直聘'},
        'type': 'default',
        'url': 'https://www.zhipin.com/web/geek/job?query=AI产品经理',
    })
    if actions:
        elements.append({'tag': 'action', 'actions': actions})

    card = {
        'msg_type': 'interactive',
        'card': {
            'config': {'wide_screen_mode': True, 'enable_forward': True},
            'header': {
                'title': {'tag': 'plain_text', 'content': f'📊 AI PM 岗位日报 · 新增 {added} 条'},
                'template': 'green',
            },
            'elements': elements,
        },
    }

    ok, detail = _post_webhook(card)
    if ok:
        _mark_sent(alert_key)
        logger.info(f'✅ 岗位日报已推送（新增 {added} 条，展示 TOP{len(new_jobs_sorted)}）')
    else:
        logger.warning(f'❌ 岗位日报推送失败: {detail}')
    return ok


def send_account_recovered(alias: str) -> bool:
    """账号恢复后的静默通知（不节流，低频）"""
    card = {
        'msg_type': 'interactive',
        'card': {
            'config': {'wide_screen_mode': True},
            'header': {
                'title': {'tag': 'plain_text', 'content': '✅ BOSS 账号已恢复'},
                'template': 'green',
            },
            'elements': [
                {
                    'tag': 'div',
                    'text': {
                        'tag': 'lark_md',
                        'content': f'账号 `{alias}` 已恢复登录状态，爬取将自动继续。\n\n时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                    },
                }
            ],
        },
    }
    ok, detail = _post_webhook(card)
    if ok:
        logger.info(f'✅ 账号恢复通知已发送: {alias}')
    else:
        logger.warning(f'❌ 账号恢复通知失败: {detail}')
    return ok


# ============ CLI 测试入口 ============

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description='飞书 webhook 告警测试')
    parser.add_argument('--test', action='store_true', help='发送测试文本消息')
    parser.add_argument('--test-alert', action='store_true', help='发送测试账号池告警卡片')
    parser.add_argument('--test-report', action='store_true', help='用当前 jobs_data.json 发送岗位日报卡片')
    parser.add_argument('--min-new', type=int, default=0, help='--test-report 使用：新增阈值，0 表示忽略阈值强制推送')
    parser.add_argument('--top-n', type=int, default=5, help='岗位日报展示条数')
    parser.add_argument('--reset-throttle', action='store_true', help='清空节流状态（调试用）')
    args = parser.parse_args()

    if args.reset_throttle:
        if ALERT_STATE_FILE.exists():
            ALERT_STATE_FILE.unlink()
        print('已清空节流状态')
        return 0

    if args.test:
        ok = send_text(
            f'飞书告警测试 @ {datetime.now().strftime("%H:%M:%S")}',
            alert_key='manual_test',
            throttle_sec=0,
        )
        return 0 if ok else 1

    if args.test_alert:
        ok = send_account_pool_alert(
            [
                {'alias': '主账号', 'last_fail': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                 'detail': '未检测到岗位列表'},
                {'alias': '备用', 'last_fail': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                 'detail': '未检测到岗位列表'},
            ],
            throttle_sec=0,
        )
        return 0 if ok else 1

    if args.test_report:
        # --min-new=0 时强制忽略新增阈值（用于测试），内部用 min_new=1 但伪造 added
        if args.min_new == 0:
            # 伪造 status：若真实 run_status 里没有 added，取 jobs 里 is_new 的数量
            jobs_file = BASE_DIR / 'jobs_data.json'
            fake_added = 0
            if jobs_file.exists():
                try:
                    data = json.loads(jobs_file.read_text(encoding='utf-8'))
                    jobs = data.get('jobs', []) if isinstance(data, dict) else data
                    fake_added = sum(1 for j in jobs if j.get('is_new'))
                    if fake_added == 0:
                        # 再退一步：用最新 _crawled_at 的 top_n 条凑数
                        fake_added = min(args.top_n, len(jobs))
                except Exception:
                    pass
            fake_status = {'added': max(fake_added, 1), 'total': 0, 'duration_sec': 0}
            ok = send_daily_report_alert(status=fake_status, min_new=1, top_n=args.top_n, throttle_sec=0)
        else:
            ok = send_daily_report_alert(min_new=args.min_new, top_n=args.top_n, throttle_sec=0)
        return 0 if ok else 1

    parser.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(_cli())
