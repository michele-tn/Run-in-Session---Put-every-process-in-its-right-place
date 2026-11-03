"""Run in Session: English Windows distribution."""
from __future__ import annotations
from contextlib import ExitStack
import logging
from dataclasses import dataclass
import math
import os
import sys
import time
from typing import Literal
if sys.platform != 'win32':
    sys.exit('Error: this application requires Windows.')
try:
    import win32ts
    import win32security
    import win32process
    import win32con
    import win32profile
    import win32api
    import win32event
    import win32service
    import pywintypes
except ImportError as exc:
    sys.exit(f'Cannot load pywin32: {exc}\nInstall the dependency with: "{sys.executable}" -m pip install --upgrade pywin32')
log = logging.getLogger('run_in_session')
STATE_NAMES = {win32ts.WTSActive: 'Active', win32ts.WTSConnected: 'Connected', win32ts.WTSConnectQuery: 'ConnectQuery', win32ts.WTSShadow: 'Shadow', win32ts.WTSDisconnected: 'Disconnected', win32ts.WTSIdle: 'Idle', win32ts.WTSListen: 'Listen', win32ts.WTSReset: 'Reset', win32ts.WTSDown: 'Down', win32ts.WTSInit: 'Init'}

@dataclass(frozen=True)
class RunResult:
    status: Literal['simulated', 'launched', 'exited', 'timeout', 'detached', 'cancelled']
    pid: int | None = None
    exit_code: int | None = None

class SessionError(Exception):
    pass

def ensure_tcb_privilege():
    try:
        h_token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY)
    except pywintypes.error as e:
        raise SessionError(f'Cannot open the process token: {e.strerror}')
    try:
        user_sid = win32security.GetTokenInformation(h_token, win32security.TokenUser)[0]
        if win32security.ConvertSidToStringSid(user_sid) != 'S-1-5-18':
            raise SessionError('Launching requires LocalSystem (SYSTEM); administrator rights alone are insufficient.')
        luid = win32security.LookupPrivilegeValue(None, win32security.SE_TCB_NAME)
        win32security.AdjustTokenPrivileges(h_token, False, [(luid, win32con.SE_PRIVILEGE_ENABLED)])
        if win32api.GetLastError() == 1300:
            raise SessionError('The process does not have SeTcbPrivilege. Run as SYSTEM; administrator rights alone are insufficient.')
    except pywintypes.error as e:
        raise SessionError(f'Cannot enable SeTcbPrivilege: {e.strerror}') from e
    finally:
        h_token.Close()

def list_sessions(quiet=False):
    try:
        sessions = win32ts.WTSEnumerateSessions(None, 1, 0)
    except pywintypes.error as e:
        raise SessionError(f'Cannot enumerate sessions: {e.strerror}')
    if not quiet:
        rows = [(str(s['SessionId']), s['WinStationName'] or '-', STATE_NAMES.get(s['State'], str(s['State'])), query_account(s['SessionId']) or '-') for s in sessions]
        print('\nWINDOWS SESSIONS\n')
        print(format_table(('ID', 'Station', 'State', 'User'), rows))
        print(f'\nSessions found: {len(rows)}\n')
    return sessions

def format_table(headers, rows):
    widths = [max((len(row[i]) for row in [headers, *rows])) for i in range(len(headers))]
    lines = ['  '.join((cell.ljust(width) for cell, width in zip(headers, widths)))]
    lines.append('  '.join(('-' * width for width in widths)))
    lines.extend(('  '.join((cell.ljust(width) for cell, width in zip(row, widths))) for row in rows))
    return '\n'.join(lines)

def validate_options(cmd, cwd=None, desktop='winsta0\\default', wait=False, timeout=None):
    if not cmd or not cmd.strip():
        raise SessionError('The command must not be empty.')
    if not desktop or not desktop.strip():
        raise SessionError('The desktop must not be empty.')
    if '\x00' in desktop or (cwd and '\x00' in cwd):
        raise SessionError('Desktop and directory must not contain null characters.')
    if cwd and (not os.path.isdir(cwd)):
        raise SessionError(f'Working directory does not exist: {cwd}')
    if timeout is not None:
        if not wait:
            raise SessionError('Timeout requires the wait option (--wait).')
        if not math.isfinite(timeout) or not 0 <= timeout < 4294967.295:
            raise SessionError('Timeout must be finite, zero or positive, and less than 4294967.295 seconds.')

def _query_username(session_id):
    try:
        return win32ts.WTSQuerySessionInformation(None, session_id, win32ts.WTSUserName)
    except pywintypes.error:
        return None

def query_account(session_id):
    try:
        user = win32ts.WTSQuerySessionInformation(None, session_id, win32ts.WTSUserName)
        domain = win32ts.WTSQuerySessionInformation(None, session_id, win32ts.WTSDomainName)
    except pywintypes.error as exc:
        raise SessionError(f'Cannot read the account for session {session_id} (code {exc.winerror}).') from exc
    return f'{domain}\\{user}' if domain and user else user

def session_rows():
    rows = []
    for session in list_sessions(quiet=True):
        sid = session['SessionId']
        try:
            account = query_account(sid) or '-'
        except SessionError:
            account = '[unreadable]'
        rows.append((str(sid), account, STATE_NAMES.get(session['State'], str(session['State'])), session['WinStationName'] or '-'))
    return rows

def find_session_by_user(username):
    username = username.strip().casefold()
    matches = []
    for s in list_sessions(quiet=True):
        sid = s['SessionId']
        user = query_account(sid)
        candidate = user if '\\' in username else user.rsplit('\\', 1)[-1]
        if user and candidate.casefold() == username:
            matches.append(sid)
    if len(matches) > 1:
        raise SessionError(f"Multiple sessions match this user: {', '.join(map(str, matches))}. Specify --session ID.")
    if matches:
        return matches[0]
    raise SessionError(f"No session found for user '{username}'.")

def validate_session(session_id):
    sessions = {s['SessionId']: s for s in list_sessions(quiet=True)}
    if session_id not in sessions:
        raise SessionError(f'Session {session_id} does not exist. Use --list to see available sessions.')
    state = sessions[session_id]['State']
    if state not in (win32ts.WTSActive, win32ts.WTSConnected, win32ts.WTSDisconnected):
        raise SessionError(f"Session {session_id} is in state '{STATE_NAMES.get(state, state)}', which is not suitable for launching processes.")
    if not query_account(session_id):
        raise SessionError(f'Session {session_id} has no logged-on user.')
    return sessions[session_id]

def prepare_command(cmd=None, executable=None, arguments=''):
    if executable is not None:
        if cmd is not None:
            raise SessionError('Use --exe or --cmd, not both.')
        if not executable or '"' in executable or '\x00' in executable:
            raise SessionError('Select an executable without quotes in the path field.')
        if not os.path.isabs(executable) or not os.path.isfile(executable):
            raise SessionError('The executable must be an absolute path to an existing file.')
        if '\x00' in arguments:
            raise SessionError('Arguments contain an invalid null character.')
        return (executable, f'"{executable}"' + (f' {arguments}' if arguments else ''))
    if arguments:
        raise SessionError('Separate arguments require --exe.')
    cmd = 'notepad.exe' if cmd is None else cmd
    if not cmd.strip() or '\x00' in cmd:
        raise SessionError('The command must not be empty or contain null characters.')
    return (None, cmd)

def get_user_token(session_id):
    try:
        token = win32ts.WTSQueryUserToken(session_id)
    except pywintypes.error as e:
        if e.winerror == 1008:
            raise SessionError(f'No logged-on user in session {session_id} (token unavailable).')
        if e.winerror == 5:
            raise SessionError('WTSQueryUserToken denied access: SYSTEM/SeTcbPrivilege is required.')
        raise SessionError(f'WTSQueryUserToken failed: {e.strerror} (code {e.winerror})')
    return token

def grant_interactive_desktop(token, destination_id, desktop):
    if desktop.casefold() != 'winsta0\\default':
        raise SessionError('Cross-session desktop access supports winsta0\\default only.')
    with ExitStack() as resources:
        own = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        resources.callback(own.Close)
        if win32security.GetTokenInformation(own, win32security.TokenSessionId) != destination_id:
            raise SessionError('Run the SYSTEM GUI inside the destination session before granting desktop access.')
        station_name = win32service.GetUserObjectInformation(win32service.GetProcessWindowStation(), win32con.UOI_NAME)
        if station_name.casefold() != 'winsta0':
            raise SessionError('The SYSTEM launcher must be attached to the destination interactive window station.')
        groups = win32security.GetTokenInformation(token, win32security.TokenGroups)
        logon_sids = [sid for sid, flags in groups if flags & 3221225472 == 3221225472]
        if len(logon_sids) != 1:
            raise SessionError('Cannot identify a unique logon SID for the source account.')
        station = win32service.OpenWindowStation('winsta0', False, win32con.READ_CONTROL | win32con.WRITE_DAC)
        resources.callback(station.CloseWindowStation)
        desk = win32service.OpenDesktop('default', 0, False, win32con.READ_CONTROL | win32con.WRITE_DAC)
        resources.callback(desk.CloseDesktop)
        objects = ((station, 131895), (desk, 131271))
        planned = []
        for handle, mask in objects:
            descriptor = win32security.GetUserObjectSecurity(handle, win32security.DACL_SECURITY_INFORMATION)
            old_acl = descriptor.GetSecurityDescriptorDacl()
            if old_acl is None:
                continue
            sid = logon_sids[0]
            existing = 0
            entries = [old_acl.GetAce(i) for i in range(old_acl.GetAceCount())]
            for ace in entries:
                if ace[0][0] == win32security.ACCESS_ALLOWED_ACE_TYPE and ace[-1] == sid:
                    existing |= ace[1]
            missing = mask & ~existing
            if not missing:
                continue
            acl = old_acl
            acl.SetEntriesInAcl([{'AccessPermissions': missing, 'AccessMode': win32security.GRANT_ACCESS, 'Inheritance': 0, 'Trustee': {'TrusteeForm': win32security.TRUSTEE_IS_SID, 'TrusteeType': win32security.TRUSTEE_IS_GROUP, 'Identifier': sid}}])
            new_descriptor = win32security.SECURITY_DESCRIPTOR()
            new_descriptor.SetSecurityDescriptorDacl(1, acl, 0)
            planned.append((handle, descriptor, new_descriptor))
        applied = []
        try:
            for handle, previous, updated in planned:
                win32security.SetUserObjectSecurity(handle, win32security.DACL_SECURITY_INFORMATION, updated)
                applied.append((handle, previous))
        except pywintypes.error as exc:
            rollback_failed = False
            for handle, previous in reversed(applied):
                try:
                    win32security.SetUserObjectSecurity(handle, win32security.DACL_SECURITY_INFORMATION, previous)
                except pywintypes.error:
                    rollback_failed = True
            raise SessionError('Desktop access grant failed.' + (' Some access changes could not be rolled back; review desktop permissions.' if rollback_failed else ' Applied changes were rolled back.')) from exc
    log.warning('Desktop access granted to the source logon SID. The grant can outlive this process; destination logoff removes the desktop.')

def run_in_session(session_id, cmd=None, desktop='winsta0\\default', cwd=None, wait=False, timeout=None, dry_run=False, *, executable=None, arguments='', stop_wait=None, notify=None, source_session_id=None, grant_desktop_access=False, expected_source_account=None):
    application, cmd = prepare_command(cmd, executable, arguments)
    validate_options(cmd, cwd, desktop, wait, timeout)
    validate_session(session_id)
    source_id = session_id if source_session_id is None else source_session_id
    if source_id != session_id:
        validate_session(source_id)
    target_user = query_account(source_id)
    if expected_source_account is not None and target_user.casefold() != expected_source_account.casefold():
        raise SessionError('The source session account changed. Refresh sessions and select the execution account again.')
    destination_user = query_account(session_id)
    if dry_run:
        log.info('[SIMULATION] Input and session %d are valid (user: %s). No process launched.', session_id, target_user)
        log.info('Executable: %s. Arguments hidden.', 'explicit path checked' if application else 'legacy command: availability not checked')
        log.info('Not checked: launch privileges, target user access, profile, desktop and actual startup.')
        log.info('Execution account: %s (source session %d). Destination desktop: session %d (%s).', target_user, source_id, session_id, destination_user)
        if source_id != session_id:
            log.warning('Cross-session launch requires explicit desktop access consent. Simulation does not change permissions.')
        return RunResult('simulated')
    if stop_wait is not None and stop_wait.is_set():
        return RunResult('cancelled')
    ensure_tcb_privilege()
    if source_id != session_id and (not grant_desktop_access):
        raise SessionError('Enable desktop access consent for a cross-session launch, or use the same source and destination.')
    with ExitStack() as resources:
        token = get_user_token(source_id)
        resources.callback(token.Close)
        if expected_source_account is not None:
            sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
            name, domain, _ = win32security.LookupAccountSid(None, sid)
            token_account = f'{domain}\\{name}' if domain else name
            if token_account.casefold() != expected_source_account.casefold():
                raise SessionError('The acquired token does not belong to the selected source account. No process was created.')
        try:
            primary = win32security.DuplicateTokenEx(token, win32security.SecurityImpersonation, win32con.MAXIMUM_ALLOWED, win32security.TokenPrimary, None)
        except pywintypes.error as e:
            raise SessionError(f'DuplicateTokenEx failed: {e.strerror}')
        resources.callback(primary.Close)
        if source_id != session_id:
            try:
                win32security.SetTokenInformation(primary, win32security.TokenSessionId, session_id)
            except pywintypes.error as exc:
                raise SessionError(f'Cannot assign destination session to the source token (code {exc.winerror}).') from exc
        try:
            env = win32profile.CreateEnvironmentBlock(primary, False)
        except pywintypes.error as e:
            raise SessionError(f'User environment creation failed: {e.strerror}')
        si = win32process.STARTUPINFO()
        si.lpDesktop = desktop
        if stop_wait is not None and stop_wait.is_set():
            return RunResult('cancelled')
        if source_id != session_id:
            try:
                grant_interactive_desktop(primary, session_id, desktop)
            except pywintypes.error as exc:
                raise SessionError(f'Cannot grant destination desktop access (code {exc.winerror}).') from exc
        try:
            hProc, hThread, pid, tid = win32process.CreateProcessAsUser(primary, application, cmd, None, None, False, win32con.CREATE_UNICODE_ENVIRONMENT, env, cwd, si)
        except pywintypes.error as e:
            if e.winerror == 2:
                raise SessionError('Executable not found. Check the path and command quoting.')
            raise SessionError(f'CreateProcessAsUser failed: {e.strerror} (code {e.winerror})')
        resources.callback(hProc.Close)
        resources.callback(hThread.Close)
        log.info('Launched in session %d (user: %s) - PID %d. Arguments hidden.', session_id, target_user, pid)
        if notify:
            notify(pid)
        if not wait:
            return RunResult('launched', pid)
        return wait_for_process(hProc, pid, timeout, stop_wait)

def wait_for_process(process, pid, timeout=None, stop_wait=None):
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        if stop_wait is not None and stop_wait.is_set():
            log.info('Monitoring stopped for PID %d; no termination requested.', pid)
            return RunResult('detached', pid)
        remaining = None if deadline is None else max(0, deadline - time.monotonic())
        millis = 100 if remaining is None else min(100, int(remaining * 1000))
        result = win32event.WaitForSingleObject(process, millis)
        if result == win32event.WAIT_OBJECT_0:
            code = win32process.GetExitCodeProcess(process)
            log.info('Process PID %d exited with code %d', pid, code)
            return RunResult('exited', pid, code)
        if result != win32event.WAIT_TIMEOUT:
            raise SessionError(f'Wait failed for PID {pid}; the process may still be running.')
        if deadline is not None and time.monotonic() >= deadline:
            log.warning('Timeout for PID %d. No termination requested; subsequent state is not monitored.', pid)
            return RunResult('timeout', pid)
