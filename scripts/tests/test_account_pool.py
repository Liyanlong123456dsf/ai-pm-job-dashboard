#!/usr/bin/env python3
"""account_pool 集成测试（从磁盘读写 state 文件）"""
import sys, io, json
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
BASE = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE / 'scripts'))

# 备份并清空状态
state_file = BASE / 'logs' / 'account_pool_state.json'
backup = state_file.read_text(encoding='utf-8') if state_file.exists() else None
if state_file.exists():
    state_file.unlink()

try:
    import account_pool as ap

    # 场景1: 初次 pick 应返回一个 healthy 账号
    acc = ap.pick_next_account()
    assert acc, '初次 pick 返回 None'
    assert acc['alias'] in ['主账号', '备用'], f'意外的 alias: {acc}'
    print(f'[场景1] ✓ 初次 pick = {acc["alias"]}')

    # 场景2: 标记主账号失败后，pick(exclude=['主账号']) 应返回备用
    ap.mark_failure('主账号', 'test detail')
    acc2 = ap.pick_next_account(exclude=['主账号'])
    assert acc2, f'exclude 后 pick 返回 None'
    assert acc2['alias'] == '备用', f'应返回 备用，实际: {acc2}'
    print(f'[场景2] ✓ exclude 主账号后 pick = {acc2["alias"]}')

    # 场景3: 两账号都失败
    ap.mark_failure('备用', 'test2')
    assert ap.all_failed(), 'all_failed 应为 True'
    failed = ap.get_failed_accounts()
    aliases = sorted([f['alias'] for f in failed])
    assert aliases == ['主账号', '备用'], f'失败列表异常: {aliases}'
    print(f'[场景3] ✓ all_failed=True, 失败列表={aliases}')

    # 场景4: 节流
    assert ap.should_send_all_failed_alert(), '节流初次应允许'
    ap.mark_alert_sent()
    assert not ap.should_send_all_failed_alert(), '节流应生效'
    print('[场景4] ✓ 节流机制正常')

    # 场景5: 主账号恢复 → pick 应返回主账号
    ap.mark_success('主账号')
    acc5 = ap.pick_next_account()
    assert acc5 and acc5['alias'] == '主账号', f'恢复后应选主账号: {acc5}'
    print(f'[场景5] ✓ 主账号恢复后 pick = {acc5["alias"]}')

    # 场景6: reset 备用
    ap.reset_account('备用')
    s = ap.get_summary()
    bu = next(a for a in s['accounts'] if a['alias'] == '备用')
    assert bu['status'] == 'healthy' and bu['fail_count'] == 0, f'重置失败: {bu}'
    print(f'[场景6] ✓ 重置备用, status={bu["status"]} fail_count={bu["fail_count"]}')

    # 场景7: 单账号降级
    cfg_file = BASE / 'config' / 'boss_accounts.json'
    orig_cfg = cfg_file.read_text(encoding='utf-8')
    try:
        cfg = json.loads(orig_cfg)
        cfg['accounts'][1]['enabled'] = False
        cfg_file.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
        assert not ap.is_multi_account_enabled(), '单账号 is_multi 应 False'
        acc7 = ap.pick_next_account()
        assert acc7 and acc7['alias'] == '主账号', f'单账号 pick 异常: {acc7}'
        print(f'[场景7] ✓ 单账号降级, pick = {acc7["alias"]}')
    finally:
        cfg_file.write_text(orig_cfg, encoding='utf-8')

    # 场景8: 摘要字段完整
    summary = ap.get_summary()
    assert 'enabled' in summary and 'accounts' in summary and 'all_failed' in summary
    assert summary['enabled'] is True  # 2个账号
    assert len(summary['accounts']) == 2
    for a in summary['accounts']:
        assert all(k in a for k in ['alias', 'status', 'fail_count', 'success_count', 'last_ok'])
    print(f'[场景8] ✓ get_summary 字段完整')

    print('')
    print('✅ 全部 8 个场景通过')
finally:
    # 恢复原始状态（若有）或清空
    if state_file.exists():
        state_file.unlink()
    if backup:
        state_file.write_text(backup, encoding='utf-8')
