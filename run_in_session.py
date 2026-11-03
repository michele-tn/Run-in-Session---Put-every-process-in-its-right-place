"""Run in Session: English Windows distribution."""
from __future__ import annotations
import argparse
import logging
import sys
import session_core as core

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Launch a process in a Windows session.')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--gui', action='store_true', help='Open the graphical interface')
    mode.add_argument('--list', action='store_true', help='List sessions')
    target = parser.add_mutually_exclusive_group()
    target.add_argument('--session', type=int, help='Session ID')
    target.add_argument('--user', help='User or DOMAIN\\user; a unique match is required')
    parser.add_argument('--source-session', type=int, help='Session providing the execution account token; defaults to destination')
    parser.add_argument('--grant-desktop-access', action='store_true', help='Allow the source logon to use the destination desktop; requires SYSTEM inside that session')
    command = parser.add_mutually_exclusive_group()
    command.add_argument('--cmd', help='Legacy full command; quote executable paths containing spaces')
    command.add_argument('--exe', help='Absolute executable path (recommended)')
    parser.add_argument('--args', default='', help='Windows arguments for --exe; use --args=... for values starting with -')
    parser.add_argument('--cwd', help='Working directory')
    parser.add_argument('--desktop', default='winsta0\\default', help='Target desktop')
    parser.add_argument('--wait', action='store_true', help='Wait and return the outcome')
    parser.add_argument('--timeout', type=float, help='Timeout in seconds; zero checks immediately')
    parser.add_argument('--dry-run', action='store_true', help='Check input and session without launching')
    parser.add_argument('-v', '--verbose', action='store_true', help='Detailed diagnostics without command arguments')
    args = parser.parse_args(argv)
    if args.args and (not args.exe):
        parser.error('--args requires --exe')
    if (args.gui or args.list) and (args.session is not None or args.user or args.exe or (args.cmd is not None) or args.args or args.wait or (args.timeout is not None) or args.dry_run or args.cwd or (args.source_session is not None) or args.grant_desktop_access):
        parser.error('--gui and --list do not accept launch options')
    return args

def result_exit_code(result: core.RunResult) -> int:
    if result.status == 'timeout':
        return 124
    if result.status in ('detached', 'cancelled'):
        return 125
    if result.status == 'exited' and result.exit_code != 0:
        return 3
    return 0

def main(argv=None) -> int:
    values = sys.argv[1:] if argv is None else argv
    args = parse_args(values)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format='[%(levelname)s] %(message)s', stream=sys.stdout)
    try:
        if args.gui or not values:
            from run_in_session_gui import launch_gui
            return launch_gui()
        if args.list:
            rows = core.session_rows()
            print('\nWINDOWS SESSIONS\n')
            print(core.format_table(('ID', 'Account', 'State', 'Station'), rows))
            print(f'\nSessions found: {len(rows)}')
            return 0
        if args.session is None and (not args.user):
            raise core.SessionError('Specify --session ID, --user account or --list.')
        session_id = args.session if args.session is not None else core.find_session_by_user(args.user)
        result = core.run_in_session(session_id, args.cmd, args.desktop, args.cwd, args.wait, args.timeout, args.dry_run, executable=args.exe, arguments=args.args, source_session_id=args.source_session, grant_desktop_access=args.grant_desktop_access)
        return result_exit_code(result)
    except core.SessionError as exc:
        core.log.error('%s', exc)
        return 1
    except Exception as exc:
        core.log.error('Unexpected error (%s). Check the session, path and permissions.', type(exc).__name__)
        return 1
if __name__ == '__main__':
    sys.exit(main())
