import hashlib
import os
from pathlib import Path

os.environ.setdefault('TIKTOKEN_CACHE_DIR',str(Path(__file__).resolve().parents[1]/'vendor/tokenizer-cache'))

def count_text(text: str, encoding: str) -> dict:
    """Count this exact Unicode string; never normalize CR/LF or Unicode."""
    import tiktoken
    counter = tiktoken.get_encoding(encoding)  # fail explicitly; never silent fallback
    return {'tokens':len(counter.encode(text,disallowed_special=())), 'characters':len(text),
        'sha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),'text_encoding':'utf-8',
        'encoding':encoding,'method':'tiktoken_full_text','library_version':tiktoken.__version__,
        'newline_policy':'preserve_embedded_crlf_cr_lf','unicode_policy':'no_normalization',
        'target':'gpt-6.1-sol/xhigh','calibrated':False,
        'calibration':'估算 / 试用 / 目标 tokenizer 与实际入口预算未校准'}

def count_file(path: Path, encoding: str) -> dict:
    """Count final file bytes decoded as strict UTF-8, with no newline translation."""
    raw=Path(path).read_bytes()
    return count_text(raw.decode('utf-8',errors='strict'),encoding)
