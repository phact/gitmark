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
    is_rename: bool = False  # True if this is a pure rename with no content changes
    rename_from: str = None  # Original filename for renames
    rename_similarity: int = None  # Similarity index for renames (0-100)

    @property
    def end_line(self) -> int:
        """Calculate the end line based on the start line and context"""
        # The end line is approximated by start + max(added, removed)
        return self.start_line + max(self.added_lines, self.removed_lines)

    def __str__(self) -> str:
        if self.is_rename:
            return f"{self.rename_from} -> {self.file_path}"
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

    # Track rename metadata
    current_rename_from = None
    current_rename_similarity = None
    current_file_header_lines = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Match diff --git a/path b/path
        if line.startswith('diff --git '):
            # Save previous hunk or rename if exists
            if current_file:
                if current_hunk_lines:
                    # Regular hunk with content
                    hunk = Hunk(
                        file_path=current_file,
                        start_line=current_hunk_start,
                        added_lines=current_hunk_added,
                        removed_lines=current_hunk_removed,
                        header=current_hunk_header,
                        content=current_hunk_lines,
                        is_rename=bool(current_rename_from),
                        rename_from=current_rename_from,
                        rename_similarity=current_rename_similarity
                    )
                    hunks_by_file.setdefault(current_file, []).append(hunk)
                elif current_rename_from:
                    # Pure rename with no content changes
                    rename_hunk = Hunk(
                        file_path=current_file,
                        start_line=0,
                        added_lines=0,
                        removed_lines=0,
                        header="",
                        content=current_file_header_lines,
                        is_rename=True,
                        rename_from=current_rename_from,
                        rename_similarity=current_rename_similarity
                    )
                    hunks_by_file.setdefault(current_file, []).append(rename_hunk)

            # Reset state
            current_hunk_lines = []
            current_rename_from = None
            current_rename_similarity = None
            current_file_header_lines = []

            # Extract file path from diff --git a/file b/file
            # Use non-greedy match to handle paths correctly
            match = re.search(r'diff --git a/.+ b/(.+)$', line)
            if match:
                current_file = match.group(1)
                current_file_header_lines.append(line)

        # Match similarity index (indicates rename)
        elif line.startswith('similarity index '):
            match = re.search(r'similarity index (\d+)%', line)
            if match:
                current_rename_similarity = int(match.group(1))
            current_file_header_lines.append(line)

        # Match rename from
        elif line.startswith('rename from '):
            current_rename_from = line.replace('rename from ', '')
            current_file_header_lines.append(line)

        # Match rename to
        elif line.startswith('rename to '):
            current_file_header_lines.append(line)

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

    # Save final hunk or rename
    if current_file:
        if current_hunk_lines:
            hunk = Hunk(
                file_path=current_file,
                start_line=current_hunk_start,
                added_lines=current_hunk_added,
                removed_lines=current_hunk_removed,
                header=current_hunk_header,
                content=current_hunk_lines,
                is_rename=bool(current_rename_from),
                rename_from=current_rename_from,
                rename_similarity=current_rename_similarity
            )
            hunks_by_file.setdefault(current_file, []).append(hunk)
        elif current_rename_from:
            # Pure rename with no content changes
            rename_hunk = Hunk(
                file_path=current_file,
                start_line=0,
                added_lines=0,
                removed_lines=0,
                header="",
                content=current_file_header_lines,
                is_rename=True,
                rename_from=current_rename_from,
                rename_similarity=current_rename_similarity
            )
            hunks_by_file.setdefault(current_file, []).append(rename_hunk)

    return hunks_by_file


def find_hunks_by_address(hunks_by_file: Dict[str, List[Hunk]], address: str) -> List[Hunk]:
    """
    Find hunks matching a hunk address.

    Address formats:
    - file.py           -> all hunks in file (including renames TO this file)
    - old.py            -> all hunks renamed FROM this file
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
                    if start_line <= h.start_line <= end_line and not h.is_rename]
        else:
            # Single line: file.py:14
            target_line = int(line_spec)

            if file_path not in hunks_by_file:
                return []

            # Find hunk that starts at or contains this line
            matches = []
            for h in hunks_by_file[file_path]:
                if h.start_line == target_line and not h.is_rename:
                    matches.append(h)

            return matches
    else:
        # Whole file: file.py
        file_path = address

        # Check if this matches the new filename
        if file_path in hunks_by_file:
            return hunks_by_file[file_path]

        # Check if this matches an old filename (rename_from)
        matches = []
        for new_path, hunks in hunks_by_file.items():
            for hunk in hunks:
                if hunk.is_rename and hunk.rename_from == file_path:
                    matches.append(hunk)

        return matches


def get_hunk_identifier(hunk: Hunk) -> str:
    """Get a stable identifier for a hunk (file:line or old->new for renames)"""
    if hunk.is_rename and hunk.start_line == 0:
        # Pure rename
        return f"{hunk.rename_from} -> {hunk.file_path}"
    return f"{hunk.file_path}:{hunk.start_line}"
