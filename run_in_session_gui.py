"""Run in Session: English Windows distribution."""
from __future__ import annotations
import logging
import os
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
import session_core as backend

class QueueLogHandler(logging.Handler):

    def __init__(self, events: queue.SimpleQueue):
        super().__init__()
        self.events = events
        self.setFormatter(logging.Formatter('%(asctime)s  %(levelname)s  %(message)s', '%H:%M:%S'))

    def emit(self, record: logging.LogRecord) -> None:
        self.events.put(('log', self.format(record)))

class SessionApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.events = queue.SimpleQueue()
        self.busy = False
        self.closing = False
        self.closed = False
        self.stop_wait = threading.Event()
        self.mode = tk.StringVar(value='exe')
        self.command = tk.StringVar(value=os.path.join(os.environ.get('SystemRoot', 'C:\\Windows'), 'System32', 'notepad.exe'))
        self.arguments = tk.StringVar()
        self.cwd = tk.StringVar()
        self.desktop = tk.StringVar(value='winsta0\\default')
        self.wait = tk.BooleanVar(value=False)
        self.timeout = tk.StringVar(value='30')
        self.status = tk.StringVar(value='Ready')
        self.selection = tk.StringVar(value='Select a user session from the table.')
        self.session_choice = tk.StringVar()
        self.session_choices = {}
        self.source_choice = tk.StringVar(value='Same as destination')
        self.grant_access = tk.BooleanVar(value=False)
        self.handler = QueueLogHandler(self.events)
        if backend.log.getEffectiveLevel() > logging.INFO:
            backend.log.setLevel(logging.INFO)
        backend.log.addHandler(self.handler)
        self.rows = []
        self.filter_text = tk.StringVar()
        self.only_users = tk.BooleanVar(value=False)
        self.count_text = tk.StringVar(value='Loading sessions…')
        self.ready_text = tk.StringVar(value='Select a destination to continue.')
        self.elapsed = tk.StringVar(value='')
        self.advanced_open = False
        self._wide = None
        self._configure_style()
        root.title('Run in Session')
        root.configure(background='#edf2f8')
        root.geometry(f'{min(1180, root.winfo_screenwidth() - 60)}x{min(900, root.winfo_screenheight() - 100)}')
        root.minsize(640, 480)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        header = ttk.Frame(root, style='Hero.TFrame', padding=(24, 18))
        header.grid(row=0, column=0, sticky='ew')
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text='RUN IN SESSION', style='HeroTitle.TLabel').grid(sticky='w')
        ttk.Label(header, text='Choose a destination. Configure the process. Check the result.', style='HeroText.TLabel', wraplength=560).grid(sticky='w', pady=(5, 0))
        self.badge = ttk.Label(header, text='READY', style='Badge.TLabel', padding=(12, 6))
        self.badge.grid(row=0, column=1, rowspan=2, sticky='e', padx=(12, 0))
        container = ttk.Frame(root)
        container.grid(row=1, column=0, sticky='nsew')
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(container, highlightthickness=0, background='#edf2f8')
        self.canvas.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(container, orient='vertical', command=self.canvas.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=scroll.set)
        self.page = ttk.Frame(self.canvas, padding=18)
        page_window = self.canvas.create_window((0, 0), window=self.page, anchor='nw')
        self.page.columnconfigure(0, weight=1)
        self.page.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self._resize(event.width, page_window))
        root.bind('<FocusIn>', self._show_focus, add='+')
        root.bind('<MouseWheel>', self._wheel, add='+')
        notice = ttk.Label(self.page, text='Launching requires SYSTEM. Simulation does not start a process. Stopping the wait does not terminate the program.', style='Notice.TLabel', wraplength=850, padding=(14, 10))
        notice.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 14))
        self.page.bind('<Configure>', lambda event: notice.configure(wraplength=max(300, event.width - 70)), add='+')
        self.sessions_card = ttk.Frame(self.page, style='Card.TFrame', padding=18)
        sessions = self.sessions_card
        sessions.columnconfigure(0, weight=1)
        ttk.Label(sessions, text='01  Destination', style='CardTitle.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(sessions, textvariable=self.count_text, style='Muted.TLabel').grid(row=1, column=0, sticky='w', pady=(4, 12))
        search = ttk.Frame(sessions, style='Card.TFrame')
        search.grid(row=5, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        search.columnconfigure(0, weight=1)
        ttk.Label(search, text='Search account, ID or station', style='Card.TLabel').grid(sticky='w')
        self.search_entry = ttk.Entry(search, textvariable=self.filter_text)
        self.search_entry.grid(row=1, column=0, sticky='ew', pady=(4, 8))
        self.users_filter = ttk.Checkbutton(search, text='Only sessions with a user', variable=self.only_users, command=self._filter_rows, style='Card.TCheckbutton')
        self.users_filter.grid(row=2, column=0, sticky='w')
        self.tree = ttk.Treeview(sessions, columns=('id', 'user', 'state', 'station'), show='headings', selectmode='browse', height=7)
        for key, title, width in (('id', 'ID', 55), ('user', 'Account', 230), ('state', 'State', 130), ('station', 'Station', 120)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=45, stretch=key != 'id')
        self.tree.grid(row=6, column=0, sticky='nsew', pady=(8, 0))
        self.tree.tag_configure('active', foreground='#116748')
        self.tree.tag_configure('system', foreground='#64748b')
        scrollbar = ttk.Scrollbar(sessions, orient='vertical', command=self.tree.yview)
        scrollbar.grid(row=6, column=1, sticky='ns', pady=(8, 0))
        horizontal = ttk.Scrollbar(sessions, orient='horizontal', command=self.tree.xview)
        horizontal.grid(row=7, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        self.tree.bind('<<TreeviewSelect>>', self._selected)
        ttk.Label(sessions, text='Destination session', style='Card.TLabel').grid(row=2, column=0, columnspan=2, sticky='w', pady=(12, 4))
        self.session_selector = ttk.Combobox(sessions, textvariable=self.session_choice, state='readonly')
        self.session_selector.grid(row=3, column=0, columnspan=2, sticky='ew')
        self.session_selector.bind('<<ComboboxSelected>>', self._choose_session)
        ttk.Label(sessions, textvariable=self.selection, style='Selection.TLabel', wraplength=430, padding=(10, 10)).grid(row=4, column=0, columnspan=2, sticky='ew', pady=(8, 8))
        self.refresh_button = ttk.Button(sessions, text='Refresh sessions  ·  F5', command=self.refresh)
        self.refresh_button.grid(row=8, column=0, sticky='w')
        self.form_card = ttk.Frame(self.page, style='Card.TFrame', padding=18)
        form = self.form_card
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text='02  Configure the process', style='CardTitle.TLabel').grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 14))
        ttk.Label(form, text='Run as account (source session)', style='Card.TLabel').grid(row=1, column=0, columnspan=3, sticky='w', pady=(0, 4))
        self.source_selector = ttk.Combobox(form, textvariable=self.source_choice, state='readonly')
        self.source_selector.grid(row=2, column=0, columnspan=3, sticky='ew', pady=(0, 8))
        self.grant_box = ttk.Checkbutton(form, variable=self.grant_access, style='Card.TCheckbutton', text='Allow source logon to access destination desktop')
        self.grant_box.grid(row=3, column=0, columnspan=3, sticky='w')
        ttk.Label(form, text='Cross-session access shares this desktop with the source logon. The grant may remain until destination logoff. Run the SYSTEM GUI in the destination session.', style='Muted.TLabel', wraplength=390).grid(row=4, column=0, columnspan=3, sticky='w', pady=(4, 12))
        choices = ttk.Frame(form, style='Card.TFrame')
        choices.grid(row=5, column=0, columnspan=3, sticky='w', pady=(0, 10))
        ttk.Radiobutton(choices, text='Executable', variable=self.mode, value='exe', style='Card.TRadiobutton', command=self._mode_changed).pack(side='left')
        ttk.Radiobutton(choices, text='Full command', variable=self.mode, value='cmd', style='Card.TRadiobutton', command=self._mode_changed).pack(side='left', padx=12)
        self._entry(form, 6, 'Executable / command', self.command)
        self.browse_exe = ttk.Button(form, text='Browse…', command=self._browse_executable)
        self.browse_exe.grid(row=7, column=2, sticky='e', padx=(8, 0))
        self.arguments_entry = self._entry(form, 8, 'Arguments', self.arguments)
        ttk.Label(form, text='Arguments are excluded from the activity log.', style='Muted.TLabel', wraplength=390).grid(row=10, column=0, columnspan=3, sticky='w', pady=(0, 10))
        self.advanced_button = ttk.Button(form, text='+  Advanced options', command=self._toggle_advanced)
        self.advanced_button.grid(row=11, column=0, columnspan=3, sticky='w', pady=8)
        self.advanced = ttk.Frame(form, style='Card.TFrame')
        self.advanced.columnconfigure(1, weight=1)
        self._entry(self.advanced, 0, 'Working directory', self.cwd)
        ttk.Button(self.advanced, text='Browse…', command=self._browse).grid(row=1, column=2, padx=(8, 0))
        self._entry(self.advanced, 2, 'Desktop', self.desktop)
        options = ttk.Frame(form, style='Card.TFrame')
        options.grid(row=13, column=0, columnspan=3, sticky='ew', pady=(8, 0))
        ttk.Checkbutton(options, text='Wait for process exit', variable=self.wait, style='Card.TCheckbutton', command=self._wait_changed).grid(row=0, column=0, columnspan=2, sticky='w')
        ttk.Label(options, text='Timeout in seconds', style='Card.TLabel').grid(row=1, column=0, sticky='w', pady=8)
        self.timeout_entry = ttk.Entry(options, textvariable=self.timeout, width=10, state='disabled')
        self.timeout_entry.grid(row=1, column=1, sticky='w', padx=12)
        ttk.Label(form, textvariable=self.ready_text, style='Hint.TLabel', wraplength=390, padding=(10, 10)).grid(row=14, column=0, columnspan=3, sticky='ew', pady=(12, 0))
        results = ttk.Frame(self.page, style='Card.TFrame', padding=18)
        self.results_card = results
        results.columnconfigure(0, weight=1)
        ttk.Label(results, text='03  Activity and results', style='CardTitle.TLabel').grid(row=0, column=0, sticky='w')
        tools = ttk.Frame(results, style='Card.TFrame')
        tools.grid(row=0, column=1, sticky='e')
        ttk.Button(tools, text='Copy log', command=self._copy_log).pack(side='left', padx=4)
        ttk.Button(tools, text='Clear', command=self._clear_log).pack(side='left')
        self.output = ScrolledText(results, height=9, wrap='word', state='disabled', font=('Consolas', 10), background='#101c30', foreground='#dbe7fa', insertbackground='white', relief='flat', padx=12, pady=12)
        self.output.grid(row=1, column=0, columnspan=2, sticky='nsew', pady=(12, 0))
        for tag, color in (('error', '#ffb6b6'), ('warning', '#ffd68b'), ('success', '#99e1bf')):
            self.output.tag_configure(tag, foreground=color)
        actions = ttk.Frame(root, padding=(20, 12), style='Card.TFrame')
        actions.grid(row=2, column=0, sticky='ew')
        actions.columnconfigure(0, weight=1)
        ttk.Label(actions, textvariable=self.status, style='Card.TLabel', wraplength=550).grid(row=0, column=0, columnspan=4, sticky='ew', pady=(0, 8))
        self.progress = ttk.Progressbar(actions, mode='indeterminate', length=85)
        self.progress.grid(row=1, column=0, sticky='w')
        ttk.Label(actions, textvariable=self.elapsed, style='Muted.TLabel').grid(row=2, column=0, sticky='w', pady=(3, 0))
        self.stop_button = ttk.Button(actions, text='Stop waiting', state='disabled', command=self.stop_wait.set)
        self.stop_button.grid(row=1, column=1, padx=8)
        self.simulate_button = ttk.Button(actions, text='Simulate', command=lambda: self.execute(True))
        self.simulate_button.grid(row=1, column=2, padx=(0, 8))
        self.run_button = ttk.Button(actions, text='Launch process', style='Primary.TButton', command=lambda: self.execute(False))
        self.run_button.grid(row=1, column=3)
        self._buttons = (self.refresh_button, self.simulate_button, self.run_button)
        for variable in (self.command, self.desktop, self.timeout, self.wait, self.grant_access):
            variable.trace_add('write', lambda *_: self._update_readiness())
        self.source_choice.trace_add('write', self._source_changed)
        self.filter_text.trace_add('write', lambda *_: self._filter_rows())
        root.bind('<Control-f>', lambda event: self.search_entry.focus_set())
        root.bind('<Control-Return>', lambda event: self.execute(True))
        self._resize(1100, page_window)
        root.bind('<F5>', lambda event: self.refresh())
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_id = root.after(80, self._drain)
        self.refresh()

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background='#edf2f8', foreground='#17263e')
        style.configure('TFrame', background='#edf2f8')
        style.configure('Card.TFrame', background='#ffffff')
        style.configure('Card.TLabel', background='#ffffff', foreground='#17263e')
        style.configure('CardTitle.TLabel', background='#ffffff', foreground='#12233d', font=('Segoe UI', 13, 'bold'))
        style.configure('Muted.TLabel', background='#ffffff', foreground='#52647a', font=('Segoe UI', 9))
        style.configure('Selection.TLabel', background='#edf4ff', foreground='#174988')
        style.configure('Hint.TLabel', background='#f1f5fa', foreground='#344a65')
        style.configure('Notice.TLabel', background='#e3ecf9', foreground='#294c7b')
        style.configure('Hero.TFrame', background='#12233d')
        style.configure('HeroTitle.TLabel', background='#12233d', foreground='#ffffff', font=('Segoe UI', 22, 'bold'))
        style.configure('HeroText.TLabel', background='#12233d', foreground='#c4d3e9', font=('Segoe UI', 10))
        style.configure('Badge.TLabel', background='#254366', foreground='#e5efff', font=('Segoe UI', 9, 'bold'))
        style.configure('ErrorBadge.TLabel', background='#6c2935', foreground='#ffffff', font=('Segoe UI', 9, 'bold'))
        style.configure('SuccessBadge.TLabel', background='#1c5849', foreground='#ffffff', font=('Segoe UI', 9, 'bold'))
        style.configure('WarningBadge.TLabel', background='#715322', foreground='#ffffff', font=('Segoe UI', 9, 'bold'))
        style.configure('TButton', padding=(12, 8), background='#e9eff7', foreground='#18324f', borderwidth=0)
        style.map('TButton', background=[('disabled', '#eef1f5'), ('pressed', '#c7d8ec'), ('active', '#d6e4f5')], foreground=[('disabled', '#738397')], bordercolor=[('focus', '#2563eb')])
        style.configure('Primary.TButton', background='#215bd8', foreground='#ffffff', font=('Segoe UI', 10, 'bold'))
        style.map('Primary.TButton', background=[('disabled', '#cbd5e1'), ('pressed', '#163f9d'), ('active', '#1749b7')], foreground=[('disabled', '#4b5d75'), ('!disabled', '#ffffff')])
        style.configure('TEntry', padding=8, fieldbackground='#f7f9fd', bordercolor='#c5d1df', lightcolor='#c5d1df', darkcolor='#c5d1df')
        style.map('TEntry', bordercolor=[('focus', '#215bd8')], fieldbackground=[('disabled', '#edf1f6')])
        for name in ('Card.TCheckbutton', 'Card.TRadiobutton'):
            style.configure(name, background='#ffffff', foreground='#253d58', padding=3)
            style.map(name, background=[('active', '#edf4ff')])
        style.configure('Treeview', background='#ffffff', fieldbackground='#ffffff', foreground='#263f5d', borderwidth=0, rowheight=max(34, tkfont.nametofont('TkDefaultFont').metrics('linespace') + 12))
        style.configure('Treeview.Heading', background='#edf2f9', foreground='#52647a', font=('Segoe UI', 9, 'bold'), padding=8)
        style.map('Treeview', background=[('selected', '#dceaff')], foreground=[('selected', '#143e79')])
        style.configure('Horizontal.TProgressbar', background='#2868e0', troughcolor='#e8eef7', borderwidth=0)

    def _resize(self, width: int, page_window: int) -> None:
        self.canvas.itemconfigure(page_window, width=width)
        wide = width >= 1040
        if wide == self._wide:
            return
        self._wide = wide
        self.page.columnconfigure(0, weight=1, uniform='cards' if wide else '')
        self.page.columnconfigure(1, weight=1 if wide else 0, uniform='cards' if wide else '')
        if wide:
            self.sessions_card.grid(row=1, column=0, sticky='nsew', padx=(0, 8), pady=(0, 14))
            self.form_card.grid(row=1, column=1, sticky='nsew', padx=(8, 0), pady=(0, 14))
            self.results_card.grid(row=2, column=0, columnspan=2, sticky='ew')
        else:
            self.sessions_card.grid(row=1, column=0, sticky='ew', padx=0, pady=(0, 14))
            self.form_card.grid(row=2, column=0, sticky='ew', padx=0, pady=(0, 14))
            self.results_card.grid(row=3, column=0, columnspan=1, sticky='ew')

    def _wheel(self, event) -> None:
        if event.widget == self.tree or str(event.widget).startswith(str(self.output)):
            return
        self.canvas.yview_scroll(-int(event.delta / 120), 'units')

    def _toggle_advanced(self) -> None:
        self.advanced_open = not self.advanced_open
        if self.advanced_open:
            self.advanced.grid(row=12, column=0, columnspan=3, sticky='ew')
        else:
            self.advanced.grid_remove()
        self.advanced_button.configure(text='−  Advanced options' if self.advanced_open else '+  Advanced options')

    def _filter_rows(self) -> None:
        if not hasattr(self, 'tree') or self.busy:
            return
        previous = self.tree.selection()
        query = self.filter_text.get().strip().casefold()
        shown = [row for row in self.rows if (not query or query in ' '.join(map(str, row)).casefold()) and (not self.only_users.get() or row[1] not in ('-', '—', '[unreadable]'))]
        self.tree.delete(*self.tree.get_children())
        for row in shown:
            tag = 'active' if row[2] == 'Active' else 'system' if row[1] in ('-', '—') else ''
            self.tree.insert('', 'end', iid=str(row[0]), values=row, tags=(tag,))
        if previous and self.tree.exists(previous[0]):
            self.tree.selection_set(previous[0])
        self.count_text.set(f'{len(shown)} of {len(self.rows)} sessions' if shown else 'No results · change your filters' if self.rows else 'No sessions available')
        self._selected()

    def _sync_session_choices(self) -> None:
        self.session_choices = {f'ID {row[0]} | {row[1]} | {row[2]} | {row[3]}': str(row[0]) for row in self.rows if row[1] not in ('-', '—', '[unreadable]') and row[2] in ('Active', 'Connected', 'Disconnected') and (int(row[0]) > 0)}
        self.session_selector.configure(values=tuple(self.session_choices))
        self.source_selector.configure(values=('Same as destination', *self.session_choices))
        self.grant_access.set(False)

    def _choose_session(self, event=None) -> None:
        if self.busy or self.closing:
            return
        session_id = self.session_choices.get(self.session_choice.get())
        if session_id is None:
            return
        if not self.tree.exists(session_id):
            self.filter_text.set('')
            self._filter_rows()
        if self.tree.exists(session_id):
            self.tree.selection_set(session_id)
            self.tree.see(session_id)
            self._selected()

    def _update_readiness(self) -> bool:
        if not hasattr(self, 'run_button'):
            return False
        selected = self.tree.selection()
        reason = ''
        if not selected:
            reason = 'Select a session in the table.'
        else:
            row = self.tree.item(selected[0], 'values')
            if row[1] in ('-', '—', '[unreadable]'):
                reason = 'The destination must have a readable, logged-on user.'
            elif row[2] not in ('Active', 'Connected', 'Disconnected'):
                reason = 'This session is not available for launching.'
        source_id = None
        if self.source_choice.get() != 'Same as destination':
            source_id = self.session_choices.get(self.source_choice.get())
            if source_id is None:
                reason = 'Source session is no longer available. Select a source account again.'
        if not reason and (not self.command.get().strip()):
            reason = 'Enter an executable or command.'
        if not reason and (not self.desktop.get().strip()):
            reason = 'Enter a desktop in advanced options.'
        if not reason and self.wait.get():
            try:
                value = float(self.timeout.get().replace(',', '.'))
                if not 0 <= value < 4294967.295:
                    raise ValueError
            except ValueError:
                reason = 'Enter a numeric timeout from 0 to less than 4294967.295 seconds.'
        ready = not reason
        self.ready_text.set(reason or 'Ready to simulate. Permissions will be checked at launch.')
        state = 'normal' if ready and (not self.busy) and (not self.closing) else 'disabled'
        self.simulate_button.configure(state=state)
        self.run_button.configure(state=state)
        if ready and source_id is not None and selected and (str(source_id) != selected[0]):
            source_label = self.source_choice.get()
            self.ready_text.set(f'Run as {source_label}. Display in session {selected[0]}.' + (' Desktop access consent enabled.' if self.grant_access.get() else ' Enable desktop access consent for actual launch.'))
            if not self.grant_access.get():
                self.run_button.configure(state='disabled')
        return ready

    def _copy_log(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.output.get('1.0', 'end-1c'))
        if not self.busy:
            self.status.set('Log copied to the clipboard.')

    def _clear_log(self) -> None:
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.configure(state='disabled')

    def _entry(self, parent, row: int, label: str, variable: tk.StringVar) -> ttk.Entry:
        ttk.Label(parent, text=label, style='Card.TLabel').grid(row=row, column=0, columnspan=3, sticky='w', pady=(8, 4))
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row + 1, column=0, columnspan=2, sticky='ew', pady=(0, 6))
        return entry

    def _browse(self) -> None:
        folder = filedialog.askdirectory(parent=self.root, title='Working directory')
        if folder:
            self.cwd.set(folder)

    def _wait_changed(self) -> None:
        self.timeout_entry.configure(state='normal' if self.wait.get() else 'disabled')

    def _selected(self, event=None) -> None:
        items = self.tree.selection()
        if self.busy and hasattr(self, 'operation_selection') and (items != self.operation_selection):
            self.tree.selection_set(self.operation_selection)
            return
        if not self.busy and getattr(self, '_consent_destination', None) != items:
            self._consent_destination = items
            self.grant_access.set(False)
        if items:
            values = self.tree.item(items[0], 'values')
            self.session_choice.set(next((label for label, sid in self.session_choices.items() if sid == str(values[0])), ''))
            self.selection.set(f'Session {values[0]}  ·  {values[1]}\n{values[2]}  /  {values[3]}')
            if not self.busy:
                self.status.set(f'Destination: session {values[0]} · {values[1]}')
        else:
            self.session_choice.set('')
            self.selection.set('No destination selected.')
        self._update_readiness()

    def _source_changed(self, *args) -> None:
        self.grant_access.set(False)
        self._update_readiness()

    def _start(self, action, status: str) -> None:
        if self.busy or self.closing:
            return
        self.stop_wait.clear()
        self.busy = True
        self.operation_selection = self.tree.selection()
        self.search_entry.configure(state='disabled')
        self.session_selector.configure(state='disabled')
        self.source_selector.configure(state='disabled')
        self.grant_box.configure(state='disabled')
        self.users_filter.configure(state='disabled')
        self.started_at = time.monotonic()
        self.badge.configure(text='IN PROGRESS', style='Badge.TLabel')
        self.status.set(status)
        for button in self._buttons:
            button.configure(state='disabled')
        self.progress.start(12)
        events = self.events

        def work():
            try:
                result = action()
                events.put(('done', result))
            except Exception as exc:
                events.put(('error', str(exc) if isinstance(exc, backend.SessionError) else f'Unexpected error ({type(exc).__name__}).'))
        self.worker = threading.Thread(target=work, daemon=False, name='session-worker')
        self.worker.start()

    def refresh(self) -> None:

        def fetch():
            return backend.session_rows()
        self._start(fetch, 'Refreshing sessions…')

    def execute(self, dry_run: bool) -> None:
        if self.busy or self.closing:
            return
        if not self._update_readiness():
            self.status.set(self.ready_text.get())
            return
        try:
            selected = self.tree.selection()
            if not selected:
                raise backend.SessionError('Select a user session in the table.')
            session_id = int(selected[0])
            source_session_id = None if self.source_choice.get() == 'Same as destination' else int(self.session_choices[self.source_choice.get()])
            identity_id = session_id if source_session_id is None else source_session_id
            expected_source_account = next((row[1] for row in self.rows if int(row[0]) == identity_id))
            grant_desktop_access = self.grant_access.get()
            if not dry_run and source_session_id is not None and (source_session_id != session_id) and (not grant_desktop_access):
                raise backend.SessionError('Enable desktop access consent before launching across sessions.')
            command, cwd, desktop = (self.command.get(), self.cwd.get().strip() or None, self.desktop.get())
            wait = self.wait.get()
            try:
                timeout = float(self.timeout.get().replace(',', '.')) if wait else None
            except ValueError:
                raise backend.SessionError('Enter a numeric timeout in seconds.') from None
            executable = command if self.mode.get() == 'exe' else None
            legacy = command if executable is None else None
            arguments = self.arguments.get() if executable is not None else ''
        except backend.SessionError as exc:
            self.status.set('Check your input')
            messagebox.showerror('Input needs attention', str(exc), parent=self.root)
            return
        stop_wait, events = (self.stop_wait, self.events)

        def run():
            return backend.run_in_session(session_id, legacy, desktop, cwd, wait, timeout, dry_run, executable=executable, arguments=arguments, stop_wait=stop_wait, notify=lambda pid: events.put(('started', (pid, wait))), source_session_id=source_session_id, grant_desktop_access=grant_desktop_access, expected_source_account=expected_source_account)
        self._append(f"\n{('SIMULATION' if dry_run else 'LAUNCH')} · Session {session_id}\n")
        self._start(run, 'Simulating…' if dry_run else 'Launching / waiting for the process…')

    def _append(self, text: str) -> None:
        follow_tail = self.output.yview()[1] >= 0.98
        self.output.configure(state='normal')
        tag = 'error' if 'ERROR' in text or 'ERROR' in text else 'warning' if 'WARNING' in text or 'Timeout' in text else 'success' if 'completed' in text or 'code 0' in text else ''
        self.output.insert('end', text, (tag,) if tag else ())
        if int(self.output.index('end-1c').split('.')[0]) > 2000:
            self.output.delete('1.0', '500.0')
        if follow_tail:
            self.output.see('end')
        self.output.configure(state='disabled')

    def _drain(self) -> None:
        if self.busy:
            self.elapsed.set(f'Elapsed time: {int(time.monotonic() - self.started_at)} s')
        for _ in range(100):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                self._append(value + '\n')
                continue
            if kind == 'started':
                pid, waiting = value
                self.status.set(f'PID {pid} launched' + (' · Waiting' if waiting else ''))
                if waiting and (not self.closing):
                    self.stop_button.configure(state='normal')
                continue
            self.busy = False
            self.search_entry.configure(state='normal')
            self.session_selector.configure(state='readonly')
            self.source_selector.configure(state='readonly')
            self.grant_box.configure(state='normal')
            self.users_filter.configure(state='normal')
            self.stop_button.configure(state='disabled')
            self.progress.stop()
            self.progress.configure(value=0)
            for button in self._buttons:
                button.configure(state='normal')
            self.badge.configure(text='ERROR' if kind == 'error' else 'READY', style='ErrorBadge.TLabel' if kind == 'error' else 'Badge.TLabel')
            if kind == 'error':
                self.status.set('Operation failed · see the log')
                self._append('ERROR: ' + value + '\n')
            elif isinstance(value, list):
                self.rows = value
                self._sync_session_choices()
                self._filter_rows()
                self.elapsed.set('')
                self.status.set(f'{len(value)} sessions found' if value else 'No sessions available')
            else:
                message = self._result_message(value) if isinstance(value, backend.RunResult) else str(value)
                self.status.set(message)
                self._append(message + '\n')
                if isinstance(value, backend.RunResult):
                    self._show_result_badge(value)
            self._update_readiness()
            if self.closing:
                self._destroy()
                return
        self.poll_id = self.root.after(80, self._drain)

    def _show_focus(self, event) -> None:
        widget = event.widget
        if str(widget).startswith(str(self.canvas) + '.'):
            self.root.update_idletasks()
            top = widget.winfo_rooty() - self.canvas.winfo_rooty() + self.canvas.canvasy(0)
            bottom = top + widget.winfo_height()
            view_top = self.canvas.canvasy(0)
            height = max(1, self.canvas.bbox('all')[3])
            if top < view_top:
                self.canvas.yview_moveto(max(0, top - 10) / height)
            elif bottom > view_top + self.canvas.winfo_height():
                self.canvas.yview_moveto((bottom - self.canvas.winfo_height() + 10) / height)

    def _mode_changed(self) -> None:
        explicit = self.mode.get() == 'exe'
        self.arguments_entry.configure(state='normal' if explicit else 'disabled')
        self.browse_exe.configure(state='normal' if explicit else 'disabled')

    def _browse_executable(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title='Select executable', filetypes=(('Executables', '*.exe'), ('All files', '*.*')))
        if path:
            self.command.set(os.path.normpath(path))

    @staticmethod
    def _result_message(result: backend.RunResult) -> str:
        return {'simulated': 'Simulation completed. No process launched; see the limitations in the log.', 'launched': f'Process launched · PID {result.pid}', 'exited': f'Process exited · PID {result.pid} · code {result.exit_code}', 'timeout': f'Timeout · PID {result.pid}: no termination requested; monitoring has ended.', 'detached': f'Wait stopped · PID {result.pid}: no termination requested.', 'cancelled': 'Launch cancelled before calling Windows.'}[result.status]

    def _show_result_badge(self, result: backend.RunResult) -> None:
        labels = {'simulated': 'SIMULATED', 'launched': 'LAUNCHED', 'exited': 'EXITED', 'timeout': 'TIMEOUT', 'detached': 'WAIT STOPPED', 'cancelled': 'CANCELLED'}
        text = labels[result.status]
        style = 'SuccessBadge.TLabel'
        if result.status in ('timeout', 'detached', 'cancelled'):
            style = 'WarningBadge.TLabel'
        if result.status == 'exited' and result.exit_code != 0:
            text, style = (f'CODE {result.exit_code}', 'ErrorBadge.TLabel')
        self.badge.configure(text=text, style=style)

    def close(self) -> None:
        if self.closing:
            return
        if self.busy:
            if not messagebox.askyesno('Operation in progress', 'Close after the Windows operation completes? Waiting will stop, but an already launched process will not be terminated.', parent=self.root):
                return
            self.closing = True
            self.stop_wait.set()
            self.status.set('Closing after the Windows operation completes…')
            self.stop_button.configure(state='disabled')
            return
        self._destroy()

    def _destroy(self) -> None:
        if self.closed:
            return
        if self.worker.is_alive():
            self.root.after(20, self._destroy)
            return
        self.closed = True
        backend.log.removeHandler(self.handler)
        self.root.after_cancel(self.poll_id)
        self.root.destroy()

def launch_gui() -> int:
    root = tk.Tk()
    SessionApp(root)
    root.mainloop()
    return 0
if __name__ == '__main__':
    raise SystemExit(launch_gui())
