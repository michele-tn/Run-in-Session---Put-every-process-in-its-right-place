"""Run in Session: English Windows distribution."""
from __future__ import annotations
import argparse
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import time
import uuid
import win32com.client
import session_core as core
PROGRAMS = {'run_in_session.py': ('--gui',), 'run_in_session_gui.py': ()}
PROJECT_DIR = Path(__file__).resolve().parent
CREATE_BREAKAWAY_FROM_JOB = 16777216
WORKER_ERRORS = {10: 'SYSTEM/SeTcbPrivilege is unavailable in the helper.', 11: 'Interactive session unavailable or has no user.', 12: 'Python files or local dependencies are unavailable.', 13: 'Cannot prepare the SYSTEM token for the selected session.', 14: 'Process creation failed: check desktop permissions, the interpreter and Windows job restrictions.'}

def program_path(name: str) -> Path:
    if name not in PROGRAMS:
        raise core.SessionError('Program not allowed. Choose one of the two listed files.')
    path = PROJECT_DIR / name
    if not path.is_file():
        raise core.SessionError(f'Missing file: {path}')
    for dependency in ('session_core.py', 'run_in_session_gui.py'):
        if not (PROJECT_DIR / dependency).is_file():
            raise core.SessionError(f'Missing dependency: {dependency}')
    return path

def current_session_id() -> int:
    token = core.win32security.OpenProcessToken(core.win32api.GetCurrentProcess(), core.win32con.TOKEN_QUERY)
    try:
        return core.win32security.GetTokenInformation(token, core.win32security.TokenSessionId)
    finally:
        token.Close()

def is_admin() -> bool:
    sid = core.win32security.CreateWellKnownSid(core.win32security.WinBuiltinAdministratorsSid, None)
    return bool(core.win32security.CheckTokenMembership(None, sid))

def choose_program() -> str | None:
    print('\nINTERACTIVE SYSTEM LAUNCH\n')
    print('  1. run_in_session.py       (main entry point, --gui)')
    print('  2. run_in_session_gui.py   (direct GUI)')
    print('  0. Exit\n')
    print('Both entry points open the same interface.\n')
    while True:
        value = input('Choose 1, 2 or 0: ').strip()
        if value == '0':
            return None
        if value in ('1', '2'):
            return tuple(PROGRAMS)[int(value) - 1]
        print('Invalid selection.')

def choose_session() -> int | None:
    rows = [row for row in core.session_rows() if int(row[0]) > 0 and row[1] not in ('-', '—', '[unreadable]') and (row[2] in ('Active', 'Connected', 'Disconnected'))]
    if not rows:
        raise core.SessionError('No user sessions available. Log on a user and try again.')
    print('\nDESTINATION SESSION\n')
    print(core.format_table(('ID', 'Account', 'State', 'Station'), rows))
    allowed = {int(row[0]) for row in rows}
    while True:
        value = input('\nDestination session ID for the GUI (0 = exit): ').strip()
        if value == '0':
            return None
        try:
            session_id = int(value)
        except ValueError:
            session_id = -1
        if session_id in allowed:
            return session_id
        print('Choose a listed session ID, not the row number.')

def system_worker(name: str, session_id: int) -> int:
    try:
        core.ensure_tcb_privilege()
    except (core.SessionError, core.pywintypes.error):
        return 10
    try:
        core.validate_session(session_id)
        if session_id <= 0:
            return 11
    except (core.SessionError, core.pywintypes.error):
        return 11
    try:
        script = program_path(name)
    except core.SessionError:
        return 12
    with ExitStack() as resources:
        try:
            token = core.win32security.OpenProcessToken(core.win32api.GetCurrentProcess(), core.win32con.TOKEN_ALL_ACCESS)
            resources.callback(token.Close)
            primary = core.win32security.DuplicateTokenEx(token, core.win32security.SecurityImpersonation, core.win32con.MAXIMUM_ALLOWED, core.win32security.TokenPrimary, None)
            resources.callback(primary.Close)
            core.win32security.SetTokenInformation(primary, core.win32security.TokenSessionId, session_id)
            environment = core.win32profile.CreateEnvironmentBlock(primary, False)
        except core.pywintypes.error:
            return 13
        startup = core.win32process.STARTUPINFO()
        startup.lpDesktop = 'winsta0\\default'
        command = subprocess.list2cmdline([sys.executable, str(script), *PROGRAMS[name]])
        try:
            process, thread, _, _ = core.win32process.CreateProcessAsUser(primary, sys.executable, command, None, None, False, core.win32con.CREATE_UNICODE_ENVIRONMENT | CREATE_BREAKAWAY_FROM_JOB, environment, str(PROJECT_DIR), startup)
        except core.pywintypes.error:
            return 14
        resources.callback(process.Close)
        resources.callback(thread.Close)
    return 0

def schedule_program(name: str, session_id: int, timeout: float=45) -> None:
    program_path(name)
    if session_id <= 0:
        raise core.SessionError('Choose an interactive session other than 0.')
    core.validate_session(session_id)
    if not is_admin():
        raise core.SessionError('Open PowerShell as administrator and run this launcher again.')
    service = win32com.client.Dispatch('Schedule.Service')
    service.Connect()
    folder = service.GetFolder('\\')
    definition = service.NewTask(0)
    definition.RegistrationInfo.Description = 'Interactive Run in Session launch as SYSTEM, without PsExec.'
    definition.Principal.UserId = 'S-1-5-18'
    definition.Principal.LogonType = 5
    definition.Principal.RunLevel = 1
    definition.Settings.Enabled = True
    definition.Settings.AllowDemandStart = True
    definition.Settings.DisallowStartIfOnBatteries = False
    definition.Settings.StopIfGoingOnBatteries = False
    definition.Settings.ExecutionTimeLimit = 'PT1M'
    action = definition.Actions.Create(0)
    action.Path = sys.executable
    action.Arguments = subprocess.list2cmdline([str(Path(__file__).resolve()), '--worker', '--program', name, '--session', str(session_id)])
    action.WorkingDirectory = str(PROJECT_DIR)
    task_name = 'RunInSession-Launch-' + uuid.uuid4().hex
    task = folder.RegisterTaskDefinition(task_name, definition, 2, 'S-1-5-18', None, 5, 'D:P(A;;FA;;;SY)(A;;FA;;;BA)')
    print(f'Temporary task: {task_name}')
    finished = False
    try:
        task.Run('')
        deadline = time.monotonic() + timeout
        while True:
            if task.GetInstances(0).Count == 0 and task.LastTaskResult not in (267009, 267011):
                finished = True
                break
            if time.monotonic() >= deadline:
                raise core.SessionError(f'Outcome not yet available. Do not automatically retry. Check task {task_name} in Task Scheduler.')
            time.sleep(0.2)
        result = task.LastTaskResult
        if result:
            detail = WORKER_ERRORS.get(result, 'Interpreter or Task Scheduler error.')
            raise core.SessionError(f'Launch failed ({result}): {detail}')
        print(f'Process created as SYSTEM in session {session_id}: {name}')
        print('Process creation does not guarantee that the GUI has finished loading.')
    finally:
        if finished:
            try:
                folder.DeleteTask(task_name, 0)
            except core.pywintypes.com_error:
                print(f'Cleanup failed: manually remove task {task_name}.')
        else:
            print(f'Task retained for diagnostics: {task_name}. No recurring trigger configured.')

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--program', choices=tuple(PROGRAMS), help='Skip the menu and select the file')
    parser.add_argument('--session', type=int, help='Interactive session ID; omit to show a selection menu')
    parser.add_argument('--dry-run', action='store_true', help='Show the selection without creating a task')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.worker:
            if args.program is None or args.session is None or args.dry_run:
                parser.error('The helper requires an explicit program and session.')
            return system_worker(args.program, args.session)
        name = args.program or choose_program()
        if name is None:
            return 0
        script = program_path(name)
        session_id = choose_session() if args.session is None else args.session
        if session_id is None:
            return 0
        if session_id <= 0:
            raise core.SessionError('Specify --session with an interactive ID other than 0.')
        if args.dry_run:
            print(f'SIMULATION: {script} · SYSTEM account · session {session_id}')
            print('No task created. Privileges and desktop access were not checked.')
            return 0
        schedule_program(name, session_id)
        return 0
    except (core.SessionError, core.pywintypes.error, core.pywintypes.com_error) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print('\nRequest interrupted; a previously requested launch may have occurred.')
        return 130
if __name__ == '__main__':
    raise SystemExit(main())
