#!/usr/bin/env python3
"""macOS 原生风格进度弹窗 — 读取 progress.json 实时显示"""
import json
import tkinter as tk
from tkinter import ttk
from pathlib import Path

PROGRESS_FILE = Path(__file__).parent.parent / 'logs' / 'progress.json'
POLL_MS = 1200  # 刷新间隔


class ProgressWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('AI 岗位爬取进度')
        self.root.geometry('420x320')
        self.root.resizable(False, False)
        # macOS 置顶
        self.root.attributes('-topmost', True)
        self.root.after(3000, lambda: self.root.attributes('-topmost', False))

        # 样式
        style = ttk.Style()
        style.theme_use('aqua')

        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill='both', expand=True)

        # 标题
        self.title_label = ttk.Label(frame, text='🤖 AI 岗位爬取中...', font=('SF Pro', 16, 'bold'))
        self.title_label.pack(pady=(0, 8))

        # 进度条
        self.progress = ttk.Progressbar(frame, length=360, mode='determinate', maximum=100)
        self.progress.pack(pady=(0, 4))

        # 百分比
        self.pct_label = ttk.Label(frame, text='0%', font=('SF Pro', 12))
        self.pct_label.pack(pady=(0, 6))

        # 阶段
        self.phase_label = ttk.Label(frame, text='初始化...', font=('SF Pro', 13, 'bold'), foreground='#6B4FBB')
        self.phase_label.pack(pady=(0, 2))

        # 详细信息
        self.detail_label = ttk.Label(frame, text='', font=('SF Pro', 11), foreground='#888')
        self.detail_label.pack(pady=(0, 10))

        # 步骤列表（滚动）
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill='both', expand=True)

        self.steps_text = tk.Text(list_frame, height=8, font=('SF Pro', 10), wrap='word',
                                  bg='#f5f5f7', relief='flat', highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=self.steps_text.yview)
        self.steps_text.configure(yscrollcommand=scrollbar.set)
        self.steps_text.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.steps_text.configure(state='disabled')

        # 开始轮询
        self.poll()
        self.root.mainloop()

    def poll(self):
        try:
            if PROGRESS_FILE.exists():
                data = json.loads(PROGRESS_FILE.read_text(encoding='utf-8'))
                pct = data.get('pct', 0)
                phase = data.get('phase', '')
                detail = data.get('detail', '')
                steps = data.get('steps', [])
                done = data.get('done', False)

                self.progress['value'] = pct
                self.pct_label.configure(text=f'{pct}%')
                self.phase_label.configure(text=phase)
                self.detail_label.configure(text=detail)

                # 更新步骤列表
                self.steps_text.configure(state='normal')
                self.steps_text.delete('1.0', 'end')
                for s in steps:
                    icon = '✅' if s.get('ok') is True else ('❌' if s.get('ok') is False else '⏳')
                    t = s.get('time', '')
                    name = s.get('name', '')
                    info = s.get('detail', '')
                    line = f'{icon} {name}  {info}  [{t}]\n'
                    self.steps_text.insert('end', line)
                self.steps_text.see('end')
                self.steps_text.configure(state='disabled')

                if done:
                    if pct >= 90:
                        self.title_label.configure(text='✅ 爬取完成!')
                        self.phase_label.configure(foreground='#30d158')
                    else:
                        self.title_label.configure(text='⚠️ 部分完成')
                        self.phase_label.configure(foreground='#ff6b6b')
                    return  # 停止轮询
        except Exception:
            pass
        self.root.after(POLL_MS, self.poll)


if __name__ == '__main__':
    ProgressWindow()
