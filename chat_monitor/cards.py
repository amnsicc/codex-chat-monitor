"""Non-activating, grouped application reminder cards for Windows."""
import ctypes
import tkinter as tk
from tkinter import ttk


class ReminderCard:
    def __init__(self, root, close):
        self.window = tk.Toplevel(root, takefocus=False)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes('-topmost', True)
        body = ttk.Frame(self.window, padding=12, relief='solid')
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Codex 材料用量提醒 · 试用 / 未校准',
                  font=('Microsoft YaHei UI', 11, 'bold')).pack(anchor='w')
        content = ttk.Frame(body)
        content.pack(fill='both', expand=True, pady=8)
        self.canvas = tk.Canvas(content, width=450, height=80, highlightthickness=0, takefocus=False)
        scrollbar = ttk.Scrollbar(content, orient='vertical', command=self.canvas.yview, takefocus=False)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.text = ttk.Label(self.canvas, wraplength=450, justify='left')
        self.canvas.create_window(0, 0, window=self.text, anchor='nw', width=450)
        ttk.Button(body, text='关闭提示卡（继续监控）', takefocus=False, command=close).pack(anchor='e')

    def show(self, events):
        lines = [f"{e['title']} [{e['chat_id']}]\n{e['level']}% · {e['tokens']} / {e['budget']} token"
                 for e in events]
        self.text.configure(text='\n\n'.join(lines)+'\n每条提示默认8秒自动收起')
        self.window.update_idletasks()
        self.canvas.configure(height=min(self.text.winfo_reqheight(), max(80, self.window.winfo_screenheight()-220)))
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        self.window.update_idletasks()
        width = 500
        height = self.window.winfo_reqheight()
        x = max(0, self.window.winfo_screenwidth()-width-24)
        y = max(0, self.window.winfo_screenheight()-height-70)
        self.window.geometry(f'{width}x{height}+{x}+{y}')
        user = ctypes.windll.user32
        user.GetAncestor.restype = ctypes.c_void_p
        hwnd = user.GetAncestor(ctypes.c_void_p(self.window.winfo_id()), 2)
        get_style = user.GetWindowLongPtrW
        set_style = user.SetWindowLongPtrW
        get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
        get_style.restype = ctypes.c_ssize_t
        set_style.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        set_style.restype = ctypes.c_ssize_t
        # WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW. No focus_set, focus_force or grab.
        set_style(hwnd, -20, get_style(hwnd, -20) | 0x08000000 | 0x00000080)
        self.window.deiconify()
        user.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(-1), x, y, width, height, 0x0010 | 0x0040)

    def close(self):
        self.window.destroy()
