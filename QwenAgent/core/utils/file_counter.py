"""File line counter utility."""

def count_lines(path: str) -> int:
    """
    Count lines in a file.
    
    Args:
        path: Path to file
        
    Returns:
        Number of lines or -1 if file not found
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return sum(1 for _ in f)
    except FileNotFoundError:
        return -1