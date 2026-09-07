from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Device:
    id: int
    name: str
    brand: str
    model: Optional[str]
    host: str
    device_key: Optional[str]
    device_uuid: Optional[str]
    device_type: Optional[str]
    channel: int
    is_enabled: bool
    last_state: Optional[str]
    created_at: str
    updated_at: str
