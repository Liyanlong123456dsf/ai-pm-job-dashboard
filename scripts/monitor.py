#!/usr/bin/env python3
"""轻量持续监控脚本 - 每 60 秒刷新一次关键指标"""
import json, time, os, sys
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent.parent
STATUS_FILE = BASE / 'run_status.json'
RECORD_FILE = BASE / 'logs' / 'auto_daily_record.json'
JOBS_FILE = BASE / 'jobs_data.json'
INTERVAL = 60  # 秒

def _load(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except:
        return {}

def _py_alive():
    """检查 python 爬虫进程是否存活"""
    import subprocess
    # Windows 下避免 wmic 每次弹 CMD 黑窗
    kwargs = {}
    if sys.platform == 'win32':
        kwargs['creationflags'] = 0x08000000  # CREATE_NO_WINDOW
    try:
        r = subprocess.run(['wmic', 'process', 'where', "name='python.exe'", 'get', 'ProcessId,CommandLine'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace',
                           **kwargs)
        for line in r.stdout.splitlines():
            line = line.strip()
            if 'daily_update' in line or 'auto_daily' in line or 'boss_dp' in line:
                pid = line.split()[0] if line.split() else '?'
                return True, pid
        return False, '-'
    except:
        return False, '?'

def _jobs_stats():
    d = _load(JOBS_FILE)
    jobs = d.get('jobs', [])
    total = len(jobs)
    has_desc = sum(1 for j in jobs if j.get('desc') and len(j['desc'].strip()) > 20)
    has_url = sum(1 for j in jobs if j.get('url'))
    return total, has_url, has_desc

def _tail_log(path, n=3):
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
        return lines[-n:] if len(lines) >= n else lines
    except:
        return []

def _safe_print(text):
    """安全输出: 替换 GBK 不支持的字符"""
    try:
        print(text)
    except UnicodeEncodeError:
        safe = text.encode('gbk', errors='replace').decode('gbk')
        print(safe)

def main():
    _safe_print('[MONITOR] AI PM 爬虫监控启动 (Ctrl+C 退出)\n')
    last_total = None
    while True:
        now = datetime.now().strftime('%H:%M:%S')
        alive, pid = _py_alive()
        status = _load(STATUS_FILE)
        record = _load(RECORD_FILE)
        total, has_url, has_desc = _jobs_stats()

        # 状态标记
        if status.get('overall') == 'running':
            tag = '[RUNNING]'
        elif status.get('overall') == 'success':
            tag = '[OK]'
        elif status.get('overall') == 'failed':
            tag = '[FAIL]'
        else:
            tag = '[?]'

        # 新增速度
        delta = ''
        if last_total is not None and last_total != total:
            delta = f' (+{total - last_total})'
        last_total = total

        # 最近完成的关键词
        steps = status.get('steps', [])
        kw_steps = [s for s in steps if '爬取' in s.get('name', '')]
        last_kw = kw_steps[-1] if kw_steps else None

        # 最近一轮记录
        last_round = record[-1] if record else {}

        _safe_print(f'[{now}] {tag}  process={"alive(PID:"+str(pid)+")" if alive else "not found"}{delta}')
        _safe_print(f'  DB: {total} jobs | url={has_url} | desc={has_desc} | missing={total-has_desc}')
        if status.get('overall') == 'running':
            _safe_print(f'  crawl_raw={status.get("crawl_raw",0)} | cleaned={status.get("crawl_cleaned",0)} | added={status.get("added",0)} | total={status.get("total",0)}')
            if last_kw:
                _safe_print(f'  last_kw: {last_kw["name"]} => {last_kw.get("detail","")}')
            errors = status.get('errors', [])
            if errors:
                _safe_print(f'  [!] error: {errors[-1][:100]}')
        elif last_round:
            _safe_print(f'  last_round: {last_round.get("executed_at","")} | ok={last_round.get("success")} | dur={last_round.get("duration_sec",0)}s')
            if last_round.get('error'):
                _safe_print(f'  [!] error: {last_round["error"][:120]}')

        # 最新日志
        log_file = BASE / 'logs' / 'crawler.log'
        tail = _tail_log(log_file, 2)
        if tail:
            for line in tail:
                short = line.strip()[-80:] if len(line.strip()) > 80 else line.strip()
                _safe_print(f'  LOG: {short}')

        _safe_print('')
        try:
            time.sleep(INTERVAL)
        except KeyboardInterrupt:
            _safe_print('\n[STOP] monitor stopped')
            break

if __name__ == '__main__':
    main()
