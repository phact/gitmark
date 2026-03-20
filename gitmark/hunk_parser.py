"""Parse git diff output to extract hunks and their locations"""

import re
from dataclasses import dataclass
from typing import List, Dict, Tuple


@dataclass
class Hunk:
    """Represents a single hunk from git diff"""
    file_path: str
    start_line: int
    added_lines: int
    removed_lines: int
    header: str  # The line starting with @@
    content: List[str]  # Full hunk content including header

    @property
    def end_line(self) -> int:
        """Calculate the end line based on the start line and context"""
        # The end line is approximated by start + max(added, removed)
        return self.start_line + max(self.added_lines, self.removed_lines)

    def __str__(self) -> str:
        return f"{self.file_path}:{self.start_line}"


def parse_diff_output(diff_output: str) -> Dict[str, List[Hunk]]:
    """
    Parse git diff output and return a dictionary mapping file paths to their hunks.

    Returns:
        Dict[file_path, List[Hunk]]
    """
    hunks_by_file: Dict[str, List[Hunk]] = {}

    lines = diff_output.split('\n')
    current_file = None
    current_hunk_lines = []
    current_hunk_header = None
    current_hunk_start = None
    current_hunk_added = 0
    current_hunk_removed = 0

    i = 0
    while i < len(lines):
        line = lines[i]

        # Match diff --git a/path b/path
        if line.startswith('diff --git '):
            # Save previous hunk if exists
            if current_file and current_hunk_lines:
                hunk = Hunk(
                    file_path=current_file,
                    start_line=current_hunk_start,
                    added_lines=current_hunk_added,
                    removed_lines=current_hunk_removed,
                    header=current_hunk_header,
                    content=current_hunk_lines
                )
                hunks_by_file.setdefault(current_file, []).append(hunk)
                current_hunk_lines = []

            # Extract file path from diff --git a/file b/file
            match = re.search(r'b/(.+)$', line)
            if match:
                current_file = match.group(1)

        # Match hunk header @@ -old_start,old_count +new_start,new_count @@
        elif line.startswith('@@'):
            # Save previous hunk if exists
            if current_file and current_hunk_lines:
                hunk = Hunk(
                    file_path=current_file,
                    start_line=current_hunk_start,
                    added_lines=current_hunk_added,
                    removed_lines=current_hunk_removed,
                    header=current_hunk_header,
                    content=current_hunk_lines
                )
                hunks_by_file.setdefault(current_file, []).append(hunk)

            # Parse hunk header
            current_hunk_header = line
            current_hunk_lines = [line]

            # Extract new file start line from +start,count
            match = re.search(r'\+(\d+)(?:,(\d+))?\s*@@', line)
            if match:
                current_hunk_start = int(match.group(1))
                count = match.group(2)
                # We'll count actual added/removed lines as we go
                current_hunk_added = 0
                current_hunk_removed = 0

        # Hunk content lines
        elif current_file and current_hunk_lines:
            # Stop at next file or hunk
            if line.startswith('diff --git ') or (line.startswith('@@') and line != current_hunk_header):
                # Don't consume this line, process it in next iteration
                i -= 1
                i += 1
                continue

            current_hunk_lines.append(line)

            # Count added/removed lines
            if line.startswith('+') and not line.startswith('+++'):
                current_hunk_added += 1
            elif line.startswith('-') and not line.startswith('---'):
                current_hunk_removed += 1

        i += 1

    # Save final hunk
    if current_file and current_hunk_lines:
        hunk = Hunk(
            file_path=current_file,
            start_line=current_hunk_start,
            added_lines=current_hunk_added,
            removed_lines=current_hunk_removed,
            header=current_hunk_header,
            content=current_hunk_lines
        )
        hunks_by_file.setdefault(current_file, []).append(hunk)

    return hunks_by_file


def find_hunks_by_address(hunks_by_file: Dict[str, List[Hunk]], address: str) -> List[Hunk]:
    """
    Find hunks matching a hunk address.

    Address formats:
    - file.py           -> all hunks in file
    - file.py:14        -> single hunk starting at line 14
    - file.py:14-67     -> all hunks whose start line falls within range

    Returns:
        List of matching hunks
    """
    # Parse address
    if ':' in address:
        file_path, line_spec = address.rsplit(':', 1)

        if '-' in line_spec:
            # Range: file.py:14-67
            start, end = line_spec.split('-', 1)
            start_line = int(start)
            end_line = int(end)

            if file_path not in hunks_by_file:
                return []

            return [h for h in hunks_by_file[file_path]
                    if start_line <= h.start_line <= end_line]
        else:
            # Single line: file.py:14
            target_line = int(line_spec)

            if file_path not in hunks_by_file:
                return []

            # Find hunk that starts at or contains this line
            matches = []
            for h in hunks_by_file[file_path]:
                if h.start_line == target_line:
                    matches.append(h)

            return matches
    else:
        # Whole file: file.py
        file_path = address
        return hunks_by_file.get(file_path, [])


def get_hunk_identifier(hunk: Hunk) -> str:
    """Get a stable identifier for a hunk (file:line)"""
    return f"{hunk.file_path}:{hunk.start_line}"
