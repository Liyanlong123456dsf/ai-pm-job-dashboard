#!/usr/bin/env python3
"""
每日自动更新入口
用法：
  python3 daily_update.py              # 正常运行（抓取+合并）
  python3 daily_update.py --dry-run    # 仅测试爬虫，不写入文件
  python3 daily_update.py --boss-cookie "xxx"  # 指定 BOSS 直聘 Cookie
"""
import sys
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


def _notify(title, message):
    """发送 macOS 原生通知"""
    try:
        import subprocess
        script = f'display notification "{message}" with title "{title}" sound name "Glass"'
        subprocess.run(['osascript', '-e', script], timeout=5)
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
    """同时触发：① 右上角横幅通知 ② 弹窗对话框 ③ 浏览器报告"""
    import subprocess
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

    # ① 右上角横幅通知（不阻塞）
    _notify(f'AI 岗位扒取情况 - {label}', banner_msg)

    # ② 弹窗对话框（阻塞直到用户点击）
    try:
        git_s = '✅ 已推送' if s.get('git_pushed') else '❌ 未推送'
        net_s = '✅ 已部署' if s.get('deployed') else '❌ 未部署'
        err_line = f'\n⚠️ {len(s["errors"])} 个错误' if s.get('errors') else ''
        dialog_msg = (
            f'📅 执行日期: {s.get("date", "")}\n'
            f'⏱ 耗时: {dur}\n'
            f'📊 今日新增: {added} 条\n'
            f'📦 数据总量: {total} 条\n'
            f'🔀 爬取: {s.get("crawl_raw", 0)} → 清洗: {s.get("crawl_cleaned", 0)}\n\n'
            f'Git: {git_s}\n'
            f'Netlify: {net_s}\n\n'
            f'{label}{err_line}'
        )
        dialog_script = (
            f'display dialog "{dialog_msg}" '
            f'with title "AI 岗位扒取情况" '
            f'buttons {{"查看详细报告", "好的"}} default button 2 with icon note'
        )
        result = subprocess.run(['osascript', '-e', dialog_script],
                                capture_output=True, text=True, timeout=300)
        clicked_report = '查看详细报告' in result.stdout
    except Exception:
        clicked_report = False

    # ③ 浏览器报告（弹窗点了"查看详细报告"或自动打开）
    try:
        report = _generate_report(status)
        subprocess.Popen(['open', str(report)])
    except Exception as e:
        logger.warning(f'报告弹出失败: {e}')


def main():
    parser = argparse.ArgumentParser(description='AI PM 岗位每日更新')
    parser.add_argument('--dry-run', action='store_true', help='仅测试抓取，不写入文件')
    parser.add_argument('--quick', action='store_true', help='快速模式：只用核心关键词和TOP5城市')
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

    logger.info('=' * 50)
    logger.info(f'开始每日更新 {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    logger.info('=' * 50)

    # Load config
    config_file = BASE_DIR / 'config' / 'keywords.json'
    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)

    keywords = config['keywords']
    cities = config['cities']

    if args.quick:
        keywords = ['AI产品经理', 'AIGC产品经理']
        cities = {k: v for i, (k, v) in enumerate(cities.items()) if i < 5}
        logger.info(f'[QUICK] 关键词: {keywords}, 城市: {list(cities.keys())}')

    # === 1. 抓取 ===
    all_raw = []

    # BOSS直聘 (DrissionPage 自动化浏览器)
    try:
        from spiders.boss_dp import BossDPSpider
        spider = BossDPSpider()
        jobs = spider.run(keywords, cities, headless=True)
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
        _popup_report(status)
        return

    # === 2. 清洗 ===
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
    from merger import load_existing, merge, save, save_snapshot
    existing_keys, existing_jobs = load_existing()
    merged, added_count = merge(existing_jobs, existing_keys, cleaned)

    # === 4. 保存 ===
    save(merged)
    save_snapshot(cleaned)

    logger.info(f'合并完成: 新增 {added_count} 条, 总计 {len(merged)} 条')
    status['added'] = added_count
    status['total'] = len(merged)
    _step('增量合并', True, f'新增 {added_count} 条，总计 {len(merged)} 条')

    if added_count == 0:
        logger.warning('⚠️ 今日新增为 0，可能被反爬或无新岗位')

    # === 5. 回填链接 ===
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
    try:
        with open(BASE_DIR / 'jobs_data.json', 'r', encoding='utf-8') as f:
            data_check = json.load(f)
        missing = sum(1 for j in data_check.get('jobs', [])
                      if j.get('url') and (not j.get('desc') or len(j['desc'].strip()) < 20))
        if missing > 0:
            logger.info(f'发现 {missing} 条描述缺失，开始追踪补全...')
            subprocess.run([sys.executable, str(SCRIPT_DIR / 'backfill_desc.py')],
                           cwd=str(BASE_DIR), check=True)
            logger.info('✅ 描述补全完成')
            _step('补全描述', True, f'补全 {missing} 条')
        else:
            logger.info('所有岗位描述完整，跳过补全')
            _step('补全描述', True, '描述完整，跳过')
    except Exception as e:
        logger.warning(f'描述补全失败(非致命): {e}')
        _step('补全描述', False, str(e))

    # === 7. 导出统一总表 ===
    try:
        subprocess.run([sys.executable, str(SCRIPT_DIR / 'export_total.py')],
                       cwd=str(BASE_DIR), check=True)
        logger.info('✅ 统一总表已导出')
        _step('导出总表', True)
    except Exception as e:
        logger.warning(f'总表导出失败(非致命): {e}')
        _step('导出总表', False, str(e))

    # === 7.5 生成知识库 + 复制到 RAG 资料目录 ===
    try:
        subprocess.run([sys.executable, str(SCRIPT_DIR / 'gen_knowledge.py')],
                       cwd=str(BASE_DIR), check=True)
        logger.info('✅ knowledge_base.md + coze_prompt.txt + RAG_GUIDE.md 已重新生成')
        _step('生成知识库', True)
    except Exception as e:
        logger.warning(f'知识库生成失败(非致命): {e}')
        _step('生成知识库', False, str(e))

    # === 8. Git 提交 + 推送 ===
    try:
        import subprocess
        today = datetime.now().strftime('%Y-%m-%d')
        subprocess.run(['git', 'add', '-A'], cwd=str(BASE_DIR), check=True)
        subprocess.run(['git', 'commit', '-m',
                         f'daily: {today} 新增{added_count}条 总{len(merged)}条'],
                       cwd=str(BASE_DIR), check=True)
        subprocess.run(['git', 'push', 'origin', 'main'], cwd=str(BASE_DIR), check=True)
        logger.info('✅ Git 提交推送完成')
        status['git_pushed'] = True
        _step('Git 推送', True, f'daily: {today}')
    except Exception as e:
        logger.warning(f'Git 推送失败(非致命): {e}')
        status['errors'].append(f'Git 推送失败: {e}')
        _step('Git 推送', False, str(e))

    # === 9. 同步 dist 目录 + Netlify 部署 ===
    try:
        dist_dir = BASE_DIR / 'dist'
        dist_dir.mkdir(exist_ok=True)
        import shutil
        for fname in ['job_dashboard.html', 'jobs_data.json', 'index.html', 'netlify.toml', 'knowledge_base.md', 'run_status.json']:
            src = BASE_DIR / fname
            if src.exists():
                shutil.copy2(src, dist_dir / fname)
        logger.info(f'dist 目录已同步')
        result = subprocess.run(['netlify', 'deploy', '--prod', '--dir=dist'],
                                cwd=str(BASE_DIR), capture_output=True, text=True)
        if result.returncode == 0:
            logger.info('✅ Netlify 部署完成')
            status['deployed'] = True
            _step('Netlify 部署', True)
        else:
            logger.warning(f'Netlify 部署失败: {result.stderr}')
            status['errors'].append(f'Netlify: {result.stderr[:200]}')
            _step('Netlify 部署', False, result.stderr[:200])
    except Exception as e:
        logger.warning(f'Netlify 部署失败(非致命): {e}')
        status['errors'].append(f'Netlify: {e}')
        _step('Netlify 部署', False, str(e))

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
    _popup_report(status)


if __name__ == '__main__':
    main()
