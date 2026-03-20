"""Main CLI entry point for gitmark"""

import sys
import os
import argparse
from colorama import Fore, Style

from .git_ops import is_git_repo
from .commands import (
    cmd_diff, cmd_mark, cmd_unmark, cmd_exec, cmd_message,
    cmd_reset, cmd_status, cmd_commit, cmd_restore
)


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser"""
    parser = argparse.ArgumentParser(
        prog='gitmark',
        description='Assign uncommitted changes to named commits'
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # diff command
    diff_parser = subparsers.add_parser('diff', help='Show uncommitted changes with assignment state')
    diff_parser.add_argument('tag', nargs='?', help='Show only hunks for this tag')

    # mark command
    mark_parser = subparsers.add_parser('mark', help='Assign hunks to a named commit')
    mark_parser.add_argument('tag', help='Tag name for the commit')
    mark_parser.add_argument('addresses', nargs='+', help='Hunk addresses (file:line or file)')

    # unmark command
    unmark_parser = subparsers.add_parser('unmark', help='Remove hunk assignments')
    unmark_parser.add_argument('tag', help='Tag name')
    unmark_parser.add_argument('addresses', nargs='+', help='Hunk addresses to unmark')

    # exec command
    exec_parser = subparsers.add_parser('exec', help='Attach an exec command to a named commit')
    exec_parser.add_argument('tag', help='Tag name')
    exec_parser.add_argument('command', help='Shell command to run')

    # message command
    message_parser = subparsers.add_parser('message', help='Set commit message for a named commit')
    message_parser.add_argument('tag', help='Tag name')
    message_parser.add_argument('message', help='Commit message')

    # reset command
    reset_parser = subparsers.add_parser('reset', help='Remove a named commit from the plan')
    reset_parser.add_argument('tag', help='Tag name to remove')

    # status command
    status_parser = subparsers.add_parser('status', help='Show the current plan')

    # commit command
    commit_parser = subparsers.add_parser('commit', help='Execute commits')
    commit_parser.add_argument('tag', nargs='?', help='Tag to commit (omit to commit all)')
    commit_parser.add_argument('-m', '--message', help='Commit message (for single tag mode)')
    commit_parser.add_argument('--allow-unassigned', action='store_true',
                              help='Allow unassigned hunks (for bulk commit)')
    commit_parser.add_argument('--edit', action='store_true',
                              help='Edit plan in $EDITOR before executing')

    # restore command
    restore_parser = subparsers.add_parser('restore', help='Restore working tree from backup')
    restore_parser.add_argument('backup', nargs='?', help='Specific backup branch to restore (default: most recent)')
    restore_parser.add_argument('--list', action='store_true', help='List all backup branches')

    return parser


def main():
    """Main entry point"""
    # Check if we're in a git repo
    if not is_git_repo():
        print(f"{Fore.RED}Error: not a git repository{Style.RESET_ALL}")
        sys.exit(1)

    parser = create_parser()

    # If no arguments, show status
    if len(sys.argv) == 1:
        args = argparse.Namespace(command='status')
    else:
        args = parser.parse_args()

    # If no command specified, show status
    if not args.command:
        args.command = 'status'

    # Dispatch to command handler
    try:
        if args.command == 'diff':
            exit_code = cmd_diff(args)
        elif args.command == 'mark':
            exit_code = cmd_mark(args)
        elif args.command == 'unmark':
            exit_code = cmd_unmark(args)
        elif args.command == 'exec':
            exit_code = cmd_exec(args)
        elif args.command == 'message':
            exit_code = cmd_message(args)
        elif args.command == 'reset':
            exit_code = cmd_reset(args)
        elif args.command == 'status':
            exit_code = cmd_status(args)
        elif args.command == 'commit':
            exit_code = cmd_commit(args)
        elif args.command == 'restore':
            exit_code = cmd_restore(args)
        else:
            parser.print_help()
            exit_code = 1

        sys.exit(exit_code)

    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Interrupted{Style.RESET_ALL}")
        sys.exit(130)
    except BrokenPipeError:
        # Handle pipe closing (e.g., when output is piped to head)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(0)
    except Exception as e:
        print(f"{Fore.RED}Error: {str(e)}{Style.RESET_ALL}")
        sys.exit(1)


if __name__ == '__main__':
    main()
