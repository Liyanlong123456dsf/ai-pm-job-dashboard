#!/usr/bin/env python3
import sys, io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import argparse
import json
import logging
import os
import queue
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
LOG_DIR = BASE_DIR / 'logs'
PARALLEL_DIR = LOG_DIR / 'parallel_crawl'
PROGRESS_FILE = LOG_DIR / 'progress.json'
RUN_STATUS_FILE = BASE_DIR / 'run_status.json'
CONFIG_FILE = BASE_DIR / 'config' / 'keywords.json'
PARALLEL_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(SCRIPT_DIR))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [parallel] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'parallel_crawl.log', encoding='utf-8'),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger('parallel_crawl')

HANGZHOU = '杭州'
SALARY_SPECS = [
    {'code': '405', 'label': '15-20K'},
    {'code': '406', 'label': '20-30K'},
    {'code': '407', 'label': '30-50K'},
    {'code': '408', 'label': '50K+'},
]
FOCUS_MARKERS = (
    'AIGC', '生成式', '电商', '营销', '内容中台', '内容平台', '内容生成', '内容管理',
    '创作平台', '创作工具', '文案', '图文', '内容分发', '内容推荐', '素材中台', '商业化'
)


def read_json(path, default=None):
    try:
        path = Path(path)
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        pass
    return default if default is not None else {}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def save_status(status):
    status['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    write_json(RUN_STATUS_FILE, status)


def step(status, name, ok=True, detail=''):
    status['steps'].append({
        'name': name,
        'ok': ok,
        'detail': detail,
        'time': datetime.now().strftime('%H:%M:%S'),
    })
    save_status(status)


def progress(pct, phase, detail, status, done=False):
    write_json(PROGRESS_FILE, {
        'pct': min(100, max(0, int(pct))),
        'phase': phase,
        'detail': detail,
        'steps': status.get('steps', []),
        'done': done,
        'task_type': 'parallel_crawl',
        'ts': datetime.now().strftime('%H:%M:%S'),
    })


def merge_terms(*groups):
    out, seen = [], set()
    for group in groups:
        for raw in group or []:
            term = str(raw or '').strip()
            if term and term not in seen:
                seen.add(term)
                out.append(term)
    return out


def is_focus(term, focus_set=None):
    term = str(term or '').strip()
    if focus_set is not None:
        return term in focus_set
    upper = term.upper()
    return any(marker.upper() in upper for marker in FOCUS_MARKERS)


def load_settings():
    cfg = read_json(CONFIG_FILE, {})
    schedule = cfg.get('schedule') or {}
    settings = schedule.get('parallel') or {}
    return {
        'workers': 2,
        'ports': settings.get('ports') or [9222, 9223],
    }


def select_accounts(ports):
    import account_pool
    if len(ports) < 2 or int(ports[0]) == int(ports[1]):
        raise RuntimeError('并行端口配置无效：需要两个不同端口')
    cfg = account_pool.load_config()
    summary = account_pool.get_summary()
    state_by_alias = {a['alias']: a for a in summary.get('accounts', [])}
    enabled = [a for a in cfg.get('accounts', []) if a.get('enabled', True) and a.get('alias')]
    healthy = [
        a for a in enabled
        if state_by_alias.get(a['alias'], {}).get('status', 'healthy') == 'healthy'
    ]
    if len(healthy) < 2:
        raise RuntimeError(f'并行模式需要至少2个 healthy 账号，当前{len(healthy)}/{len(enabled)}')
    healthy.sort(key=lambda a: state_by_alias.get(a['alias'], {}).get('last_used', '') or '')
    first, second = healthy[0], healthy[1]
    return [
        {'alias': first['alias'], 'port': int(ports[0])},
        {'alias': second['alias'], 'port': int(ports[1])},
    ]


def build_tasks(quick=False):
    from spiders.boss_dp import get_focus_keywords, load_config, load_keywords
    config = load_config()
    cities = config.get('cities') or {}
    keywords = load_keywords(quick=quick)
    focus_set = set(merge_terms(get_focus_keywords(config)))
    focus_keywords = [kw for kw in keywords if is_focus(kw, focus_set)]
    keywords = merge_terms(focus_keywords, [kw for kw in keywords if kw not in set(focus_keywords)])
    hangzhou_code = cities.get(HANGZHOU)
    if not hangzhou_code:
        raise RuntimeError('配置中未找到杭州城市码')
    stages = [('杭州随机关键词17K以上', keywords, {HANGZHOU: hangzhou_code})]
    if focus_keywords:
        stages.append(('杭州重点方向17K以上第2轮', focus_keywords, {HANGZHOU: hangzhou_code}))
        stages.append(('杭州重点方向17K以上第3轮', focus_keywords, {HANGZHOU: hangzhou_code}))
    other_cities = {k: v for k, v in cities.items() if k != HANGZHOU}
    if other_cities:
        stages.append(('其他城市爬取17K以上一次', keywords, other_cities))

    tasks = []
    for stage_name, stage_keywords, stage_cities in stages:
        for spec in SALARY_SPECS:
            for keyword in stage_keywords:
                for city_name, city_code in stage_cities.items():
                    tasks.append({
                        'stage': stage_name,
                        'keyword': keyword,
                        'city_name': city_name,
                        'city_code': city_code,
                        'salary_code': spec['code'],
                        'salary_label': spec['label'],
                        'min_avg': 17,
                        'max_avg': None,
                        'greedy': not quick,
                        'focus': keyword in set(focus_keywords),
                    })
    return tasks, keywords, focus_keywords, cities


def split_balanced(tasks):
    ordered = sorted(tasks, key=lambda t: (
        0 if t.get('city_name') == HANGZHOU else 1,
        0 if t.get('focus') else 1,
        t.get('stage', ''),
        t.get('salary_code', ''),
        t.get('keyword', ''),
        t.get('city_name', ''),
    ))
    return [ordered[0::2], ordered[1::2]]


def spawn_worker(worker_id, account, port, tasks_file, output_file, state_file):
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / 'crawl_worker.py'),
        '--worker-id', worker_id,
        '--account', account,
        '--chrome-port', str(port),
        '--tasks-file', str(tasks_file),
        '--output-file', str(output_file),
        '--state-file', str(state_file),
    ]
    env = os.environ.copy()
    env.setdefault('AI_PM_UNATTENDED', '1')
    env.setdefault('AI_PM_SHOW_PROGRESS_GUI', '0')
    env.setdefault('AI_PM_OPEN_REPORT', '0')
    return subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        bufsize=1,
        env=env,
    )


def reader_thread(proc, worker_id, output_queue):
    try:
        for line in iter(proc.stdout.readline, ''):
            output_queue.put((worker_id, line.rstrip()))
    except Exception as e:
        output_queue.put((worker_id, f'[reader-error] {e}'))
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass


def aggregate_progress(workers, status, total_tasks):
    done = 0
    raw = 0
    cleaned = 0
    details = []
    for worker in workers:
        state = read_json(worker['state'], {
            'worker_id': worker['id'],
            'phase': 'starting',
            'completed': 0,
            'total': worker['tasks'],
            'raw': 0,
            'cleaned': 0,
        })
        done += int(state.get('completed', 0) or 0)
        raw += int(state.get('raw', 0) or 0)
        cleaned += int(state.get('cleaned', 0) or 0)
        details.append(f"{state.get('worker_id', worker['id'])}:{state.get('phase', '')} {state.get('completed', 0)}/{state.get('total', worker['tasks'])}")
    status['crawl_raw'] = raw
    status['crawl_cleaned'] = cleaned
    save_status(status)
    progress(5 + int(70 * done / max(total_tasks, 1)), '🔀 双浏览器并行爬取', ' | '.join(details), status)


def run_workers(shards, accounts, status):
    workers = []
    total_tasks = sum(len(s) for s in shards)
    for idx, shard in enumerate(shards):
        worker_id = chr(ord('A') + idx)
        tasks_file = PARALLEL_DIR / f'tasks_{worker_id}.json'
        output_file = PARALLEL_DIR / f'result_{worker_id}.json'
        state_file = PARALLEL_DIR / f'state_{worker_id}.json'
        for path in [output_file, state_file]:
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass
        write_json(tasks_file, {'worker_id': worker_id, 'account': accounts[idx]['alias'], 'tasks': shard})
        proc = spawn_worker(worker_id, accounts[idx]['alias'], accounts[idx]['port'], tasks_file, output_file, state_file)
        workers.append({'id': worker_id, 'proc': proc, 'output': output_file, 'state': state_file, 'tasks': len(shard)})
        step(status, f'启动 Worker {worker_id}', True, f"账号 {accounts[idx]['alias']} · 端口 {accounts[idx]['port']} · 任务 {len(shard)}")

    output_queue = queue.Queue()
    threads = []
    for worker in workers:
        th = threading.Thread(target=reader_thread, args=(worker['proc'], worker['id'], output_queue), daemon=True)
        th.start()
        threads.append(th)

    last_progress = 0
    try:
        while True:
            while True:
                try:
                    wid, line = output_queue.get_nowait()
                except queue.Empty:
                    break
                if line:
                    logger.info(f'[{wid}] {line}')
            if time.time() - last_progress >= 5:
                aggregate_progress(workers, status, total_tasks)
                last_progress = time.time()
            if all(worker['proc'].poll() is not None for worker in workers):
                break
            time.sleep(1)
    except KeyboardInterrupt:
        logger.warning('收到中断信号，正在停止并行 worker...')
        for worker in workers:
            if worker['proc'].poll() is None:
                worker['proc'].terminate()
        time.sleep(3)
        for worker in workers:
            if worker['proc'].poll() is None:
                worker['proc'].kill()
        raise
    except Exception:
        for worker in workers:
            if worker['proc'].poll() is None:
                worker['proc'].terminate()
        raise

    for th in threads:
        th.join(timeout=2)

    results = []
    failed = []
    for worker in workers:
        result = read_json(worker['output'], {})
        if worker['proc'].returncode != 0 or not result.get('ok'):
            failed.append({'worker': worker['id'], 'returncode': worker['proc'].returncode, 'errors': result.get('errors', [])})
        if result:
            results.append(result)
    return results, failed


def merge_results(results, status):
    from merger import load_existing, merge, save, save_snapshot
    all_jobs = []
    total_raw = 0
    total_cleaned = 0
    for result in results:
        all_jobs.extend(result.get('jobs') or [])
        total_raw += int(result.get('raw', 0) or 0)
        total_cleaned += int(result.get('cleaned', 0) or 0)
        status['errors'].extend(result.get('errors') or [])

    existing_keys, existing_jobs = load_existing()
    old_total = len(existing_jobs)
    merged, added = merge(existing_jobs, existing_keys, all_jobs)
    save(merged, clean=True)
    if all_jobs:
        save_snapshot(all_jobs)
    _, final_jobs = load_existing()
    status['crawl_raw'] = total_raw
    status['crawl_cleaned'] = total_cleaned
    status['added'] = added
    status['total'] = len(final_jobs)
    step(status, '并行结果合并', True, f'原{old_total}+清{len(all_jobs)}→新增{added}=总{len(final_jobs)}')
    return added, len(final_jobs), total_raw


def run_postprocess(status, total_added):
    jobs = [
        (78, '导出总表', 'export_total.py', 900),
        (82, '生成知识库', 'gen_knowledge.py', 900),
        (85, '飞书同步', 'sync_feishu.py', 600),
    ]
    for pct, name, script, timeout in jobs:
        progress(pct, name, '', status)
        try:
            subprocess.run([sys.executable, str(SCRIPT_DIR / script)], cwd=str(BASE_DIR), check=True, timeout=timeout)
            step(status, name, True)
        except Exception as e:
            status['errors'].append(f'{name}失败: {e}')
            step(status, name, False, str(e)[:200])

    progress(87, 'Git 推送中', '', status)
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        branch_ret = subprocess.run(
            ['git', 'branch', '--show-current'],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=30,
        )
        branch = (branch_ret.stdout or '').strip() or 'main'
        status['git_branch'] = branch
        status['main_published'] = branch == 'main'
        publish_paths = [
            'jobs_data.json',
            'AIPM总表_统一格式.csv',
            'knowledge_base.md',
            'coze_prompt.txt',
            'RAG_GUIDE.md',
            'config/keywords.json',
            'scripts/auto_daily.py',
            'scripts/crawl_worker.py',
            'scripts/parallel_crawl.py',
            'app/index.html',
            'app/js/renderer.js',
            'electron/main.js',
        ]
        subprocess.run(['git', 'add', *publish_paths], cwd=str(BASE_DIR), check=True, timeout=120)
        diff_ret = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=str(BASE_DIR), timeout=60)
        if diff_ret.returncode == 0:
            status['git_pushed'] = True
            step(status, 'Git 推送', True, '无文件变更，跳过提交')
        else:
            subprocess.run(
                ['git', 'commit', '-m', f'daily: {today} 并行新增{total_added}条 总{status.get("total", 0)}条'],
                cwd=str(BASE_DIR),
                check=True,
                timeout=120,
            )
            subprocess.run(['git', 'push', 'origin', f'HEAD:{branch}'], cwd=str(BASE_DIR), check=True, timeout=180)
            status['git_pushed'] = True
            step(status, 'Git 推送', True, f'已推送到 {branch}')
    except Exception as e:
        status['errors'].append(f'Git 推送失败: {e}')
        step(status, 'Git 推送', False, str(e)[:200])

    if status.get('git_pushed') and status.get('main_published', True):
        status['deployed'] = True
        step(status, '云同步', True, '数据已通过 GitHub Raw URL 自动更新')
    else:
        step(status, '云同步', False, 'Git 推送未成功或非 main 分支')

    try:
        final = read_json(BASE_DIR / 'jobs_data.json', {})
        final_jobs = final.get('jobs', []) if isinstance(final, dict) else []
        if total_added > 0 and status.get('git_pushed') and status.get('main_published', True):
            from feishu_alert import send_daily_report_alert
            status_for_alert = dict(status)
            status_for_alert['added'] = total_added
            status_for_alert['total'] = len(final_jobs)
            send_daily_report_alert(status=status_for_alert, min_new=1, top_n=5, throttle_sec=0)
        elif total_added > 0 and not status.get('main_published', True):
            logger.warning('当前为临时分支，跳过飞书岗位日报推送，避免网页 main 数据不一致')
        elif total_added > 0:
            logger.warning('Git 推送未成功，跳过飞书岗位日报推送，避免网页数据不一致')
    except Exception as e:
        logger.warning(f'飞书岗位日报推送失败(非致命): {e}')


def new_status(mode):
    return {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'start_time': datetime.now().strftime('%H:%M:%S'),
        'mode': mode,
        'steps': [],
        'overall': 'running',
        'crawl_raw': 0,
        'crawl_cleaned': 0,
        'added': 0,
        'total': 0,
        'git_pushed': False,
        'deployed': False,
        'errors': [],
        'duration_sec': 0,
    }


def main():
    global RUN_STATUS_FILE, PROGRESS_FILE
    parser = argparse.ArgumentParser(description='双浏览器均衡分片并行爬取')
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.dry_run:
        RUN_STATUS_FILE = PARALLEL_DIR / 'dry_run_status.json'
        PROGRESS_FILE = PARALLEL_DIR / 'dry_run_progress.json'

    started = time.time()
    status = new_status('parallel_quick' if args.quick else 'parallel_full')
    save_status(status)
    progress(1, '双浏览器并行启动中', '', status)
    try:
        settings = load_settings()
        tasks, keywords, focus_keywords, cities = build_tasks(quick=args.quick)
        accounts = select_accounts(settings.get('ports') or [9222, 9223])
        shards = split_balanced(tasks)
        step(status, '并行任务生成', True, f'{len(tasks)} 任务 · {len(keywords)} 关键词 · {len(focus_keywords)} 重点 · {len(cities)} 城市')

        if args.dry_run:
            write_json(PARALLEL_DIR / 'dry_run_plan.json', {
                'accounts': accounts,
                'shards': [{'count': len(shard), 'sample': shard[:10]} for shard in shards],
            })
            status['overall'] = 'success'
            status['duration_sec'] = round(time.time() - started)
            step(status, 'Dry Run', True, '已生成计划，不启动浏览器')
            progress(100, '双浏览器并行 Dry Run 完成', '计划已生成', status, done=True)
            return True

        results, failed = run_workers(shards, accounts, status)
        if failed:
            status['errors'].append(f'Worker 失败: {failed}')
            write_json(PARALLEL_DIR / 'retry_tasks.json', {'failed': failed, 'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        if not results or not any(result.get('jobs') for result in results):
            raise RuntimeError('worker 未产出可合并数据')

        total_added, total, total_raw = merge_results(results, status)
        if total_raw == 0:
            raise RuntimeError('原始数据为 0')
        run_postprocess(status, total_added)
        status['duration_sec'] = round(time.time() - started)
        status['overall'] = 'success' if not status['errors'] else 'partial'
        step(status, '全流程完成', True, f'总 {total} 条，新增 {total_added} 条')
        progress(100, '双浏览器并行完成', f'新增 {total_added} 条，总计 {total} 条', status, done=True)
        return not status['errors']
    except Exception as e:
        logger.error(f'并行爬取失败: {e}', exc_info=True)
        status['errors'].append(str(e))
        status['duration_sec'] = round(time.time() - started)
        status['overall'] = 'failed'
        step(status, '并行爬取失败', False, str(e)[:200])
        progress(30, '双浏览器并行失败', str(e)[:200], status, done=True)
        return False
    finally:
        save_status(status)


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
