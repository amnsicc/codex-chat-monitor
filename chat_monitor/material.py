import hashlib
import os
from pathlib import Path

os.environ.setdefault('TIKTOKEN_CACHE_DIR',str(Path(__file__).resolve().parents[1]/'vendor/tokenizer-cache'))

def count_text(text: str, encoding: str) -> dict:
    import tiktoken
    counter = tiktoken.get_encoding(encoding)  # fail explicitly; never silent fallback
    return {'tokens':len(counter.encode(text,disallowed_special=())), 'characters':len(text),
        'sha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),'text_encoding':'utf-8',
        'encoding':encoding,'method':'tiktoken_full_text','library_version':tiktoken.__version__,
        'target':'gpt-6.1-sol/xhigh','calibrated':False,
        'calibration':'估算 / 试用 / 目标 tokenizer 与实际入口预算未校准'}
