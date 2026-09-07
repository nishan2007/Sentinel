from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class DeviceBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    brand: str = Field(default="meross", min_length=1, max_length=60)
    model: Optional[str] = Field(default=None, max_length=80)
    host: str = Field(min_length=1, max_length=255)
    device_key: Optional[str] = Field(default=None, max_length=12000)
    device_uuid: Optional[str] = Field(default=None, max_length=255)
    device_type: Optional[str] = Field(default=None, max_length=500)
    channel: int = Field(default=0, ge=0)
    is_enabled: bool = True


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    brand: Optional[str] = Field(default=None, min_length=1, max_length=60)
    model: Optional[str] = Field(default=None, max_length=80)
    host: Optional[str] = Field(default=None, min_length=1, max_length=255)
    device_key: Optional[str] = Field(default=None, max_length=12000)
    device_uuid: Optional[str] = Field(default=None, max_length=255)
    device_type: Optional[str] = Field(default=None, max_length=500)
    channel: Optional[int] = Field(default=None, ge=0)
    is_enabled: Optional[bool] = None


class DeviceOut(DeviceBase):
    id: int
    device_key: Optional[str] = Field(default=None, exclude=True)
    last_state: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class DeviceState(BaseModel):
    id: int
    name: str
    host: str
    channel: int
    is_on: bool
    is_open: Optional[bool] = None
    luminance: Optional[int] = None
    appliance: Optional[dict] = None
    raw: dict


class DeviceActionResult(BaseModel):
    id: int
    name: str
    host: str
    channel: int
    requested_state: Optional[bool] = None
    is_on: Optional[bool] = None
    is_open: Optional[bool] = None
    luminance: Optional[int] = None
    message: str


class BrightnessRequest(BaseModel):
    luminance: int = Field(ge=1, le=100)


class CudyRebootRequest(BaseModel):
    target: str = Field(default="main", pattern="^(main|satellites|all)$")


class SmartThingsCommandRequest(BaseModel):
    component: str = Field(default="main", min_length=1, max_length=120)
    capability: str = Field(min_length=1, max_length=160)
    command: str = Field(min_length=1, max_length=160)
    arguments: list = Field(default_factory=list)


class NestCommandRequest(BaseModel):
    command: str = Field(
        min_length=1,
        max_length=40,
        pattern="^(set-mode|set-heat|set-cool|set-range)$",
    )
    mode: Optional[str] = Field(default=None, max_length=20)
    heat_celsius: Optional[float] = Field(default=None, ge=5, le=35)
    cool_celsius: Optional[float] = Field(default=None, ge=5, le=35)


class NetworkScanRequest(BaseModel):
    subnet: Optional[str] = Field(
        default=None,
        description="CIDR subnet to scan, for example 10.1.1.0/24. Defaults to the host machine's current /24.",
    )
    port: int = Field(default=80, ge=1, le=65535)
    timeout_seconds: Optional[float] = Field(default=None, gt=0, le=5)


class NetworkScanResult(BaseModel):
    subnet: str
    port: int
    hosts: list[str]


class HealthResponse(BaseModel):
    status: str
    database: str


class ReliabilityHealthResponse(BaseModel):
    status: str
    background_refresh: dict
    credentials: list[dict]
    duplicate_candidates: list[dict]


class DuplicateRepairResponse(BaseModel):
    disabled: list[dict]
    kept: list[dict]
    note: str


class MerossCloudImportRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: SecretStr
    api_base_url: str = "https://iotx-us.meross.com"
    mfa_code: Optional[str] = Field(default=None, max_length=20)
    save_devices: bool = True


class MerossCloudImportedDevice(BaseModel):
    id: Optional[int] = None
    name: str
    model: Optional[str] = None
    host: Optional[str] = None
    mac_address: Optional[str] = None
    device_uuid: Optional[str] = None
    device_type: Optional[str] = None
    channels: list[int]
    saved: bool
    note: Optional[str] = None


class MerossCloudImportResponse(BaseModel):
    imported: list[MerossCloudImportedDevice]
    account_key_available: bool
    note: str


class SmartThingsImportRequest(BaseModel):
    token: Optional[SecretStr] = None
    client_id: Optional[str] = Field(default=None, max_length=500)
    client_secret: Optional[SecretStr] = None
    authorization_code: Optional[SecretStr] = None
    redirect_uri: str = Field(default="http://localhost:8088/setup/smartthings/oauth/callback", max_length=500)
    refresh_token: Optional[SecretStr] = None
    access_token: Optional[SecretStr] = None
    save_devices: bool = True
    exclude_overlaps: bool = True


class SmartThingsImportedDevice(BaseModel):
    id: Optional[int] = None
    name: str
    device_uuid: str
    device_type: Optional[str] = None
    model: Optional[str] = None
    capabilities: list[str]
    saved: bool
    skipped: bool = False
    skip_reason: Optional[str] = None


class SmartThingsImportResponse(BaseModel):
    imported: list[SmartThingsImportedDevice]
    skipped: list[SmartThingsImportedDevice]
    note: str


class SmartThingsOAuthStartRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=500)
    client_secret: SecretStr
    redirect_uri: str = Field(default="http://localhost:8088/setup/smartthings/oauth/callback", max_length=500)
    scopes: str = Field(default="r:devices:* x:devices:*", min_length=1, max_length=500)
    save_devices: bool = True
    exclude_overlaps: bool = True


class SmartThingsOAuthStartResponse(BaseModel):
    authorization_url: str
    state: str


class NestImportRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=255)
    client_id: Optional[str] = Field(default=None, max_length=500)
    client_secret: Optional[SecretStr] = None
    authorization_code: Optional[SecretStr] = None
    redirect_uri: str = Field(default="http://localhost:8088/setup/nest/oauth/callback", max_length=500)
    refresh_token: Optional[SecretStr] = None
    access_token: Optional[SecretStr] = None
    save_devices: bool = True
    exclude_overlaps: bool = True


class NestImportedDevice(BaseModel):
    id: Optional[int] = None
    name: str
    device_uuid: str
    device_type: Optional[str] = None
    model: Optional[str] = None
    room: Optional[str] = None
    saved: bool
    skipped: bool = False
    skip_reason: Optional[str] = None
    disabled_overlaps: list[str] = Field(default_factory=list)


class NestImportResponse(BaseModel):
    imported: list[NestImportedDevice]
    skipped: list[NestImportedDevice]
    note: str


class RingImportRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: SecretStr
    otp_code: Optional[str] = Field(default=None, max_length=20)
    save_devices: bool = True
    exclude_overlaps: bool = True


class RingImportedDevice(BaseModel):
    id: Optional[int] = None
    name: str
    device_uuid: str
    device_type: Optional[str] = None
    model: Optional[str] = None
    saved: bool
    skipped: bool = False
    skip_reason: Optional[str] = None
    disabled_overlaps: list[str] = Field(default_factory=list)


class RingImportResponse(BaseModel):
    imported: list[RingImportedDevice]
    skipped: list[RingImportedDevice]
    requires_2fa: bool = False
    note: str


class RingAlert(BaseModel):
    id: str
    kind: Optional[str] = None
    state: Optional[str] = None
    device_name: Optional[str] = None
    expires_at: Optional[float] = None


class RingAlertResponse(BaseModel):
    active: bool
    alerts: list[RingAlert]


class RingWebRtcOfferRequest(BaseModel):
    sdp_offer: str = Field(min_length=1, max_length=120000)


class RingWebRtcCandidateRequest(BaseModel):
    candidate: str = Field(min_length=1, max_length=120000)
    sdp_m_line_index: int = Field(ge=0, le=10)


class CameraCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    host: str = Field(min_length=1, max_length=255)
    model: Optional[str] = Field(default=None, max_length=120)
    username: Optional[str] = Field(default=None, max_length=255)
    password: Optional[SecretStr] = None
    main_stream_url: str = Field(min_length=1, max_length=2000)
    sub_stream_url: Optional[str] = Field(default=None, max_length=2000)
    recording_enabled: bool = True
    audio_enabled: bool = True


class CameraUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    host: Optional[str] = Field(default=None, min_length=1, max_length=255)
    model: Optional[str] = Field(default=None, max_length=120)
    username: Optional[str] = Field(default=None, max_length=255)
    password: Optional[SecretStr] = None
    main_stream_url: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    sub_stream_url: Optional[str] = Field(default=None, max_length=2000)
    recording_enabled: Optional[bool] = None
    audio_enabled: Optional[bool] = None


class CameraOut(BaseModel):
    id: int
    device_id: int
    name: str
    host: str
    model: Optional[str] = None
    username: Optional[str] = None
    main_stream_configured: bool
    sub_stream_configured: bool
    recording_enabled: bool
    audio_enabled: bool
    created_at: str
    updated_at: str


class CameraDiscoveryRequest(BaseModel):
    timeout_seconds: float = Field(default=3.0, ge=0.5, le=10)
    subnets: list[str] = Field(default_factory=list, max_length=16)
    scan_routed_subnets: bool = True


class PrinterDiscoveryRequest(BaseModel):
    timeout_seconds: float = Field(default=3.0, ge=0.5, le=10)
    subnets: list[str] = Field(default_factory=list, max_length=16)
    scan_routed_subnets: bool = True
    community: str = Field(default="public", min_length=1, max_length=120)
    model_hint: Optional[str] = Field(default=None, max_length=80)


class PrinterInkRefillRequest(BaseModel):
    color: str = Field(min_length=1, max_length=40)


class CameraOnvifProfilesRequest(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=80, ge=1, le=65535)
    username: Optional[str] = Field(default=None, max_length=255)
    password: Optional[SecretStr] = None


class CameraStorageUpdate(BaseModel):
    recording_root: str = Field(min_length=1, max_length=2000)
    capacity_gb: Optional[float] = Field(default=None, ge=1)
    reserve_gb: float = Field(default=10, ge=1)


class YaleImportRequest(BaseModel):
    access_token: Optional[SecretStr] = None
    email: Optional[str] = Field(default=None, max_length=255)
    password: Optional[SecretStr] = None
    verification_code: Optional[str] = Field(default=None, max_length=20)
    login_method: str = Field(default="email", pattern="^(email|phone)$")
    brand: str = Field(default="yale_access", max_length=40)
    save_devices: bool = True
    exclude_overlaps: bool = True


class YaleImportedDevice(BaseModel):
    id: Optional[int] = None
    name: str
    device_uuid: str
    house_id: Optional[str] = None
    saved: bool
    skipped: bool = False
    skip_reason: Optional[str] = None
    disabled_overlaps: list[str] = Field(default_factory=list)


class YaleImportResponse(BaseModel):
    imported: list[YaleImportedDevice]
    skipped: list[YaleImportedDevice]
    requires_validation: bool = False
    note: str
