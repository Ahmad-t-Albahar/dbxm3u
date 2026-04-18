#!/usr/bin/env python3
"""
M3U Playlist Fixer
Sorts files alphabetically and updates category format from " - " to " / "
"""

import re
import sys
from pathlib import Path


def parse_m3u(file_path):
    """Parse M3U file into list of entries"""
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    if not lines or not lines[0].strip().startswith('#EXTM3U'):
        print("Error: Not a valid M3U file")
        return None
    
    entries = []
    i = 1  # Skip #EXTM3U header
    
    while i < len(lines):
        line = lines[i].strip()
        
        if line.startswith('#EXTINF'):
            # This is an entry header
            if i + 1 < len(lines):
                url_line = lines[i + 1].strip()
                entries.append({
                    'extinf': line,
                    'url': url_line
                })
                i += 2
            else:
                i += 1
        else:
            i += 1
    
    return entries


def extract_filename(extinf_line):
    """Extract filename from EXTINF line for sorting"""
    # EXTINF format: #EXTINF:-1 group-title="...", filename
    match = re.search(r',\s*(.+)$', extinf_line)
    if match:
        return match.group(1).strip()
    return ""


def update_category(extinf_line):
    """Update category format from ' - ' to ' / '"""
    # Find group-title="..." portion
    match = re.search(r'group-title="([^"]+)"', extinf_line)
    if match:
        old_category = match.group(1)
        # Replace " - " with " / " but preserve actual hyphens in names
        new_category = old_category.replace(" - ", " / ")
        return extinf_line.replace(f'group-title="{old_category}"', f'group-title="{new_category}"')
    return extinf_line


def fix_m3u(input_path, output_path=None):
    """Fix M3U file: sort entries and update category format"""
    print(f"Reading: {input_path}")
    
    entries = parse_m3u(input_path)
    if entries is None:
        return False
    
    print(f"Found {len(entries)} entries")
    
    # Sort entries by filename
    print("Sorting entries alphabetically...")
    entries.sort(key=lambda x: extract_filename(x['extinf']).lower())
    
    # Update category format
    print("Updating category format...")
    for entry in entries:
        entry['extinf'] = update_category(entry['extinf'])
    
    # Write output
    if output_path is None:
        # Create backup and overwrite original
        backup_path = Path(input_path).with_suffix('.m3u.bak')
        print(f"Creating backup: {backup_path}")
        Path(input_path).rename(backup_path)
        output_path = input_path
    
    print(f"Writing fixed M3U to: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('#EXTM3U\n')
        for entry in entries:
            f.write(entry['extinf'] + '\n')
            f.write(entry['url'] + '\n')
    
    print(f"✓ Fixed M3U saved successfully!")
    print(f"  - Sorted {len(entries)} entries alphabetically")
    print(f"  - Updated category format (- to /)")
    
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python m3u_fixer.py <input.m3u> [output.m3u]")
        print("\nIf output is not specified, the input file will be updated (with .bak backup)")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not Path(input_file).exists():
        print(f"Error: File not found: {input_file}")
        sys.exit(1)
    
    success = fix_m3u(input_file, output_file)
    sys.exit(0 if success else 1)
