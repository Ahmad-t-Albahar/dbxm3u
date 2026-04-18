import asyncio
import aiohttp
import dropbox
from dropbox.exceptions import ApiError
import os
import re
from typing import List, Tuple, Callable, Optional
from link_utils import get_or_create_shared_link as _get_or_create_shared_link, to_direct_stream_url

class AsyncM3UProcessor:
    def __init__(self, dbx: dropbox.Dropbox, progress_callback: Optional[Callable] = None, series_mode: bool = False, series_logo: str = "", extensions: Optional[List[str]] = None):
        """
        Initialize async processor
        
        Args:
            dbx: Dropbox client instance
            progress_callback: Function to call with progress updates (callable from any thread)
            series_mode: Enable VOD/Series formatting
            series_logo: URL for tvg-logo tag (used in series mode)
        """
        self.dbx = dbx
        self.progress_callback = progress_callback
        self.cancelled = False
        self.series_mode = series_mode
        self.series_logo = series_logo
        self.extensions = [e.lower() for e in (extensions or []) if isinstance(e, str) and e.strip()]
        
    def set_cancelled(self):
        """Signal cancellation from external thread"""
        self.cancelled = True
        
    async def collect_files(self, folder_paths: List[str]) -> List[Tuple[any, str]]:
        """
        Collect all audio files from specified folders
        
        Args:
            folder_paths: List of Dropbox folder paths to scan
            
        Returns:
            List of (FileMetadata, root_path) tuples
        """
        all_files = []
        audio_extensions = self.extensions
        
        if self.progress_callback:
            self.progress_callback('log', "Starting file collection...", 'info')
        
        for root_path in folder_paths:
            if self.cancelled:
                break
                
            try:
                if self.progress_callback:
                    self.progress_callback('log', f"Scanning folder: {root_path}", 'info')
                
                # Run blocking Dropbox API call in executor
                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(None, self.dbx.files_list_folder, root_path, True)
                
                def collect_entries(entries):
                    collected = []
                    for entry in entries:
                        if isinstance(entry, dropbox.files.FileMetadata):
                            if any(entry.name.lower().endswith(ext) for ext in audio_extensions):
                                collected.append((entry, root_path))
                    return collected
                
                all_files.extend(collect_entries(res.entries))
                
                # Handle pagination
                while res.has_more:
                    if self.cancelled:
                        break
                    res = await loop.run_in_executor(None, self.dbx.files_list_folder_continue, res.cursor)
                    all_files.extend(collect_entries(res.entries))
                    
            except Exception as e:
                if self.progress_callback:
                    self.progress_callback('log', f"Error scanning {root_path}: {e}", 'error')
                continue
        
        # Sort files by full path using a natural sort so numeric prefixes (e.g. "01 - 02")
        # appear in the expected order across series, audiobooks, etc.
        all_files.sort(key=lambda x: self._natural_sort_key(x[0].path_lower))
        
        if self.progress_callback:
            self.progress_callback('log', f"Found {len(all_files)} audio files (sorted alphabetically)", 'success')
            
        return all_files
    
    async def get_or_create_shared_link(self, file_path: str, semaphore: asyncio.Semaphore) -> Optional[str]:
        """
        Get existing or create new shared link for a file
        
        Args:
            file_path: Dropbox file path
            semaphore: Semaphore to limit concurrent API calls
            
        Returns:
            Shared link URL or None if failed
        """
        async with semaphore:
            loop = asyncio.get_event_loop()
            
            try:
                res = await loop.run_in_executor(
                    None,
                    lambda: _get_or_create_shared_link(self.dbx, file_path, direct_only=True).url,
                )
                return res
                
            except ApiError as api_err:
                # Handle "link already exists" error
                if hasattr(api_err.error, 'get_shared_link_already_exists'):
                    try:
                        res = await loop.run_in_executor(
                            None,
                            lambda: _get_or_create_shared_link(self.dbx, file_path, direct_only=False).url,
                        )
                        return res
                    except Exception:
                        return None
                return None
            except Exception:
                return None
    
    async def process_files(self, files: List[Tuple[any, str]], max_concurrent: int = 5) -> Tuple[List[str], dict]:
        """
        Process files and generate M3U lines
        
        Args:
            files: List of (FileMetadata, root_path) tuples
            max_concurrent: Maximum concurrent API calls
            
        Returns:
            Tuple of (m3u_lines, stats_dict)
        """
        m3u_lines = ["#EXTM3U"]
        stats = {
            'processed': 0,
            'skipped': 0,
            'total': len(files)
        }
        
        if self.progress_callback:
            self.progress_callback('set_total', len(files))
        
        # Semaphore to limit concurrent API calls
        semaphore = asyncio.Semaphore(max_concurrent)
        
        # Process files in batches to maintain order but allow concurrency
        batch_size = max_concurrent
        
        for i in range(0, len(files), batch_size):
            if self.cancelled:
                if self.progress_callback:
                    self.progress_callback('log', "Processing cancelled", 'warning')
                break
            
            batch = files[i:i + batch_size]
            tasks = []
            
            for entry, root_path in batch:
                task = self.process_single_file(entry, root_path, semaphore, i + len(tasks) + 1, len(files))
                tasks.append(task)
            
            # Process batch concurrently
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Add successful results to M3U
            for result in batch_results:
                if isinstance(result, Exception):
                    stats['skipped'] += 1
                elif result:
                    m3u_lines.append(result)
                    stats['processed'] += 1
                else:
                    stats['skipped'] += 1
        
        return m3u_lines, stats
    
    async def process_single_file(self, entry, root_path: str, semaphore: asyncio.Semaphore, 
                                  index: int, total: int) -> Optional[str]:
        """
        Process a single file and return M3U line
        
        Args:
            entry: FileMetadata object
            root_path: Root folder path
            semaphore: Semaphore for rate limiting
            index: Current file index
            total: Total files count
            
        Returns:
            M3U line string or None if failed
        """
        try:
            if self.progress_callback:
                self.progress_callback('update_progress', index, total, entry.name)
                self.progress_callback('log', f"Processing: {entry.name}", 'info')
            
            # Generate category from path with cleaner hierarchy
            relative_path = entry.path_display.replace(root_path, "").strip("/")
            category = os.path.dirname(relative_path) or os.path.basename(root_path)
            category = category.replace("/", " / ")

            series_group = os.path.basename(root_path)
            if relative_path:
                first_part = relative_path.split("/")[0].strip()
                if first_part:
                    series_group = first_part
            
            # Get or create shared link
            link = await self.get_or_create_shared_link(entry.path_lower, semaphore)
            
            if not link:
                if self.progress_callback:
                    self.progress_callback('log', f"Failed to get link for: {entry.name}", 'error')
                    self.progress_callback('increment_skipped')
                return None
            
            # Convert to streaming URL
            stream_url = to_direct_stream_url(link)
            
            if self.progress_callback:
                self.progress_callback('log', f"Created link for: {entry.name}", 'success')
                self.progress_callback('increment_processed')
            
            # Return M3U line based on mode
            if self.series_mode:
                # VOD/Series mode with enhanced metadata
                series_title, episode_string, display_name = self.format_as_series(series_group, entry.name)
                return (f'#EXTINF:-1 tvg-id="" tvg-name="{display_name}" '
                       f'tvg-logo="{self.series_logo}" group-title="{series_title}", '
                       f'{display_name}\n{stream_url}')
            else:
                # Standard mode
                return f'#EXTINF:-1 group-title="{category}", {entry.name}\n{stream_url}'
            
        except Exception as e:
            if self.progress_callback:
                self.progress_callback('log', f"Error processing {entry.name}: {e}", 'error')
                self.progress_callback('increment_skipped')
            return None
    
    def parse_season_episode(self, filename: str) -> Tuple[Optional[int], Optional[int], str]:
        """Best-effort extraction of season/episode + a human title.

        This is intentionally generic: it tries common patterns often used for
        episodic audio/video naming, while still producing reasonable output
        for non-TV collections.

        Returns:
            (season_int|None, episode_int|None, cleaned_title)
        """
        name_without_ext = os.path.splitext(filename)[0]

        # Common: S01E02 / S01 E02 / S01.E02
        match = re.search(r'\bS(\d{1,2})\s*[-_. ]?\s*E(\d{1,3})\b', name_without_ext, re.IGNORECASE)
        if match:
            season = int(match.group(1))
            episode = int(match.group(2))
            cleaned = re.sub(r'\bS\d{1,2}\s*[-_. ]?\s*E\d{1,3}\b', '', name_without_ext, flags=re.IGNORECASE)
            cleaned = re.sub(r'^[\s._-]+|[\s._-]+$', '', cleaned)
            return season, episode, cleaned

        # Common: 01 - 02 Title (season, episode)
        match = re.match(r'^\s*(\d{1,2})\s*[-_. ]+\s*(\d{1,3})(?:\s*[-_. ]+\s*)?(.*)$', name_without_ext)
        if match:
            season = int(match.group(1))
            episode = int(match.group(2))
            cleaned = (match.group(3) or '').strip()
            cleaned = re.sub(r'^[\s._-]+|[\s._-]+$', '', cleaned)
            return season, episode, cleaned

        # "Part 1" -> episode 1
        match = re.search(r'\bPart\s*(\d+)\b', name_without_ext, re.IGNORECASE)
        if match:
            episode = int(match.group(1))
            cleaned = re.sub(r'\bPart\s*\d+\b', '', name_without_ext, flags=re.IGNORECASE)
            cleaned = re.sub(r'^[\s._-]+|[\s._-]+$', '', cleaned)
            return None, episode, cleaned

        # "...P05" -> episode 5
        match = re.search(r'\bP(\d+)\b', name_without_ext, re.IGNORECASE)
        if match:
            episode = int(match.group(1))
            cleaned = re.sub(r'\bP\d+\b', '', name_without_ext, flags=re.IGNORECASE)
            cleaned = re.sub(r'^[\s._-]+|[\s._-]+$', '', cleaned)
            return None, episode, cleaned

        # Leading digits "02 Title" -> episode 2
        match = re.match(r'^\s*(\d{1,3})\s+(.+)$', name_without_ext)
        if match:
            episode = int(match.group(1))
            cleaned = match.group(2).strip()
            cleaned = re.sub(r'^[\s._-]+|[\s._-]+$', '', cleaned)
            return None, episode, cleaned

        # Fallback: no numbering detected
        return None, None, name_without_ext.strip()

    def _natural_sort_key(self, value: str):
        parts = re.split(r'(\d+)', value.lower())
        key = []
        for part in parts:
            if part.isdigit():
                key.append(int(part))
            else:
                key.append(part)
        return key
    
    def format_as_series(self, category: str, filename: str) -> Tuple[str, str, str]:
        """
        Format category and filename for VOD/Series mode
        
        Args:
            category: Original category/group-title
            filename: Original filename
            
        Returns:
            Tuple of (series_title, episode_string, display_name)
        """
        series_title = category
        
        season_num, episode_num, _cleaned_title = self.parse_season_episode(filename)

        base_name = os.path.splitext(filename)[0].strip()

        # Keep Sxx Exx only as an optional hint for IPTV clients that may use it,
        # but never override the visible name with a generic label.
        if season_num is not None and episode_num is not None:
            episode_string = f"S{season_num:02d} E{episode_num:02d}"
        else:
            episode_string = ""

        display_name = base_name
        
        return series_title, episode_string, display_name


async def run_async_processing(dbx: dropbox.Dropbox, folder_paths: List[str], 
                               progress_callback: Optional[Callable] = None,
                               max_concurrent: int = 5,
                               series_mode: bool = False,
                               series_logo: str = "",
                               extensions: Optional[List[str]] = None) -> Tuple[List[str], dict]:
    """
    Main entry point for async processing
    
    Args:
        dbx: Dropbox client instance
        folder_paths: List of folder paths to process
        progress_callback: Callback function for progress updates
        max_concurrent: Maximum concurrent API calls
        series_mode: Enable VOD/Series formatting
        series_logo: URL for tvg-logo tag
        
    Returns:
        Tuple of (m3u_lines, stats_dict)
    """
    processor = AsyncM3UProcessor(dbx, progress_callback, series_mode, series_logo, extensions=extensions)
    
    # Collect all files
    files = await processor.collect_files(folder_paths)
    
    if not files:
        return ["#EXTM3U"], {'processed': 0, 'skipped': 0, 'total': 0}
    
    # Process files
    m3u_lines, stats = await processor.process_files(files, max_concurrent)
    
    return m3u_lines, stats
