"""Git operations using subprocess"""

import subprocess
import sys
from typing import Optional, Tuple


class GitError(Exception):
    """Raised when a git command fails"""
    pass


def run_git_command(args: list, capture_output: bool = True, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command and return the result"""
    try:
        result = subprocess.run(
            ['git'] + args,
            capture_output=capture_output,
            text=True,
            check=check
        )
        return result
    except subprocess.CalledProcessError as e:
        raise GitError(f"Git command failed: {' '.join(['git'] + args)}\n{e.stderr}")


def get_git_dir() -> str:
    """Get the .git directory path"""
    result = run_git_command(['rev-parse', '--git-dir'])
    return result.stdout.strip()


def is_git_repo() -> bool:
    """Check if current directory is inside a git repo"""
    try:
        run_git_command(['rev-parse', '--git-dir'])
        return True
    except GitError:
        return False


def get_repo_root() -> str:
    """Get the root directory of the git repository"""
    result = run_git_command(['rev-parse', '--show-toplevel'])
    return result.stdout.strip()


def get_diff() -> str:
    """Get the full uncommitted diff including untracked files"""
    # First, add untracked files with intent-to-add so they show up in diff
    result = run_git_command(['ls-files', '--others', '--exclude-standard'])
    untracked_files = [f for f in result.stdout.strip().split('\n') if f]

    # Use intent-to-add for untracked files
    if untracked_files:
        run_git_command(['add', '-N'] + untracked_files)

    # Check if HEAD exists
    has_head = True
    try:
        run_git_command(['rev-parse', 'HEAD'], check=True)
    except GitError:
        has_head = False

    # Get full diff
    if has_head:
        result = run_git_command(['diff', 'HEAD'])
    else:
        # No HEAD, show all staged/tracked changes
        result = run_git_command(['diff'])

    # Remove intent-to-add for untracked files
    if untracked_files:
        run_git_command(['reset', '--'] + untracked_files, check=False)

    return result.stdout


def apply_patch_to_index(patch: str) -> Tuple[bool, str]:
    """
    Apply a patch to the index (staging area) using git apply --cached.

    Returns:
        (success: bool, error_message: str)
    """
    try:
        result = subprocess.run(
            ['git', 'apply', '--cached'],
            input=patch,
            capture_output=True,
            text=True,
            check=True
        )
        return True, ""
    except subprocess.CalledProcessError as e:
        return False, e.stderr


def stash_keep_index() -> Tuple[bool, bool, str]:
    """
    Stash everything not in the index.

    Returns:
        (success: bool, stash_created: bool, error_message: str)
    """
    try:
        # Check if HEAD exists - stash doesn't work without an initial commit
        try:
            run_git_command(['rev-parse', 'HEAD'], check=True)
        except GitError:
            # No HEAD yet, stash won't work. That's OK - nothing to isolate in a new repo.
            return True, False, ""

        # Check if there's anything to stash
        result = run_git_command(['status', '--porcelain'])
        unstaged_changes = False
        for line in result.stdout.split('\n'):
            if line and (line[1] != ' ' or line.startswith('??')):
                unstaged_changes = True
                break

        if not unstaged_changes:
            # Nothing to stash, that's fine
            return True, False, ""

        run_git_command(['stash', '--keep-index', '--include-untracked'])
        return True, True, ""
    except GitError as e:
        return False, False, str(e)


def stash_pop() -> Tuple[bool, str]:
    """Pop the stash. Returns (success, error_message)"""
    try:
        run_git_command(['stash', 'pop'])
        return True, ""
    except GitError as e:
        return False, str(e)


def reset_index() -> bool:
    """Clear the index. Returns True on success."""
    try:
        run_git_command(['reset'])
        return True
    except GitError:
        return False


def create_commit(message: str) -> Tuple[bool, str]:
    """
    Create a git commit with the staged changes.

    Returns:
        (success: bool, commit_hash_or_error: str)
    """
    try:
        run_git_command(['commit', '-m', message])
        # Get the commit hash
        result = run_git_command(['rev-parse', 'HEAD'])
        commit_hash = result.stdout.strip()[:7]  # Short hash
        return True, commit_hash
    except GitError as e:
        return False, str(e)


def add_to_exclude(pattern: str) -> bool:
    """Add a pattern to .git/info/exclude"""
    try:
        git_dir = get_git_dir()
        exclude_file = f"{git_dir}/info/exclude"

        # Read existing content
        try:
            with open(exclude_file, 'r') as f:
                content = f.read()
        except FileNotFoundError:
            content = ""

        # Check if pattern already exists
        if pattern in content.split('\n'):
            return True

        # Append pattern
        with open(exclude_file, 'a') as f:
            if content and not content.endswith('\n'):
                f.write('\n')
            f.write(f"{pattern}\n")

        return True
    except Exception:
        return False


def create_backup_branch() -> Tuple[bool, str]:
    """
    Create a backup branch with current working tree state WITHOUT checking out branches.

    Returns:
        (success: bool, branch_name_or_error: str)
    """
    from datetime import datetime
    import tempfile
    import os

    try:
        # Get current branch name
        result = run_git_command(['branch', '--show-current'])
        current_branch = result.stdout.strip()

        # Generate backup branch name with timestamp
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        backup_branch = f"gitmark/backup-{timestamp}"

        # Get current HEAD
        result = run_git_command(['rev-parse', 'HEAD'], check=False)
        if result.returncode != 0:
            # No commits yet - create an orphan branch with all current files
            # Use git hash-object and write-tree to create commit without checking out
            run_git_command(['add', '-A'])
            tree = run_git_command(['write-tree']).stdout.strip()
            commit = run_git_command(['commit-tree', tree, '-m', f'gitmark backup {timestamp}']).stdout.strip()
            run_git_command(['branch', backup_branch, commit])
            run_git_command(['reset'])  # Unstage everything
            return True, backup_branch

        current_head = result.stdout.strip()

        # Create a temporary index file
        git_dir = get_git_dir()
        temp_index = tempfile.NamedTemporaryFile(delete=False, suffix='.index')
        temp_index.close()

        try:
            # Set GIT_INDEX_FILE to use temporary index
            env = os.environ.copy()
            env['GIT_INDEX_FILE'] = temp_index.name

            # Initialize temp index from current HEAD tree
            subprocess.run(['git', 'read-tree', current_head], env=env, check=True, capture_output=True)

            # Add all current files to temp index
            subprocess.run(['git', 'add', '-A'], env=env, check=True, capture_output=True)

            # Write tree from temp index
            result = subprocess.run(['git', 'write-tree'], env=env, check=True, capture_output=True, text=True)
            tree = result.stdout.strip()

            # Create commit from tree with current HEAD as parent
            result = subprocess.run(
                ['git', 'commit-tree', tree, '-p', current_head, '-m', f'gitmark backup {timestamp}'],
                check=True, capture_output=True, text=True
            )
            commit = result.stdout.strip()

            # Create branch pointing to new commit
            run_git_command(['branch', backup_branch, commit])

        finally:
            # Clean up temp index
            if os.path.exists(temp_index.name):
                os.unlink(temp_index.name)

        return True, backup_branch

    except (GitError, subprocess.CalledProcessError) as e:
        return False, str(e)


def list_backup_branches() -> list:
    """
    List all gitmark backup branches.
    
    Returns:
        List of tuples: (branch_name, timestamp, commit_date)
    """
    try:
        result = run_git_command(['branch', '--list', 'gitmark/backup-*', '--format=%(refname:short)|%(committerdate:iso)'])
        branches = []
        
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split('|')
            if len(parts) == 2:
                branch_name = parts[0]
                commit_date = parts[1]
                # Extract timestamp from branch name
                timestamp = branch_name.replace('gitmark/backup-', '')
                branches.append((branch_name, timestamp, commit_date))
        
        return sorted(branches, key=lambda x: x[1], reverse=True)
        
    except GitError:
        return []


def restore_from_backup(backup_branch: str) -> Tuple[bool, str]:
    """
    Restore working tree from a backup branch.
    
    Returns:
        (success: bool, error_message: str)
    """
    try:
        # Get current branch
        result = run_git_command(['branch', '--show-current'])
        current_branch = result.stdout.strip()
        
        # Verify backup branch exists
        result = run_git_command(['rev-parse', '--verify', backup_branch], check=False)
        if result.returncode != 0:
            return False, f"backup branch '{backup_branch}' not found"
        
        # Get the backup commit
        result = run_git_command(['rev-parse', backup_branch])
        backup_commit = result.stdout.strip()
        
        # Get parent of backup commit (the original HEAD)
        result = run_git_command(['rev-parse', f'{backup_branch}^'], check=False)
        if result.returncode != 0:
            # No parent - backup was made in empty repo
            parent_commit = None
        else:
            parent_commit = result.stdout.strip()
        
        # Reset current branch to its HEAD (discarding working tree changes)
        run_git_command(['reset', '--hard'])
        
        # Checkout the backup branch
        run_git_command(['checkout', backup_branch])
        
        # Soft reset to parent (or initial state), leaving changes in working tree
        if parent_commit:
            run_git_command(['reset', '--soft', parent_commit])
        else:
            # No parent - just unstage everything
            run_git_command(['reset', '--soft', '--'])
        
        # Return to original branch with restored working tree
        if current_branch:
            run_git_command(['checkout', current_branch])
        else:
            # Was detached - stay detached at same commit
            if parent_commit:
                run_git_command(['checkout', parent_commit])
        
        return True, ""
        
    except GitError as e:
        return False, str(e)


def delete_backup_branch(backup_branch: str) -> Tuple[bool, str]:
    """
    Delete a backup branch.
    
    Returns:
        (success: bool, error_message: str)
    """
    try:
        run_git_command(['branch', '-D', backup_branch])
        return True, ""
    except GitError as e:
        return False, str(e)
