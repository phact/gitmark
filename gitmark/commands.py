"""Command implementations for gitmark CLI"""

import sys
import subprocess
import tempfile
import os
from typing import List, Dict, Optional
from colorama import Fore, Style, init as colorama_init

from .git_ops import (
    get_diff, apply_patch_to_index, stash_keep_index, stash_pop,
    reset_index, create_commit, GitError
)
from .hunk_parser import (
    parse_diff_output, find_hunks_by_address, get_hunk_identifier, Hunk
)
from .state import StateManager, Plan, NamedCommit

# Initialize colorama for cross-platform color support
colorama_init()


def get_all_hunks() -> Dict[str, List[Hunk]]:
    """Get all uncommitted hunks"""
    diff = get_diff()
    if not diff:
        return {}
    return parse_diff_output(diff)


def cmd_diff(args) -> int:
    """Show uncommitted changes with assignment state"""
    state_mgr = StateManager()
    plan = state_mgr.load()
    hunks_by_file = get_all_hunks()

    if not hunks_by_file:
        print("No uncommitted changes")
        return 0

    # If a tag is specified, show only hunks for that tag
    if args.tag:
        target_tag = args.tag
        commit = plan.get_commit(target_tag)
        if not commit:
            print(f"{Fore.RED}Error: tag '{target_tag}' not found{Style.RESET_ALL}")
            return 1

        # Show full diff for hunks in this tag
        print(f"{Fore.CYAN}Hunks assigned to {target_tag}:{Style.RESET_ALL}\n")

        for file_path, hunks in sorted(hunks_by_file.items()):
            file_shown = False
            for hunk in hunks:
                hunk_id = get_hunk_identifier(hunk)
                if hunk_id in commit.hunks:
                    if not file_shown:
                        print(f"{Fore.CYAN}{file_path}{Style.RESET_ALL}")
                        file_shown = True
                    # Show full hunk content
                    for line in hunk.content:
                        if line.startswith('+') and not line.startswith('+++'):
                            print(f"{Fore.GREEN}{line}{Style.RESET_ALL}")
                        elif line.startswith('-') and not line.startswith('---'):
                            print(f"{Fore.RED}{line}{Style.RESET_ALL}")
                        else:
                            print(line)
                    print()  # Blank line between hunks
        return 0

    # Show overview with assignment state
    for file_path, hunks in sorted(hunks_by_file.items()):
        print(f"{file_path}")

        for hunk in hunks:
            hunk_id = get_hunk_identifier(hunk)
            owner = plan.find_hunk_owner(hunk_id)

            # Extract first line of actual code change for display
            first_line = ""
            for line in hunk.content[1:]:  # Skip header
                if line.startswith(('+', '-')) and not line.startswith(('+++', '---')):
                    first_line = line[:50]  # Truncate long lines
                    break

            # Format: :line +added -removed first_line_preview → tag
            added = f"+{hunk.added_lines}" if hunk.added_lines else ""
            removed = f"-{hunk.removed_lines}" if hunk.removed_lines else ""
            stats = f"{added:>4} {removed:>4}"

            if owner:
                print(f"  :{hunk.start_line:<4} {stats}  {first_line:<40} {Fore.GREEN}→ {owner}{Style.RESET_ALL}")
            else:
                print(f"  :{hunk.start_line:<4} {stats}  {first_line:<40} {Fore.YELLOW}✗ unassigned{Style.RESET_ALL}")

        print()  # Blank line between files

    return 0


def cmd_mark(args) -> int:
    """Assign hunks to a named commit"""
    tag = args.tag
    addresses = args.addresses

    state_mgr = StateManager()
    plan = state_mgr.load()
    hunks_by_file = get_all_hunks()

    if not hunks_by_file:
        print(f"{Fore.RED}Error: no uncommitted changes{Style.RESET_ALL}")
        return 1

    # Find all hunks matching the addresses
    hunks_to_mark = []
    for address in addresses:
        matches = find_hunks_by_address(hunks_by_file, address)

        if not matches:
            print(f"{Fore.RED}Error: no hunks match '{address}'{Style.RESET_ALL}")
            print(f"\nRun 'gitmark diff' to see available hunks")
            return 1

        for hunk in matches:
            hunk_id = get_hunk_identifier(hunk)

            # Check if already assigned to a different tag
            owner = plan.find_hunk_owner(hunk_id)
            if owner and owner != tag:
                print(f"{Fore.RED}Error: hunk {hunk_id} already assigned to '{owner}'{Style.RESET_ALL}")
                return 1

            hunks_to_mark.append(hunk)

    # All checks passed, assign the hunks
    commit = plan.add_commit(tag)

    for hunk in hunks_to_mark:
        hunk_id = get_hunk_identifier(hunk)
        if hunk_id not in commit.hunks:
            commit.hunks.append(hunk_id)

    state_mgr.save(plan)

    print(f"{Fore.GREEN}✓{Style.RESET_ALL} Marked {len(hunks_to_mark)} hunk(s) for '{tag}'")
    return 0


def cmd_unmark(args) -> int:
    """Remove hunk assignments"""
    tag = args.tag
    addresses = args.addresses

    state_mgr = StateManager()
    plan = state_mgr.load()
    hunks_by_file = get_all_hunks()

    commit = plan.get_commit(tag)
    if not commit:
        print(f"{Fore.RED}Error: tag '{tag}' not found{Style.RESET_ALL}")
        return 1

    # Find hunks to unmark
    hunks_to_unmark = []
    for address in addresses:
        matches = find_hunks_by_address(hunks_by_file, address)

        if not matches:
            print(f"{Fore.RED}Error: no hunks match '{address}'{Style.RESET_ALL}")
            return 1

        hunks_to_unmark.extend(matches)

    # Remove the hunks
    removed_count = 0
    for hunk in hunks_to_unmark:
        hunk_id = get_hunk_identifier(hunk)
        if hunk_id in commit.hunks:
            commit.hunks.remove(hunk_id)
            removed_count += 1

    state_mgr.save(plan)

    print(f"{Fore.GREEN}✓{Style.RESET_ALL} Unmarked {removed_count} hunk(s) from '{tag}'")
    return 0


def cmd_exec(args) -> int:
    """Attach an exec command to a named commit"""
    tag = args.tag
    command = args.command

    state_mgr = StateManager()
    plan = state_mgr.load()

    commit = plan.add_commit(tag)
    commit.exec_command = command

    state_mgr.save(plan)

    print(f"{Fore.GREEN}✓{Style.RESET_ALL} Set exec command for '{tag}': {command}")
    return 0


def cmd_message(args) -> int:
    """Set the commit message for a named commit"""
    tag = args.tag
    message = args.message

    state_mgr = StateManager()
    plan = state_mgr.load()

    commit = plan.add_commit(tag)
    commit.message = message

    state_mgr.save(plan)

    print(f"{Fore.GREEN}✓{Style.RESET_ALL} Set message for '{tag}'")
    return 0


def cmd_reset(args) -> int:
    """Remove a named commit from the plan"""
    tag = args.tag

    state_mgr = StateManager()
    plan = state_mgr.load()

    if plan.remove_commit(tag):
        state_mgr.save(plan)
        print(f"{Fore.GREEN}✓{Style.RESET_ALL} Removed '{tag}' from plan")
        return 0
    else:
        print(f"{Fore.RED}Error: tag '{tag}' not found{Style.RESET_ALL}")
        return 1


def cmd_status(args) -> int:
    """Show the current plan"""
    state_mgr = StateManager()
    plan = state_mgr.load()
    hunks_by_file = get_all_hunks()

    if not plan.commits:
        print("No commits in plan")
        print("\nRun 'gitmark mark <tag> <hunk>' to start planning")
        return 0

    print(f"{Fore.CYAN}PLAN{Style.RESET_ALL}\n")

    for commit in plan.get_sorted_commits():
        print(f"  {Fore.GREEN}{commit.tag}{Style.RESET_ALL}")

        if commit.message:
            print(f"    message : \"{commit.message}\"")
        else:
            print(f"    message : {Fore.YELLOW}(not set){Style.RESET_ALL}")

        if commit.exec_command:
            print(f"    exec    : {commit.exec_command}")

        if commit.hunks:
            hunk_list = "  ".join(commit.hunks)
            print(f"    hunks   : {hunk_list}")
        else:
            print(f"    hunks   : {Fore.YELLOW}(none){Style.RESET_ALL}")

        print()

    # Show unassigned hunks
    all_hunk_ids = set()
    for hunks in hunks_by_file.values():
        for hunk in hunks:
            all_hunk_ids.add(get_hunk_identifier(hunk))

    assigned_hunk_ids = set()
    for commit in plan.commits:
        assigned_hunk_ids.update(commit.hunks)

    unassigned = all_hunk_ids - assigned_hunk_ids

    if unassigned:
        print(f"{Fore.YELLOW}UNASSIGNED{Style.RESET_ALL}")
        for hunk_id in sorted(unassigned):
            print(f"    {hunk_id}")

    return 0


def cmd_commit(args) -> int:
    """Execute commits"""
    from .git_ops import create_backup_branch, delete_backup_branch

    state_mgr = StateManager()
    plan = state_mgr.load()
    hunks_by_file = get_all_hunks()

    if not plan.commits:
        print(f"{Fore.RED}Error: no commits in plan{Style.RESET_ALL}")
        return 1

    # Create backup before doing anything
    success, backup_branch_or_error = create_backup_branch()
    if not success:
        print(f"{Fore.RED}Error: failed to create backup branch{Style.RESET_ALL}")
        print(f"{backup_branch_or_error}")
        print(f"\nAborting - will not proceed without backup")
        return 1

    backup_branch = backup_branch_or_error
    print(f"{Fore.GREEN}✓{Style.RESET_ALL} backup created: {Fore.CYAN}{backup_branch}{Style.RESET_ALL}\n")

    # Single tag mode
    if args.tag:
        result = _commit_single(args.tag, args.message, plan, hunks_by_file, state_mgr)
    else:
        # Bulk mode - execute all commits
        result = _commit_all(plan, hunks_by_file, state_mgr, args.allow_unassigned, args.edit)

    # Offer to delete backup if successful
    if result == 0:
        try:
            response = input(f"\ndelete backup branch {backup_branch}? [y/N] ")
            if response.lower() in ('y', 'yes'):
                success, error = delete_backup_branch(backup_branch)
                if success:
                    print(f"{Fore.GREEN}✓{Style.RESET_ALL} Deleted {backup_branch}")
                else:
                    print(f"{Fore.YELLOW}Warning: failed to delete backup: {error}{Style.RESET_ALL}")
            else:
                print(f"Backup kept: {backup_branch}")
        except (KeyboardInterrupt, EOFError):
            print(f"\nBackup kept: {backup_branch}")

    return result


def _commit_single(tag: str, message: str, plan: Plan, hunks_by_file: Dict[str, List[Hunk]], state_mgr: StateManager) -> int:
    """Execute a single named commit"""
    commit = plan.get_commit(tag)
    if not commit:
        print(f"{Fore.RED}Error: tag '{tag}' not found{Style.RESET_ALL}")
        return 1

    if not message:
        print(f"{Fore.RED}Error: commit message required (use -m){Style.RESET_ALL}")
        return 1

    if not commit.hunks:
        print(f"{Fore.RED}Error: no hunks assigned to '{tag}'{Style.RESET_ALL}")
        return 1

    # Set the message
    commit.message = message

    # Execute the commit
    success, error = _execute_commit(commit, hunks_by_file)

    if success:
        # Remove from plan
        plan.remove_commit(tag)
        state_mgr.save(plan)
        return 0
    else:
        return 1


def _commit_all(plan: Plan, hunks_by_file: Dict[str, List[Hunk]], state_mgr: StateManager, allow_unassigned: bool, edit: bool) -> int:
    """Execute all commits in the plan"""

    # Check all commits have messages
    missing_messages = [c.tag for c in plan.commits if not c.message]
    if missing_messages:
        print(f"{Fore.RED}Error: the following tags have no message set:{Style.RESET_ALL}")
        for tag in missing_messages:
            print(f"  {tag}")
        print(f"\nSet messages with: gitmark message <tag> \"<message>\"")
        return 1

    # Check for unassigned hunks
    if not allow_unassigned:
        all_hunk_ids = set()
        for hunks in hunks_by_file.values():
            for hunk in hunks:
                all_hunk_ids.add(get_hunk_identifier(hunk))

        assigned_hunk_ids = set()
        for commit in plan.commits:
            assigned_hunk_ids.update(commit.hunks)

        unassigned = all_hunk_ids - assigned_hunk_ids

        if unassigned:
            print(f"{Fore.RED}Error: unassigned hunks remain:{Style.RESET_ALL}")
            for hunk_id in sorted(unassigned):
                print(f"  {hunk_id}")
            print(f"\nAssign them or use --allow-unassigned to proceed anyway")
            return 1

    # TODO: Handle --edit flag

    # Execute commits in order
    commits_to_execute = plan.get_sorted_commits()
    total = len(commits_to_execute)

    print(f"executing plan  ({total} commit{'s' if total != 1 else ''})\n")

    executed_tags = []

    for i, commit in enumerate(commits_to_execute, 1):
        print(f"  [{i}/{total}] {Fore.GREEN}{commit.tag}{Style.RESET_ALL}")
        print(f"        hunks   : {' '.join(commit.hunks)}")
        if commit.exec_command:
            print(f"        exec    : {commit.exec_command}")

        success, error = _execute_commit(commit, hunks_by_file)

        if success:
            executed_tags.append(commit.tag)
            # Reload hunks since the working tree changed
            hunks_by_file = get_all_hunks()
            print()
        else:
            # Failure - clean up and report
            print(f"\n{Fore.RED}gitmark: bailing. repo restored to pre-commit state.{Style.RESET_ALL}")
            if executed_tags:
                print(f"commits already applied : {', '.join(executed_tags)}")

            remaining = [c.tag for c in commits_to_execute[i:]]
            print(f"remaining               : {', '.join(remaining)}")
            print(f"fix the issue and re-run: gitmark commit")

            # Remove successfully executed commits from plan
            for tag in executed_tags:
                plan.remove_commit(tag)
            state_mgr.save(plan)

            return 1

    # All succeeded - remove from plan
    for tag in executed_tags:
        plan.remove_commit(tag)

    # If plan is now empty, delete the state file
    if not plan.commits:
        state_mgr.delete()
    else:
        state_mgr.save(plan)

    return 0


def _execute_commit(commit: NamedCommit, hunks_by_file: Dict[str, List[Hunk]]) -> tuple:
    """
    Execute a single commit. Returns (success, error_message).

    Steps:
    1. Build patch from assigned hunks
    2. Apply to index
    3. Stash everything not in index
    4. Run exec command if set
    5. Pop stash
    6. Create commit
    """

    # Build patch from hunks
    patch_lines = []
    current_file = None

    for hunk_id in commit.hunks:
        # Parse hunk_id to get file and line
        file_path, line_str = hunk_id.rsplit(':', 1)
        line = int(line_str)

        # Find the hunk
        hunk = None
        if file_path in hunks_by_file:
            for h in hunks_by_file[file_path]:
                if h.start_line == line:
                    hunk = h
                    break

        if not hunk:
            print(f"        {Fore.RED}✗ hunk not found: {hunk_id}{Style.RESET_ALL}")
            return False, f"hunk not found: {hunk_id}"

        # Add file header if new file
        if current_file != file_path:
            if current_file is not None:
                patch_lines.append("")  # Blank line between files

            patch_lines.append(f"diff --git a/{file_path} b/{file_path}")

            # Check if this is a new file (hunk starts at line 1 with only additions)
            is_new_file = (hunk.start_line == 1 and hunk.removed_lines == 0)
            if is_new_file:
                patch_lines.append("new file mode 100644")
                patch_lines.append("index 0000000..0000000")

            if is_new_file:
                patch_lines.append("--- /dev/null")
            else:
                patch_lines.append(f"--- a/{file_path}")
            patch_lines.append(f"+++ b/{file_path}")
            current_file = file_path

        # Add hunk content
        patch_lines.extend(hunk.content)

    patch = '\n'.join(patch_lines)

    # Apply to index
    print(f"        applying...  ", end='', flush=True)
    success, error = apply_patch_to_index(patch)
    if not success:
        print(f"{Fore.RED}✗ FAILED{Style.RESET_ALL}")
        print(f"\n{error}")
        reset_index()
        return False, f"failed to apply patch: {error}"
    print(f"{Fore.GREEN}✓{Style.RESET_ALL}")

    # Stash everything else
    print(f"        isolating... ", end='', flush=True)
    success, stash_created, error = stash_keep_index()
    if not success:
        print(f"{Fore.RED}✗ FAILED{Style.RESET_ALL}")
        print(f"\n{error}")
        reset_index()
        return False, f"failed to stash: {error}"
    print(f"{Fore.GREEN}✓{Style.RESET_ALL}")

    # Run exec command if set
    if commit.exec_command:
        print(f"        running...   ", end='', flush=True)

        try:
            result = subprocess.run(
                commit.exec_command,
                shell=True,
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                # Success
                output = result.stdout.strip()
                if output:
                    # Try to extract useful info (e.g., test count)
                    print(f"{Fore.GREEN}✓{Style.RESET_ALL}  ({output.split()[0] if output.split() else 'passed'})")
                else:
                    print(f"{Fore.GREEN}✓{Style.RESET_ALL}")
            else:
                # Failure
                print(f"{Fore.RED}✗ FAILED{Style.RESET_ALL}\n")
                print(f"        exec command exited with code {result.returncode}:")
                print(f"        {'─' * 50}")
                # Show stderr or stdout
                error_output = result.stderr or result.stdout
                for line in error_output.strip().split('\n')[:20]:  # Limit output
                    print(f"        {line}")
                print(f"        {'─' * 50}\n")

                # Pop stash and reset
                if stash_created:
                    stash_pop()
                reset_index()
                return False, f"exec command failed with code {result.returncode}"

        except Exception as e:
            print(f"{Fore.RED}✗ FAILED{Style.RESET_ALL}")
            print(f"        {str(e)}")
            if stash_created:
                stash_pop()
            reset_index()
            return False, str(e)

    # Pop stash
    if stash_created:
        success, error = stash_pop()
        if not success:
            print(f"{Fore.RED}Warning: failed to pop stash: {error}{Style.RESET_ALL}")

    # Create commit
    success, commit_hash = create_commit(commit.message)
    if not success:
        print(f"{Fore.RED}✗ Failed to create commit{Style.RESET_ALL}")
        return False, commit_hash

    print(f"        committed    {Fore.CYAN}{commit_hash}{Style.RESET_ALL}  \"{commit.message}\"")

    return True, ""


def cmd_restore(args) -> int:
    """Restore working tree from backup branch"""
    from .git_ops import list_backup_branches, restore_from_backup
    
    # List mode
    if args.list:
        backups = list_backup_branches()
        if not backups:
            print(f"{Fore.YELLOW}No backup branches found{Style.RESET_ALL}")
            return 0
        
        print(f"{Fore.CYAN}Available backups:{Style.RESET_ALL}\n")
        for branch_name, timestamp, commit_date in backups:
            print(f"  {branch_name:50}  {commit_date}")
        return 0
    
    # Restore mode
    backups = list_backup_branches()
    if not backups:
        print(f"{Fore.RED}Error: no backup branches found{Style.RESET_ALL}")
        return 1
    
    # Determine which backup to restore
    if args.backup:
        backup_branch = args.backup
    else:
        # Use most recent
        backup_branch = backups[0][0]
    
    # Show confirmation prompt
    from .git_ops import run_git_command
    result = run_git_command(['branch', '--show-current'])
    current_branch = result.stdout.strip() or "(detached HEAD)"
    
    # Get backup timestamp
    for branch, timestamp, commit_date in backups:
        if branch == backup_branch:
            backup_time = commit_date
            break
    else:
        print(f"{Fore.RED}Error: backup branch '{backup_branch}' not found{Style.RESET_ALL}")
        print(f"\nAvailable backups:")
        for branch_name, _, _ in backups:
            print(f"  {branch_name}")
        return 1
    
    print(f"restoring from {Fore.CYAN}{backup_branch}{Style.RESET_ALL}...")
    print()
    print(f"  this will discard all changes since the backup was created.")
    print(f"  current branch: {current_branch}")
    print(f"  backup taken  : {backup_time}")
    print()
    
    # Prompt for confirmation
    try:
        response = input(f"  continue? [y/N] ")
        if response.lower() not in ('y', 'yes'):
            print("Aborted")
            return 0
    except (KeyboardInterrupt, EOFError):
        print("\nAborted")
        return 0
    
    # Restore
    success, error = restore_from_backup(backup_branch)
    if not success:
        print(f"{Fore.RED}Error: {error}{Style.RESET_ALL}")
        return 1
    
    print(f"{Fore.GREEN}✓{Style.RESET_ALL} Restored from {backup_branch}")
    return 0
