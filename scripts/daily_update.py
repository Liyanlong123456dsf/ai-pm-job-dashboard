#!/usr/bin/env python3
"""
每日自动更新入口
用法：
  python daily_update.py              # 正常运行（抓取+合并）
  python daily_update.py --dry-run    # 仅测试爬虫，不写入文件
  python daily_update.py --boss-cookie "xxx"  # 指定 BOSS 直聘 Cookie
"""
import sys, io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime
import time as _time
import subprocess
from pipeline import MIN_AVG_SALARY_K

# Setup paths
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

# Logging
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'crawler.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('daily')

HANGZHOU_CITY_NAME = '杭州'
SALARY_SPECS_17_PLUS = [
    {'code': '406', 'label': '20-30K'},
    {'code': '407', 'label': '30-50K'},
    {'code': '408', 'label': '50K+'},
]
OTHER_CITY_SALARY_SPECS = SALARY_SPECS_17_PLUS
FOCUS_KEYWORD_SEEDS = [
    'AIGC产品经理',
    '生成式AI产品经理',
    'AIGC电商产品经理',
    'AIGC视频产品经理',
    'AIGC营销产品经理',
    'AI电商产品经理',
    'AI电商营销产品经理',
    'AI营销产品经理',
    'AI内容营销产品经理',
    'AI视频产品经理',
    'AI短视频产品经理',
    'AI内容产品经理',
    'AI商业化产品经理',
    '直播电商产品经理',
    '内容电商产品经理',
]
FOCUS_KEYWORD_MARKERS = (
    'AIGC', '生成式', '电商', '营销', '视频', '短视频', '直播', '内容', '商业化'
)


def _save_status(status):
    """写入 run_status.json 供 Dashboard 读取"""
    status['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    out = BASE_DIR / 'run_status.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


# ============ 实时进度窗口 ============

_PROGRESS_FILE = LOG_DIR / 'progress.json'
_PROGRESS_HTML = LOG_DIR / 'progress.html'


def _write_progress(pct, phase, detail, steps=None, done=False):
    """写入进度 JSON，供 HTML 页面读取"""
    data = {
        'pct': min(100, max(0, int(pct))),
        'phase': phase,
        'detail': detail,
        'steps': steps or [],
        'done': done,
        'task_type': 'crawl',
        'ts': datetime.now().strftime('%H:%M:%S'),
    }
    with open(_PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def _start_progress_window():
    """初始化进度文件（供 Electron 控制台 / HTTP server 读取）

    旧版会 spawn Tkinter 弹窗，现已移除——所有 UI 统一到 Electron 应用。
    """
    _write_progress(0, '启动中...', '')


def _finish_progress(status):
    """进度窗口切换为完成状态"""
    s = status
    overall = s.get('overall', 'unknown')
    pct = 100 if overall == 'success' else (80 if overall == 'partial' else 30)
    labels = {'success': '✅ 全部成功', 'partial': '⚠️ 部分完成', 'failed': '❌ 执行失败'}
    _write_progress(
        pct, labels.get(overall, overall),
        f'新增 {s.get("added",0)} 条，总计 {s.get("total",0)} 条',
        s.get('steps', []), done=True
    )


def _notify(title, message):
    """发送系统通知（跨平台）"""
    try:
        from platform_utils import notify
        notify(title, message)
    except Exception:
        pass


def _generate_report(status):
    """生成 HTML 报告并在浏览器打开"""
    s = status
    overall = s.get('overall', 'unknown')
    labels = {'success': '✅ 全部成功', 'partial': '⚠️ 部分完成', 'failed': '❌ 执行失败', 'running': '⏳ 运行中'}
    colors = {'success': '#30d158', 'partial': '#ff9f0a', 'failed': '#ff375f', 'running': '#2997ff'}
    label = labels.get(overall, overall)
    color = colors.get(overall, '#999')
    mins = s.get('duration_sec', 0) // 60
    secs = s.get('duration_sec', 0) % 60
    dur = f'{mins}分{secs}秒' if mins else f'{secs}秒'

    steps_html = ''
    for st in s.get('steps', []):
        icon = '✅' if st.get('ok') else '❌'
        steps_html += f'<tr><td>{icon}</td><td><b>{st["name"]}</b></td><td style="color:#888">{st.get("time","")}</td><td style="color:#666">{st.get("detail","")}</td></tr>\n'

    errors_html = ''
    if s.get('errors'):
        errors_html = '<div style="background:#fff0f0;border:1px solid #ffcdd2;border-radius:10px;padding:14px;margin-top:16px"><b style="color:#d32f2f">⚠️ 错误记录</b><ul style="margin:8px 0 0 16px;color:#666">'
        for e in s['errors']:
            errors_html += f'<li>{e}</li>'
        errors_html += '</ul></div>'

    html = f'''<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>每日更新报告 {s.get("date","")}</title>
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:600px;margin:40px auto;padding:20px;background:#fafafa;color:#333}}
  h1{{font-size:22px;margin-bottom:4px}} .sub{{color:#888;font-size:13px;margin-bottom:20px}}
  .badge{{display:inline-block;padding:6px 16px;border-radius:20px;font-weight:700;font-size:15px;color:#fff;background:{color}}}
  .cards{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:16px 0}}
  .card{{background:#fff;border-radius:12px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
  .card .v{{font-size:24px;font-weight:700;color:#1d1d1f}} .card .l{{font-size:11px;color:#888;margin-bottom:4px;text-transform:uppercase}}
  table{{width:100%;border-collapse:collapse;margin-top:16px}} td{{padding:6px 8px;border-bottom:1px solid #f0f0f0;font-size:13px}}
  .foot{{text-align:center;font-size:11px;color:#bbb;margin-top:24px}}
</style></head><body>
<h1>每日更新报告</h1>
<div class="sub">{s.get("date","")} {s.get("start_time","")} · {"快速模式" if s.get("mode")=="quick" else "全量模式"}</div>
<div class="badge">{label}</div>
<div class="cards">
  <div class="card"><div class="l">耗时</div><div class="v">{dur}</div></div>
  <div class="card"><div class="l">今日新增</div><div class="v">{s.get("added",0)} 条</div></div>
  <div class="card"><div class="l">数据总量</div><div class="v">{s.get("total",0)} 条</div></div>
  <div class="card"><div class="l">爬取原始</div><div class="v">{s.get("crawl_raw",0)} → {s.get("crawl_cleaned",0)}</div></div>
  <div class="card"><div class="l">Git 推送</div><div class="v">{"✅ 已推送" if s.get("git_pushed") else "❌ 未推送"}</div></div>
  <div class="card"><div class="l">Netlify 部署</div><div class="v">{"✅ 已部署" if s.get("deployed") else "❌ 未部署"}</div></div>
</div>
<b>执行时间线</b>
<table>{steps_html}</table>
{errors_html}
<div class="foot">更新于 {s.get("updated","")} · <a href="file://{BASE_DIR / "job_dashboard.html"}#run-status">打开 Dashboard</a></div>
</body></html>'''

    report_path = BASE_DIR / 'logs' / 'report.html'
    report_path.write_text(html, encoding='utf-8')
    return report_path


def _popup_report(status):
    """同时触发：① 系统通知 ② 弹窗对话框 ③ 浏览器报告"""
    from platform_utils import show_dialog, open_file
    s = status
    overall = s.get('overall', 'unknown')
    labels = {'success': '✅ 全部成功', 'partial': '⚠️ 部分完成', 'failed': '❌ 执行失败'}
    label = labels.get(overall, overall)
    added = s.get('added', 0)
    total = s.get('total', 0)
    mins = s.get('duration_sec', 0) // 60
    secs = s.get('duration_sec', 0) % 60
    dur = f'{mins}分{secs}秒' if mins else f'{secs}秒'
    banner_msg = f'新增 {added} 条，总计 {total} 条' if overall != 'failed' else '今日未抓取到数据'

    # ① 系统通知（不阻塞）
    _notify(f'AI 岗位扒取情况 - {label}', banner_msg)

    # ② 弹窗对话框（阻塞直到用户点击）
    try:
        git_s = '✅ 已推送' if s.get('git_pushed') else '❌ 未推送'
        net_s = '✅ 已部署' if s.get('deployed') else '❌ 未部署'
        err_line = f'\n⚠️ {len(s["errors"])} 个错误' if s.get('errors') else ''
        dialog_msg = (
            f'执行日期: {s.get("date", "")}\n'
            f'耗时: {dur}\n'
            f'今日新增: {added} 条\n'
            f'数据总量: {total} 条\n'
            f'爬取: {s.get("crawl_raw", 0)} → 清洗: {s.get("crawl_cleaned", 0)}\n\n'
            f'Git: {git_s}\n'
            f'Netlify: {net_s}\n\n'
            f'{label}{err_line}'
        )
        show_dialog('AI 岗位扒取情况', dialog_msg, buttons='ok', icon='info')
    except Exception:
        pass

    # ③ 浏览器报告
    try:
        report = _generate_report(status)
        logger.info(f'报告已生成: {report}')
        open_file(report)
    except Exception as e:
        logger.warning(f'报告弹出失败: {e}')


def _merge_keyword_terms(*groups):
    merged = []
    seen = set()
    for group in groups:
        for raw in group or []:
            term = str(raw or '').strip()
            if term and term not in seen:
                seen.add(term)
                merged.append(term)
    return merged


def _is_focus_keyword(term):
    upper = str(term or '').upper()
    return any(marker.upper() in upper for marker in FOCUS_KEYWORD_MARKERS)


def _prioritize_focus_keywords(keywords):
    focus = [kw for kw in keywords if _is_focus_keyword(kw)]
    normal = [kw for kw in keywords if not _is_focus_keyword(kw)]
    return _merge_keyword_terms(focus, normal)


def _filter_salary_jobs(jobs, min_avg=MIN_AVG_SALARY_K, max_avg=None):
    filtered = []
    for job in jobs:
        try:
            avg = float(job.get('avg') or 0)
        except Exception:
            avg = 0
        if avg >= min_avg and (max_avg is None or avg < max_avg):
            filtered.append(job)
    return filtered


def main():
    parser = argparse.ArgumentParser(description='AI PM 岗位每日更新')
    parser.add_argument('--dry-run', action='store_true', help='仅测试抓取，不写入文件')
    parser.add_argument('--quick', action='store_true', help='快速模式（随机3-5个关键词，标准翻页）')
    parser.add_argument('--account', default='', help='使用指定 BOSS 账号别名（config/boss_accounts.json）')
    args = parser.parse_args()

    # 应用账号池 Profile（把环境变量 AI_PM_BOSS_PROFILE 设置好，让 spider 加载对应 Cookie）
    if args.account:
        try:
            import sys as _sys
            _sys.path.insert(0, str(SCRIPT_DIR))
            import account_pool as _ap
            profile = _ap.get_account_profile_dir(args.account)
            if profile:
                import os as _os
                from pathlib import Path as _P
                p = _P(profile)
                if not p.is_absolute():
                    p = BASE_DIR / p
                _os.environ['AI_PM_BOSS_PROFILE'] = str(p)
                logger.info(f'🔑 daily_update 使用账号 [{args.account}] Profile={p}')
            else:
                logger.warning(f'账号 [{args.account}] 在配置中未找到，沿用默认 Profile')
        except Exception as e:
            logger.warning(f'账号池加载失败（沿用默认 Profile）: {e}')

    # ---- 运行状态追踪 ----
    _t0 = _time.time()
    status = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'start_time': datetime.now().strftime('%H:%M:%S'),
        'mode': 'quick' if args.quick else 'full',
        'steps': [],
        'overall': 'running',
        'crawl_raw': 0,
        'crawl_cleaned': 0,
        'added': 0,
        'total': 0,
        'has_url': 0,
        'has_desc': 0,
        'git_pushed': False,
        'deployed': False,
        'errors': [],
        'duration_sec': 0,
    }
    def _step(name, ok=True, detail=''):
        status['steps'].append({'name': name, 'ok': ok, 'detail': detail, 'time': datetime.now().strftime('%H:%M:%S')})
        _save_status(status)

    # 启动实时进度窗口
    _start_progress_window()

    logger.info('=' * 50)
    logger.info(f'开始每日更新 {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    logger.info('=' * 50)

    from spiders.boss_dp import load_config, load_keywords
    config = load_config()
    cities = config['cities']
    if args.quick:
        keywords = load_keywords(quick=True)
    else:
        keywords = config.get('keywords') or load_keywords(quick=False)
    keywords = _prioritize_focus_keywords(_merge_keyword_terms(FOCUS_KEYWORD_SEEDS, keywords))
    focus_keywords = [kw for kw in keywords if _is_focus_keyword(kw)]
    hangzhou_code = cities.get(HANGZHOU_CITY_NAME)
    if not hangzhou_code:
        logger.error('配置中未找到杭州城市码，无法执行杭州重点爬取')
        status['errors'].append('配置中未找到杭州城市码')
        _step('配置检查', False, '缺少杭州城市码')
        status['overall'] = 'failed'
        status['duration_sec'] = round(_time.time() - _t0)
        _save_status(status)
        _finish_progress(status)
        _popup_report(status)
        return False
    hangzhou_city = {HANGZHOU_CITY_NAME: hangzhou_code}
    other_cities = {k: v for k, v in cities.items() if k != HANGZHOU_CITY_NAME}
    is_greedy = not args.quick
    mode_label = '快速' if args.quick else '全量(贪婪)'
    logger.info(f'[{mode_label}] 杭州重点策略: {len(keywords)} 关键词，其中重点方向 {len(focus_keywords)} 个')
    logger.info(f'[{mode_label}] 其他城市: {list(other_cities.keys())}')

    from pipeline import process_batch
    from merger import load_existing, merge, save, save_snapshot
    from spiders.boss_dp import BossDPSpider

    spider = BossDPSpider()
    total_kws = len(keywords)
    total_added = 0
    total_raw = 0
    total_cleaned = 0
    _crawl_t0 = _time.time()

    # 后续流程步骤（未执行）
    _pending_phases = [
        '导出总表', '生成知识库', '飞书同步', 'Git 推送', '云同步',
    ]

    _write_progress(5, '🔍 正在爬取 BOSS 直聘...', f'杭州17K以上两遍 + 重点方向加倍；其他城市一次', status.get('steps', []))

    # 启动浏览器 + 登录
    try:
        spider.start_browser(headless=False)
        first_city = list(cities.values())[0]
        if not spider.ensure_login(first_city):
            try:
                spider.page.quit()
            except Exception:
                pass
            logger.error('登录失败，无法继续')
            status['errors'].append('登录失败')
            _step('登录', False, '登录未成功')
            status['overall'] = 'failed'
            status['duration_sec'] = round(_time.time() - _t0)
            _save_status(status)
            _finish_progress(status)
            _popup_report(status)
            return False
        _step('登录', True, '已登录')
    except Exception as e:
        logger.error(f'浏览器启动/登录失败: {e}', exc_info=True)
        status['errors'].append(f'登录失败: {e}')
        _step('登录', False, str(e))
        status['overall'] = 'failed'
        status['duration_sec'] = round(_time.time() - _t0)
        _save_status(status)
        _finish_progress(status)
        _popup_report(status)
        return False

    spider._processed_keys = set()

    def _crawl_stage(stage_idx, stage_count, stage_name, stage_keywords, stage_cities,
                     salary_specs, min_avg=MIN_AVG_SALARY_K, max_avg=None):
        nonlocal total_added, total_raw, total_cleaned
        if not stage_keywords or not stage_cities:
            logger.info(f'{stage_name}: 无关键词或城市，跳过')
            _step(stage_name, True, '无关键词或城市，跳过')
            return

        spider.all_jobs = {}
        spider._processed_keys = set()
        stage_units = max(1, len(stage_keywords) * len(salary_specs))

        for spec_idx, spec in enumerate(salary_specs, 1):
            salary_code = spec.get('code', '')
            salary_label = spec.get('label', '')
            for kw_idx, kw in enumerate(stage_keywords, 1):
                unit_idx = (spec_idx - 1) * len(stage_keywords) + kw_idx
                pct = 5 + int(70 * ((stage_idx - 1) + unit_idx / stage_units) / max(stage_count, 1))
                _write_progress(
                    pct,
                    f'🔍 {stage_name}',
                    f'{kw} · {salary_label} [{unit_idx}/{stage_units}]',
                    status.get('steps', [])
                )

                try:
                    kw_raw = spider.run_keyword(
                        kw,
                        stage_cities,
                        greedy=is_greedy,
                        salary_code=salary_code,
                        salary_label=salary_label,
                        stop_on_no_new=True,
                    )
                    total_raw += len(kw_raw)
                    logger.info(f'{stage_name} [{kw}] [{salary_label}] 抓取 {len(kw_raw)} 条原始数据')

                    if not kw_raw:
                        _step(f'{stage_name}: {kw} {salary_label}', True, '无数据')
                        continue

                    kw_cleaned_all = process_batch(kw_raw)
                    kw_cleaned = _filter_salary_jobs(kw_cleaned_all, min_avg=min_avg, max_avg=max_avg)
                    total_cleaned += len(kw_cleaned)
                    logger.info(f'{stage_name} [{kw}] [{salary_label}] 清洗 {len(kw_cleaned_all)} → 薪资过滤 {len(kw_cleaned)} 条')

                    if args.dry_run:
                        logger.info(f'[DRY RUN] {stage_name} {kw} {salary_label}: {len(kw_cleaned)} 条')
                        for j in kw_cleaned[:3]:
                            logger.info(f'  {j["title"]} | {j["company"]} | {j["city"]} | {j["salary"]}')
                        continue

                    if not kw_cleaned:
                        _step(f'{stage_name}: {kw} {salary_label}', True, '薪资过滤后无数据')
                        continue

                    existing_keys, existing_jobs = load_existing()
                    old_total = len(existing_jobs)
                    merged, kw_added = merge(existing_jobs, existing_keys, kw_cleaned)
                    save(merged)
                    save_snapshot(kw_cleaned)
                    total_added += kw_added

                    logger.info(f'{stage_name} [{kw}] 合并: 原{old_total}+新{len(kw_raw)}→清{len(kw_cleaned)}→+{kw_added}=总{len(merged)}')
                    _step(f'{stage_name}: {kw} {salary_label}', True, f'+{kw_added}条 (累计+{total_added})')

                    status['crawl_raw'] = total_raw
                    status['crawl_cleaned'] = total_cleaned
                    status['added'] = total_added
                    status['total'] = len(merged)
                    _save_status(status)
                except Exception as e:
                    logger.error(f'{stage_name} [{kw}] [{salary_label}] 处理失败: {e}', exc_info=True)
                    status['errors'].append(f'{stage_name}/{kw}/{salary_label}: {e}')
                    _step(f'{stage_name}: {kw} {salary_label}', False, str(e)[:200])

        elapsed = _time.time() - _crawl_t0
        eta_min = elapsed / max(stage_idx, 1) * (stage_count - stage_idx) / 60
        _write_progress(
            5 + int(70 * stage_idx / max(stage_count, 1)),
            f'🔍 已完成 {stage_name}',
            f'累计新增 {total_added} 条 · 剩余阶段 ≈{eta_min:.0f}分钟',
            status.get('steps', []) + [{'name': ph, 'ok': None, 'detail': '待执行', 'time': ''} for ph in _pending_phases]
        )

    hangzhou_stages = [
        ('杭州第1轮17K以上', keywords, SALARY_SPECS_17_PLUS, MIN_AVG_SALARY_K, None),
        ('杭州第2轮17K以上', keywords, SALARY_SPECS_17_PLUS, MIN_AVG_SALARY_K, None),
    ]
    if focus_keywords:
        hangzhou_stages.append(('杭州重点方向17K以上加倍轮次', focus_keywords, SALARY_SPECS_17_PLUS, MIN_AVG_SALARY_K, None))

    total_stage_count = len(hangzhou_stages) + (1 if other_cities else 0)
    stage_no = 0
    for stage_name, stage_keywords, salary_specs, min_avg, max_avg in hangzhou_stages:
        stage_no += 1
        _crawl_stage(stage_no, total_stage_count, stage_name, stage_keywords, hangzhou_city, salary_specs, min_avg, max_avg)

    if not args.dry_run:
        try:
            existing_keys, existing_jobs = load_existing()
            before_hz_clean = len(existing_jobs)
            save(existing_jobs)
            existing_keys, existing_jobs = load_existing()
            status['total'] = len(existing_jobs)
            _save_status(status)
            logger.info(f'✅ 杭州清洗去重完成: {before_hz_clean} → {len(existing_jobs)}')
            _step('杭州清洗去重完成', True, f'{before_hz_clean} → {len(existing_jobs)} 条')
        except Exception as e:
            logger.warning(f'杭州清洗去重失败(非致命): {e}')
            status['errors'].append(f'杭州清洗去重失败: {e}')
            _step('杭州清洗去重完成', False, str(e))

    if other_cities:
        stage_no += 1
        _crawl_stage(stage_no, total_stage_count, '其他城市爬取17K以上一次', keywords, other_cities, OTHER_CITY_SALARY_SPECS, MIN_AVG_SALARY_K, None)

    # 关闭浏览器
    try:
        spider.page.quit()
    except Exception:
        pass

    status['crawl_raw'] = total_raw
    status['crawl_cleaned'] = total_cleaned
    status['added'] = total_added
    _save_status(status)

    try:
        existing_keys, existing_jobs = load_existing()
        before_clean_total = len(existing_jobs)
        save(existing_jobs)
        existing_keys, existing_jobs = load_existing()
        status['total'] = len(existing_jobs)
        _save_status(status)
        logger.info(f'✅ 上传前数据清洗完成: {before_clean_total} → {len(existing_jobs)}')
        _step('上传前清洗', True, f'{before_clean_total} → {len(existing_jobs)} 条')
    except Exception as e:
        logger.warning(f'上传前数据清洗失败(非致命): {e}')
        status['errors'].append(f'上传前数据清洗失败: {e}')
        _step('上传前清洗', False, str(e))

    if total_raw == 0:
        logger.warning('今日未抓取到任何数据！')
        status['overall'] = 'failed'
        status['duration_sec'] = round(_time.time() - _t0)
        _step('终止', False, '未抓取到任何数据')
        _save_status(status)
        _finish_progress(status)
        _popup_report(status)
        return False

    if args.dry_run:
        logger.info('[DRY RUN] 完成，不写入文件')
        return True

    if total_added == 0:
        logger.warning('⚠️ 今日新增为 0，可能被反爬或无新岗位')

    # === 7. 导出统一总表 ===
    _write_progress(78, '📊 导出总表...', '', status.get('steps', []))
    try:
        subprocess.run([sys.executable, str(SCRIPT_DIR / 'export_total.py')],
                       cwd=str(BASE_DIR), check=True, timeout=900)
        logger.info('✅ 统一总表已导出')
        _step('导出总表', True)
    except subprocess.TimeoutExpired:
        logger.warning('总表导出超时(15分钟)，已跳过')
        _step('导出总表', False, '超时 15 分钟')
    except Exception as e:
        logger.warning(f'总表导出失败(非致命): {e}')
        _step('导出总表', False, str(e))

    # === 7.5 生成知识库 + 复制到 RAG 资料目录 ===
    _write_progress(82, '📚 生成知识库...', '', status.get('steps', []))
    try:
        subprocess.run([sys.executable, str(SCRIPT_DIR / 'gen_knowledge.py')],
                       cwd=str(BASE_DIR), check=True, timeout=900)
        logger.info('✅ knowledge_base.md + coze_prompt.txt + RAG_GUIDE.md 已重新生成')
        _step('生成知识库', True)
    except subprocess.TimeoutExpired:
        logger.warning('知识库生成超时(15分钟)，已跳过')
        _step('生成知识库', False, '超时 15 分钟')
    except Exception as e:
        logger.warning(f'知识库生成失败(非致命): {e}')
        _step('生成知识库', False, str(e))

    # === 7.6 同步知识库到飞书云文档 ===
    _write_progress(85, '📤 同步知识库到飞书...', '', status.get('steps', []))
    try:
        sync_ok = False
        sync_err = ''
        for _try in range(3):
            result = subprocess.run([sys.executable, str(SCRIPT_DIR / 'sync_feishu.py')],
                           cwd=str(BASE_DIR), capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=600)
            if result.returncode == 0:
                sync_ok = True
                break
            sync_err = (result.stderr or result.stdout or '')[:300]
            logger.warning(f'飞书同步第{_try+1}次失败: {sync_err[:200]}')
            _time.sleep(10 * (_try + 1))
        if sync_ok:
            logger.info('✅ 知识库已同步到飞书云文档')
            _step('飞书同步', True)
            logger.info('飞书岗位日报将在 Git 推送成功后发送')
        else:
            logger.warning(f'飞书同步失败: {sync_err[:200]}')
            status['errors'].append(f'飞书同步失败: {sync_err[:200]}')
            _step('飞书同步', False, sync_err[:200])
    except Exception as e:
        logger.warning(f'飞书同步失败(非致命): {e}')
        status['errors'].append(f'飞书同步失败: {e}')
        _step('飞书同步', False, str(e))

    # === 8. Git 提交 + 推送 ===
    _write_progress(87, '🔀 Git 推送中...', '', status.get('steps', []))
    try:
        # 自动检测本地代理并设置 git proxy，解决 GFW 环境下推送失败
        _proxy_set = False
        for _pport in [7897, 7890, 7891, 10808, 10809, 1080]:
            try:
                import socket
                with socket.create_connection(('127.0.0.1', _pport), timeout=1):
                    pass
                subprocess.run(['git', 'config', '--global', 'http.proxy', f'http://127.0.0.1:{_pport}'],
                               capture_output=True, timeout=5)
                subprocess.run(['git', 'config', '--global', 'https.proxy', f'http://127.0.0.1:{_pport}'],
                               capture_output=True, timeout=5)
                logger.info(f'检测到本地代理 127.0.0.1:{_pport}，已设置 git proxy')
                _proxy_set = True
                break
            except (OSError, socket.timeout):
                continue
        if not _proxy_set:
            logger.info('未检测到本地代理，git 将直连推送')
        today = datetime.now().strftime('%Y-%m-%d')
        branch_ret = subprocess.run(['git', 'branch', '--show-current'],
                                    cwd=str(BASE_DIR), capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=30)
        publish_branch = (branch_ret.stdout or '').strip() or 'main'
        status['git_branch'] = publish_branch
        status['main_published'] = publish_branch == 'main'
        subprocess.run(['git', 'add', '-A'], cwd=str(BASE_DIR), check=True, timeout=120)
        diff_ret = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=str(BASE_DIR), timeout=60)
        if diff_ret.returncode == 0:
            logger.info('✅ 无文件变更，跳过 Git 提交与推送')
            status['git_pushed'] = True
            _step('Git 推送', True, '无文件变更，跳过提交')
        else:
            commit_ret = subprocess.run(['git', 'commit', '-m',
                              f'daily: {today} 新增{total_added}条 总{status["total"]}条'],
                            cwd=str(BASE_DIR), capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=120)
            if commit_ret.returncode != 0:
                raise RuntimeError(f'Git commit 失败: {(commit_ret.stderr or commit_ret.stdout)[:200]}')
            push_ok = False
            last_push_err = ''
            for _try in range(5):
                try:
                    ret = subprocess.run(['git', 'push', 'origin', f'HEAD:{publish_branch}'],
                                          cwd=str(BASE_DIR), capture_output=True, text=True,
                                          encoding='utf-8', errors='replace', timeout=180)
                except subprocess.TimeoutExpired:
                    last_push_err = 'git push 超时 180s'
                    logger.warning(f'Git push 第{_try+1}次超时，继续重试')
                    _time.sleep(5 * (_try + 1))
                    continue
                if ret.returncode == 0:
                    push_ok = True
                    break
                last_push_err = (ret.stderr or ret.stdout or '')[:200]
                logger.warning(f'Git push 第{_try+1}次失败(code={ret.returncode}): {last_push_err[:120]}')
                _time.sleep(5 * (_try + 1))
            if push_ok:
                logger.info(f'✅ Git 提交推送完成: {publish_branch}')
                status['git_pushed'] = True
                _step('Git 推送', True, f'daily: {today} -> {publish_branch}')
            else:
                raise RuntimeError(f'Git push 5次均失败: {last_push_err}')
    except Exception as e:
        logger.warning(f'Git 推送失败(非致命): {e}')
        status['errors'].append(f'Git 推送失败: {e}')
        _step('Git 推送', False, str(e))

    # === 9. 数据已通过 Git 推送同步（GitHub Raw URL 自动更新，无需 Netlify 部署） ===
    _write_progress(93, '☁️ 数据已通过 Git 云同步', '', status.get('steps', []))
    if status.get('git_pushed') and status.get('main_published', True):
        status['deployed'] = True
        _step('云同步', True, '数据已通过 GitHub Raw URL 自动更新')
    elif status.get('git_pushed'):
        status['deployed'] = False
        _step('云同步', False, f'已推送到临时分支 {status.get("git_branch")}，main 网页未更新')
    else:
        _step('云同步', False, 'Git 推送未成功，数据未同步')

    # === 10. 最终汇报 ===
    with open(BASE_DIR / 'jobs_data.json', 'r', encoding='utf-8') as f:
        final = json.load(f)
    final_jobs = final.get('jobs', [])
    has_url = sum(1 for j in final_jobs if j.get('url'))
    has_desc = sum(1 for j in final_jobs if j.get('desc') and len(j['desc'].strip()) >= 20)
    logger.info('=' * 50)
    logger.info(f'✅ 每日更新全流程完成')
    logger.info(f'   总岗位: {len(final_jobs)}')
    logger.info(f'   新增: {total_added}')
    logger.info(f'   有链接: {has_url}/{len(final_jobs)}')
    logger.info(f'   有描述: {has_desc}/{len(final_jobs)}')
    logger.info('=' * 50)

    # ---- 最终状态 ----
    status['total'] = len(final_jobs)
    status['has_url'] = has_url
    status['has_desc'] = has_desc
    status['duration_sec'] = round(_time.time() - _t0)
    status['overall'] = 'success' if not status['errors'] else 'partial'
    try:
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
        else:
            logger.info('本轮无新增岗位，跳过飞书日报推送')
    except Exception as _e:
        logger.warning(f'飞书岗位日报推送失败(非致命): {_e}')
    _step('全流程完成', True, f'总 {len(final_jobs)} 条，新增 {total_added} 条')
    _save_status(status)
    _finish_progress(status)
    _popup_report(status)
    return not status['errors']


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
