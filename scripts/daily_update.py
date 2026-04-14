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
        'ts': datetime.now().strftime('%H:%M:%S'),
    }
    with open(_PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def _start_progress_window():
    """启动桌面进度弹窗（Tkinter）"""
    import subprocess
    _write_progress(0, '启动中...', '')
    gui_script = SCRIPT_DIR / 'progress_gui.py'
    subprocess.Popen([sys.executable, str(gui_script)])


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
            f'爬取: {s.get("crawl_raw", 0)} -> 清洗: {s.get("crawl_cleaned", 0)}\n\n'
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
        open_file(report)
    except Exception as e:
        logger.warning(f'报告弹出失败: {e}')


def main():
    parser = argparse.ArgumentParser(description='AI PM 岗位每日更新')
    parser.add_argument('--dry-run', action='store_true', help='仅测试抓取，不写入文件')
    parser.add_argument('--quick', action='store_true', help='快速模式（随机3-5个关键词，标准翻页）')
    args = parser.parse_args()

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

    # Load config
    from spiders.boss_dp import load_config, load_keywords
    config = load_config()
    keywords = load_keywords(quick=args.quick)
    cities = config['cities']
    is_greedy = not args.quick  # 全量模式用贪婪策略，快速模式用标准策略
    mode_label = '快速' if args.quick else '全量(贪婪)'
    logger.info(f'[{mode_label}] 关键词: {keywords}, 城市: {list(cities.keys())}')

    # === 1. 抓取 ===
    all_raw = []
    _write_progress(5, '🔍 正在爬取 BOSS 直聘...', f'{len(keywords)} 关键词 × {len(cities)} 城市', status.get('steps', []))

    # BOSS直聘 (DrissionPage 自动化浏览器)
    try:
        from spiders.boss_dp import BossDPSpider
        spider = BossDPSpider()
        _crawl_t0 = _time.time()
        _crawl_done_steps = []  # 累积所有已完成的爬取步骤

        # 后续流程步骤（未执行）
        _pending_phases = [
            '数据清洗', '增量合并', '补全描述',
            '导出总表', '生成知识库', '飞书同步', 'Git 推送', '云同步',
        ]

        def _on_spider_progress(combo_idx, total_combos, kw, city, job_count):
            pct = 5 + int(45 * combo_idx / max(total_combos, 1))
            remaining = total_combos - combo_idx
            elapsed = _time.time() - _crawl_t0
            eta_min = (elapsed / max(combo_idx, 1)) * remaining / 60
            skipped = getattr(spider, 'skipped_existing', 0)

            # 记录已完成步骤
            _crawl_done_steps.append({
                'name': f'{kw} @ {city}',
                'ok': True,
                'detail': f'累计 {job_count} 条' + (f' (跳过已有{skipped})' if skipped else ''),
                'time': datetime.now().strftime('%H:%M:%S'),
            })

            # 构建完整步骤列表: 前置步骤 + 已完成爬取 + 当前 + 未执行后续
            all_steps = list(status.get('steps', []))
            # 只显示最近 8 条已完成爬取（避免列表太长）
            recent = _crawl_done_steps[-8:] if len(_crawl_done_steps) > 8 else _crawl_done_steps
            if len(_crawl_done_steps) > 8:
                all_steps.append({
                    'name': f'... 已完成 {len(_crawl_done_steps)-8} 组 ...',
                    'ok': True, 'detail': '', 'time': '',
                })
            all_steps.extend(recent)
            # 未执行的后续流程
            for phase in _pending_phases:
                all_steps.append({'name': phase, 'ok': None, 'detail': '待执行', 'time': ''})

            _write_progress(
                pct, f'爬取: {kw} @ {city}',
                f'[{combo_idx}/{total_combos}] 新增 {job_count} 条 · 跳过已有 {skipped} · 剩余 {remaining} 组 ≈{eta_min:.0f}分钟',
                all_steps)
        spider._progress_cb = _on_spider_progress
        # BOSS直聘反爬会检测 headless，始终使用可见模式
        # 持久化 Profile 已有登录态时会自动跳过登录步骤
        profile_dir = Path(__file__).parent.parent / '.chrome_profile'
        has_profile = profile_dir.exists() and any(profile_dir.iterdir()) if profile_dir.exists() else False
        if has_profile:
            logger.info('检测到持久化 Profile，已有登录态将自动跳过登录')
        else:
            logger.info('首次运行，使用可见模式以便登录')
        jobs = spider.run(keywords, cities, headless=False, greedy=is_greedy)
        all_raw.extend(jobs)
        logger.info(f'BOSS直聘: 抓取 {len(jobs)} 条原始数据')
        status['crawl_raw'] = len(all_raw)
        _step('爬取 BOSS 直聘', True, f'抓取 {len(jobs)} 条原始数据')
    except Exception as e:
        logger.error(f'BOSS直聘 爬虫失败: {e}', exc_info=True)
        status['errors'].append(f'爬虫失败: {e}')
        _step('爬取 BOSS 直聘', False, str(e))

    if not all_raw:
        logger.warning('今日未抓取到任何数据！')
        status['overall'] = 'failed'
        status['duration_sec'] = round(_time.time() - _t0)
        _step('终止', False, '未抓取到任何数据')
        _save_status(status)
        _finish_progress(status)
        _popup_report(status)
        return

    # === 2. 清洗 ===
    _write_progress(52, '🧹 数据清洗中...', f'原始 {len(all_raw)} 条', status.get('steps', []))
    from pipeline import process_batch
    cleaned = process_batch(all_raw)
    logger.info(f'清洗后: {len(cleaned)} 条有效岗位')
    status['crawl_cleaned'] = len(cleaned)
    _step('数据清洗', True, f'{len(cleaned)} 条有效岗位')

    if args.dry_run:
        logger.info('[DRY RUN] 不写入文件，打印前 5 条:')
        for j in cleaned[:5]:
            logger.info(f'  {j["title"]} | {j["company"]} | {j["city"]} | {j["salary"]}')
        return

    # === 3. 合并 ===
    _write_progress(55, '🔀 增量合并中...', f'{len(cleaned)} 条清洗数据', status.get('steps', []))
    from merger import load_existing, merge, save, save_snapshot
    existing_keys, existing_jobs = load_existing()
    old_total = len(existing_jobs)
    merged, added_count = merge(existing_jobs, existing_keys, cleaned)

    # === 4. 保存 ===
    save(merged)
    save_snapshot(cleaned)

    logger.info(f'合并对比: 原有 {old_total} 条 + 抓取 {len(all_raw)} 条 → 清洗 {len(cleaned)} 条 → 新增 {added_count} 条 → 总计 {len(merged)} 条')
    status['added'] = added_count
    status['total'] = len(merged)
    _step('增量合并', True, f'原{old_total}+抓{len(all_raw)}→清{len(cleaned)}→新+{added_count}=总{len(merged)}')

    if added_count == 0:
        logger.warning('⚠️ 今日新增为 0，可能被反爬或无新岗位')

    # === 5. 回填链接 ===
    _write_progress(62, '🔗 回填链接...', '', status.get('steps', []))
    try:
        logger.info('开始回填链接...')
        import subprocess
        subprocess.run([sys.executable, str(SCRIPT_DIR / 'backfill_csv.py')],
                       cwd=str(BASE_DIR), check=True)
        logger.info('✅ 链接回填完成')
        _step('回填链接', True)
    except Exception as e:
        logger.warning(f'链接回填失败(非致命): {e}')
        _step('回填链接', False, str(e))

    # === 6. 补全缺失描述 ===
    _write_progress(68, '📝 补全描述中...', '', status.get('steps', []))
    try:
        with open(BASE_DIR / 'jobs_data.json', 'r', encoding='utf-8') as f:
            data_check = json.load(f)
        missing = sum(1 for j in data_check.get('jobs', [])
                      if j.get('url') and ((not j.get('desc') or len(j['desc'].strip()) < 20)
                       or not str(j.get('salary') or '').strip()))
        if missing > 0:
            logger.info(f'发现 {missing} 条详情缺失，开始追踪补全...')
            subprocess.run([sys.executable, str(SCRIPT_DIR / 'backfill_desc.py')],
                           cwd=str(BASE_DIR), check=True)
            logger.info('✅ 详情补全完成')
            _step('补全描述', True, f'补全 {missing} 条(描述/薪资)')
        else:
            logger.info('所有可追踪岗位详情完整，跳过补全')
            _step('补全描述', True, '描述/薪资完整，跳过')
    except Exception as e:
        logger.warning(f'详情补全失败(非致命): {e}')
        _step('补全描述', False, str(e))

    # === 7. 导出统一总表 ===
    _write_progress(78, '📊 导出总表...', '', status.get('steps', []))
    try:
        subprocess.run([sys.executable, str(SCRIPT_DIR / 'export_total.py')],
                       cwd=str(BASE_DIR), check=True)
        logger.info('✅ 统一总表已导出')
        _step('导出总表', True)
    except Exception as e:
        logger.warning(f'总表导出失败(非致命): {e}')
        _step('导出总表', False, str(e))

    # === 7.5 生成知识库 + 复制到 RAG 资料目录 ===
    _write_progress(82, '📚 生成知识库...', '', status.get('steps', []))
    try:
        subprocess.run([sys.executable, str(SCRIPT_DIR / 'gen_knowledge.py')],
                       cwd=str(BASE_DIR), check=True)
        logger.info('✅ knowledge_base.md + coze_prompt.txt + RAG_GUIDE.md 已重新生成')
        _step('生成知识库', True)
    except Exception as e:
        logger.warning(f'知识库生成失败(非致命): {e}')
        _step('生成知识库', False, str(e))

    # === 7.6 同步知识库到飞书云文档 ===
    _write_progress(85, '📤 同步知识库到飞书...', '', status.get('steps', []))
    try:
        result = subprocess.run([sys.executable, str(SCRIPT_DIR / 'sync_feishu.py')],
                       cwd=str(BASE_DIR), capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            logger.info('✅ 知识库已同步到飞书云文档')
            _step('飞书同步', True)
        else:
            logger.warning(f'飞书同步失败: {result.stderr[:200]}')
            _step('飞书同步', False, result.stderr[:200])
    except Exception as e:
        logger.warning(f'飞书同步失败(非致命): {e}')
        _step('飞书同步', False, str(e))

    # === 8. Git 提交 + 推送 ===
    _write_progress(87, '🔀 Git 推送中...', '', status.get('steps', []))
    try:
        import subprocess
        today = datetime.now().strftime('%Y-%m-%d')
        subprocess.run(['git', 'add', '-A'], cwd=str(BASE_DIR), check=True)
        subprocess.run(['git', 'commit', '-m',
                         f'daily: {today} 新增{added_count}条 总{len(merged)}条'],
                       cwd=str(BASE_DIR), check=True)
        push_ok = False
        for _try in range(3):
            ret = subprocess.run(['git', 'push', 'origin', 'main'],
                                 cwd=str(BASE_DIR), capture_output=True, text=True)
            if ret.returncode == 0:
                push_ok = True
                break
            logger.warning(f'Git push 第{_try+1}次失败(code={ret.returncode}): {ret.stderr[:120]}')
            import time as _t; _t.sleep(5)
        if push_ok:
            logger.info('✅ Git 提交推送完成')
            status['git_pushed'] = True
            _step('Git 推送', True, f'daily: {today}')
        else:
            raise RuntimeError(f'Git push 3次均失败: {ret.stderr[:200]}')
    except Exception as e:
        logger.warning(f'Git 推送失败(非致命): {e}')
        status['errors'].append(f'Git 推送失败: {e}')
        _step('Git 推送', False, str(e))

    # === 9. 数据已通过 Git 推送同步（GitHub Raw URL 自动更新，无需 Netlify 部署） ===
    _write_progress(93, '☁️ 数据已通过 Git 云同步', '', status.get('steps', []))
    if status.get('git_pushed'):
        status['deployed'] = True
        _step('云同步', True, '数据已通过 GitHub Raw URL 自动更新')
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
    logger.info(f'   新增: {added_count}')
    logger.info(f'   有链接: {has_url}/{len(final_jobs)}')
    logger.info(f'   有描述: {has_desc}/{len(final_jobs)}')
    logger.info('=' * 50)

    # ---- 最终状态 ----
    status['total'] = len(final_jobs)
    status['has_url'] = has_url
    status['has_desc'] = has_desc
    status['duration_sec'] = round(_time.time() - _t0)
    status['overall'] = 'success' if not status['errors'] else 'partial'
    _step('全流程完成', True, f'总 {len(final_jobs)} 条，新增 {added_count} 条')
    _save_status(status)
    _finish_progress(status)
    _popup_report(status)


if __name__ == '__main__':
    main()
