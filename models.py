from pydantic import BaseModel
from typing import Optional


class JobConfig(BaseModel):
    name: Optional[str] = ''
    upstream: Optional[str] = ''
    provider: Optional[str] = ''
    command: Optional[str] = ''
    concurrent: Optional[int] = ''
    interval: Optional[int] = ''
    rsync_options: Optional[str] = ''
    memory_limit: Optional[str] = ''
    size_pattern: Optional[str] = ''
    addition_option: Optional[dict] = {}
    image: Optional[str] = ''
    data_size: Optional[str] = ''
    node: Optional[str] = ''
