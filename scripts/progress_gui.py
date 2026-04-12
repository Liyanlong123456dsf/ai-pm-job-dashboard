#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面进度弹窗 — 深色主题
每 800ms 读取 logs/progress.json 实时刷新
设计参考：Apple HIG 风格
"""
import json
import tkinter as tk
from tkinter import ttk
from pathlib import Path

PROGRESS_FILE = Path(__file__).parent.parent / 'logs' / 'progress.json'
POLL_MS = 800

# === Apple Design System 色板 ===
BG_DARK    = '#000000'
BG_SURFACE = '#1d1d1f'
BG_CARD    = '#2c2c2e'
APPLE_BLUE = '#0071e3'
BRIGHT_BLUE = '#2997ff'
WHITE      = '#ffffff'
GRAY_80    = '#cccccc'  # 80% white
GRAY_48    = '#7a7a7a'  # 48%
GREEN      = '#30d158'
ORANGE     = '#ff9f0a'
RED        = '#ff453a'

# 跨平台字体选择
import platform as _plat
if _plat.system() == 'Windows':
    FONT_DISPLAY = 'Segoe UI'
    FONT_TEXT    = 'Segoe UI'
else:
    FONT_DISPLAY = 'SF Pro Display'
    FONT_TEXT    = 'SF Pro Text'
FONT_FALLBACK = ('Segoe UI', 'Helvetica Neue', 'Helvetica', 'Arial')

W = 480
H = 500


def _font(family, size, weight='normal'):
    """构建字体元组，确保 fallback"""
    return (family, size, weight)


class ProgressWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('AI 岗位爬取')
        self.root.geometry('{}x{}'.format(W, H))
        self.root.resizable(False, False)
        self.root.configure(bg=BG_DARK)
        self.root.attributes('-topmost', True)
        self.root.after(5000, lambda: self.root.attributes('-topmost', False))

        # === 顶部留白 + 主标题区 (Dark Hero) ===
        hero = tk.Frame(self.root, bg=BG_DARK)
        hero.pack(fill='x', padx=32, pady=(28, 0))

        self.title_lbl = tk.Label(
            hero, text='岗位爬取中',
            font=_font(FONT_DISPLAY, 24, 'bold'),
            fg=WHITE, bg=BG_DARK, anchor='center')
        self.title_lbl.pack()

        self.subtitle_lbl = tk.Label(
            hero, text='正在启动...',
            font=_font(FONT_TEXT, 13),
            fg=GRAY_48, bg=BG_DARK, anchor='center')
        self.subtitle_lbl.pack(pady=(2, 0))

        # === 进度区域 ===
        progress_area = tk.Frame(self.root, bg=BG_DARK)
        progress_area.pack(fill='x', padx=32, pady=(20, 0))

        # 进度条：Frame 模拟圆角条
        bar_track = tk.Frame(progress_area, bg=BG_CARD, height=6)
        bar_track.pack(fill='x')
        bar_track.pack_propagate(False)
        self.bar_fill = tk.Frame(bar_track, bg=APPLE_BLUE, width=0)
        self.bar_fill.place(x=0, y=0, relheight=1.0, width=0)
        self._bar_track = bar_track

        # 百分比 + 阶段 并排
        info_row = tk.Frame(self.root, bg=BG_DARK)
        info_row.pack(fill='x', padx=32, pady=(12, 0))

        self.pct_lbl = tk.Label(
            info_row, text='0%',
            font=_font(FONT_DISPLAY, 40, 'bold'),
            fg=APPLE_BLUE, bg=BG_DARK, anchor='w')
        self.pct_lbl.pack(side='left')

        phase_col = tk.Frame(info_row, bg=BG_DARK)
        phase_col.pack(side='left', padx=(16, 0), anchor='s', pady=(0, 6))

        self.phase_lbl = tk.Label(
            phase_col, text='初始化',
            font=_font(FONT_TEXT, 14, 'bold'),
            fg=WHITE, bg=BG_DARK, anchor='w')
        self.phase_lbl.pack(anchor='w')

        self.detail_lbl = tk.Label(
            phase_col, text='',
            font=_font(FONT_TEXT, 11),
            fg=GRAY_48, bg=BG_DARK, anchor='w')
        self.detail_lbl.pack(anchor='w')

        # === 分隔线 ===
        sep = tk.Frame(self.root, bg=BG_CARD, height=1)
        sep.pack(fill='x', padx=32, pady=(16, 0))

        # === 步骤列表区 (Surface Card — 可滚动) ===
        steps_container = tk.Frame(self.root, bg=BG_DARK)
        steps_container.pack(fill='both', expand=True, padx=32, pady=(12, 0))

        steps_header = tk.Label(
            steps_container, text='执行步骤',
            font=_font(FONT_TEXT, 11, 'bold'),
            fg=GRAY_48, bg=BG_DARK, anchor='w')
        steps_header.pack(fill='x', pady=(0, 4))

        self.steps_text = tk.Text(
            steps_container, font=_font(FONT_TEXT, 11),
            bg=BG_CARD, fg=GRAY_80, relief='flat',
            highlightthickness=0, borderwidth=0,
            padx=10, pady=8, wrap='word',
            insertbackground=BG_CARD, cursor='arrow')
        self.steps_text.pack(fill='both', expand=True)
        self.steps_text.configure(state='disabled')
        # 配置标签颜色
        self.steps_text.tag_configure('ok', foreground=GREEN)
        self.steps_text.tag_configure('fail', foreground=RED)
        self.steps_text.tag_configure('run', foreground=BRIGHT_BLUE)
        self.steps_text.tag_configure('pending', foreground=GRAY_48)
        self.steps_text.tag_configure('dim', foreground=GRAY_48)

        # === 底部时间戳 ===
        self.ts_lbl = tk.Label(
            self.root, text='',
            font=_font(FONT_TEXT, 10),
            fg=GRAY_48, bg=BG_DARK, anchor='center')
        self.ts_lbl.pack(fill='x', padx=32, pady=(4, 16))

        self.root.update_idletasks()
        self.poll()
        self.root.mainloop()

    def poll(self):
        try:
            if PROGRESS_FILE.exists():
                data = json.loads(
                    PROGRESS_FILE.read_text(encoding='utf-8'))
                pct = data.get('pct', 0)
                phase = data.get('phase', '')
                detail = data.get('detail', '')
                steps = data.get('steps', [])
                done = data.get('done', False)
                ts = data.get('ts', '')

                # 进度条
                self.root.update_idletasks()
                tw = self._bar_track.winfo_width()
                fw = max(0, int(tw * pct / 100))
                self.bar_fill.place_configure(width=fw)

                # 文本
                self.pct_lbl.configure(text='{}%'.format(pct))
                self.phase_lbl.configure(text=phase.replace(
                    '\U0001f50d ', '').replace('\U0001f9f9 ', ''))
                self.detail_lbl.configure(text=detail)
                self.subtitle_lbl.configure(
                    text=phase if not done else '')
                if ts:
                    self.ts_lbl.configure(text=ts)

                # 步骤列表（可滚动 Text）
                self.steps_text.configure(state='normal')
                self.steps_text.delete('1.0', 'end')
                for s in steps:
                    if s.get('ok') is True:
                        icon, tag = '\u2713 ', 'ok'
                    elif s.get('ok') is False:
                        icon, tag = '\u2717 ', 'fail'
                    elif s.get('detail') == '\u5f85\u6267\u884c':
                        icon, tag = '\u25cb ', 'pending'
                    else:
                        icon, tag = '\u2022 ', 'run'
                    self.steps_text.insert('end', icon, tag)
                    name_tag = 'pending' if tag == 'pending' else None
                    self.steps_text.insert('end', s.get('name', ''), name_tag)
                    dt = s.get('detail', '')
                    tm = s.get('time', '')
                    if dt or tm:
                        self.steps_text.insert(
                            'end', '  {}  {}'.format(dt, tm), 'dim')
                    self.steps_text.insert('end', '\n')
                self.steps_text.see('end')
                self.steps_text.configure(state='disabled')

                if done:
                    if pct >= 90:
                        self.title_lbl.configure(text='爬取完成')
                        self.bar_fill.configure(bg=GREEN)
                        self.pct_lbl.configure(fg=GREEN)
                    elif pct >= 50:
                        self.title_lbl.configure(text='部分完成')
                        self.bar_fill.configure(bg=ORANGE)
                        self.pct_lbl.configure(fg=ORANGE)
                    else:
                        self.title_lbl.configure(text='执行失败')
                        self.bar_fill.configure(bg=RED)
                        self.pct_lbl.configure(fg=RED)
                    self.subtitle_lbl.configure(text='')
                    self.root.after(10000, self.root.destroy)
                    return
        except Exception:
            pass
        self.root.after(POLL_MS, self.poll)


if __name__ == '__main__':
    ProgressWindow()
