from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer

from .models import (
    ActStatus,
    ChatMessageType,
    ContextLinkCategory,
    InterestValue,
    OrgEventType,
    PartnerRole,
    TaskApprovalStatus,
    TaskRecurrence,
    TaskSource,
    TaskVisibility,
)
from .timeutil import utc_iso

# API timestamps are stored as naive UTC — always emit with Z so browsers
# treat them as UTC instead of local wall time.
UtcDateTime = Annotated[
    datetime,
    PlainSerializer(utc_iso, return_type=str, when_used="json"),
]
UtcDateTimeOptional = Annotated[
    datetime | None,
    PlainSerializer(utc_iso, return_type=str | None, when_used="json"),
]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    mfa_required: bool = False
    mfa_token: str | None = None
    email_hint: str | None = None


class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str = Field(min_length=4, max_length=12)


class MfaResendRequest(BaseModel):
    mfa_token: str


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=64)


class UserLogin(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str


class UserEmailUpdate(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=6, max_length=128)


class UserUsernameUpdate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class PartnerUsernameUpdate(BaseModel):
    username: str = Field(min_length=3, max_length=64)


class ClaimEmailRequest(BaseModel):
    username: str
    password: str
    email: str = Field(min_length=5, max_length=255)


class AuthPublicConfig(BaseModel):
    mfa_required: bool
    allow_public_register: bool
    smtp_configured: bool


class UserOut(BaseModel):
    id: str
    username: str
    email: str = ""
    email_set: bool = False
    onboarding_completed: bool = False
    mfa_required: bool = False
    biological_sex: str = ""

    class Config:
        from_attributes = True


class UserSexUpdate(BaseModel):
    biological_sex: Literal["male", "female", "intersex", "prefer_not_to_say"]


class DynamicCreate(BaseModel):
    name: str = Field(default="Our dynamic", max_length=120)
    role: PartnerRole


class DynamicJoin(BaseModel):
    invite_code: str = Field(min_length=4, max_length=12)
    role: PartnerRole
    display_name: str | None = Field(default=None, max_length=64)


class PartnerOut(BaseModel):
    id: str
    display_name: str
    username: str = ""
    role: PartnerRole
    survey_submitted: bool
    survey_submitted_at: datetime | None
    share_kinks: bool = False
    interview_completed: bool = False
    spti_completed: bool = False
    chastity_enabled: bool = False
    chastity_max_lock_hours: int | None = None
    is_you: bool = False


class DynamicOut(BaseModel):
    id: str
    name: str
    invite_code: str
    created_at: datetime
    partners: list[PartnerOut]
    shared_llm_configured: bool = False
    enabled_features: list[str] = []

    class Config:
        from_attributes = True


class DynamicFeaturesOut(BaseModel):
    enabled: list[str]
    core: list[str]
    optional: list[dict]


class DynamicFeaturesUpdate(BaseModel):
    enabled_optional: list[str]


class SharedLlmOut(BaseModel):
    configured: bool
    provider: str
    model: str
    api_key_hint: str | None
    set_by_display_name: str | None


class SharedLlmUpdate(BaseModel):
    provider: str
    model: str = ""
    api_key: str = ""
    use_for_dynamic: bool = True


class OnboardingStatusOut(BaseModel):
    onboarding_completed: bool
    has_dynamic: bool
    dynamic_id: str | None
    dynamic_name: str | None = None
    invite_code: str | None = None
    shared_llm_configured: bool = False
    api_skipped: bool = False
    spti_completed: bool
    spti_skipped: bool = False
    survey_submitted: bool
    survey_skipped: bool = False


class OnboardingCompleteOut(BaseModel):
    onboarding_completed: bool
    dynamic_id: str


class SptiUpdate(BaseModel):
    results: str = ""
    skipped: bool = False


class SptiOut(BaseModel):
    completed: bool
    skipped: bool
    results: str = ""
    completed_at: datetime | None = None


class ChastityLimitProposalCreate(BaseModel):
    for_membership_id: str
    proposed_max_hours: int = Field(ge=1, le=8760)
    rationale: str = ""


class ChastityLimitProposalOut(BaseModel):
    id: str
    for_display_name: str
    proposed_max_hours: int
    rationale: str
    status: str
    proposed_by_display_name: str
    created_at: datetime
    reviewed_at: datetime | None

    class Config:
        from_attributes = True


class SuggestedAgreementOut(BaseModel):
    title: str
    content: str


class SuggestedAgreementsOut(BaseModel):
    items: list[SuggestedAgreementOut]
    ready: bool
    reason: str = ""


class KinkExamplesOut(BaseModel):
    examples: list[str]


class InterestOut(BaseModel):
    id: str
    display_copy: str
    submissive_display_override: str | None
    description: str | None
    display_order: int


class InterestCategoryOut(BaseModel):
    id: str
    name: str
    description: str | None
    display_order: int
    interests: list[InterestOut]


class InterestResponsesUpdate(BaseModel):
    responses: dict[str, InterestValue]


class SubmissionSummary(BaseModel):
    submitted: bool
    submitted_at: datetime | None
    response_count: int


class InterestsBundle(BaseModel):
    categories: list[InterestCategoryOut]
    your_responses: dict[str, InterestValue]
    partner_responses: dict[str, InterestValue] = {}
    partner_submission: SubmissionSummary
    your_submission: SubmissionSummary
    your_share_kinks: bool = False
    partner_share_kinks: bool = False
    sharing_enabled: bool = False
    overlap: list[str]
    overlap_details: list[InterestOut]


class ShareKinksUpdate(BaseModel):
    share_kinks: bool


class TaskCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    visibility: TaskVisibility = TaskVisibility.visible
    tags: list[str] = Field(default_factory=list)
    recurrence: TaskRecurrence = TaskRecurrence.none
    due_at: datetime | None = None
    # Relative due: amount + unit → due_at if due_at not set
    due_in_amount: int | None = Field(default=None, ge=1, le=10000)
    due_in_unit: Literal["minutes", "hours", "days", "weeks"] | None = None
    assigned_to_membership_id: str | None = None
    is_private: bool = False


class TaskItemCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    visibility: TaskVisibility = TaskVisibility.visible
    tags: list[str] = Field(default_factory=list)
    recurrence: TaskRecurrence = TaskRecurrence.none
    due_at: datetime | None = None
    due_in_amount: int | None = Field(default=None, ge=1, le=10000)
    due_in_unit: Literal["minutes", "hours", "days", "weeks"] | None = None
    assigned_to_membership_id: str | None = None
    is_private: bool = False
    task_list_id: str | None = None
    source: TaskSource = TaskSource.sub


class TaskListCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    tasks: list[TaskCreate] = Field(min_length=1)
    # Defaults applied to each task when not set per-task
    assigned_to_membership_id: str | None = None
    is_private: bool = False
    due_in_amount: int | None = Field(default=None, ge=1, le=10000)
    due_in_unit: Literal["minutes", "hours", "days", "weeks"] | None = None


class InboxItemOut(BaseModel):
    id: str
    kind: str
    title: str
    body: str = ""
    occurred_at: datetime | None = None
    path: str = ""
    task_id: str | None = None


class InboxOut(BaseModel):
    acked_at: datetime | None = None
    items: list[InboxItemOut] = Field(default_factory=list)


class TaskOut(BaseModel):
    id: str
    position: int
    content: str
    visibility: TaskVisibility
    completed_at: datetime | None
    hidden: bool = False
    tags: list[str] = Field(default_factory=list)
    approval_status: TaskApprovalStatus
    source: TaskSource
    recurrence: TaskRecurrence
    due_at: datetime | None
    next_due_at: datetime | None
    act_id: str | None = None
    assigned_to_membership_id: str | None = None
    assigned_to_display_name: str | None = None
    is_private: bool = False
    public_code_word: str = ""
    google_task_id: str = ""
    google_synced: bool = False
    paused: bool = False
    makeup_status: str = "none"
    makeup_note: str = ""
    makeup_requested_at: datetime | None = None
    makeup_granted_at: datetime | None = None

    class Config:
        from_attributes = True


class TaskItemUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    tags: list[str] | None = None
    paused: bool | None = None
    recurrence: TaskRecurrence | None = None


class TaskMakeupRequestIn(BaseModel):
    note: str = Field(default="", max_length=2000)


class TaskMakeupReviewIn(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=4000)


class TaskMakeupAssistOut(BaseModel):
    note: str


class TaskBulkActionIn(BaseModel):
    task_ids: list[str] = Field(min_length=1)
    action: Literal["pause", "unpause", "remove_future", "apply_tag"]
    tag: str | None = Field(default=None, max_length=80)


class GoogleTasksStatusOut(BaseModel):
    configured: bool
    connected: bool
    list_id: str = "@default"


class GoogleTasksSyncOut(BaseModel):
    pushed: int = 0
    completed_from_google: int = 0
    errors: list[str] = Field(default_factory=list)


class TaskCalendarItem(BaseModel):
    task_id: str
    task_list_id: str
    list_title: str
    content: str
    tags: list[str]
    due_at: datetime
    recurrence: TaskRecurrence
    approval_status: TaskApprovalStatus
    source: TaskSource
    completed_at: datetime | None


class TaskCalendarOut(BaseModel):
    items: list[TaskCalendarItem]


class ActToTaskCreate(BaseModel):
    recurrence: TaskRecurrence = TaskRecurrence.weekly
    tags: list[str] = Field(default_factory=list)
    due_at: datetime | None = None


class TagPresetsOut(BaseModel):
    presets: list[str]
    task_presets: list[str] = Field(default_factory=list)


class TagPresetsUpdate(BaseModel):
    presets: list[str] | None = None
    task_presets: list[str] | None = None


class ChatSettingsOut(BaseModel):
    retain_history: bool
    e2e_enabled: bool
    key_configured: bool = False
    expire_hours: int
    system_events: bool
    push_enabled: bool
    you_are_dominant: bool = False
    chastity_sub_can_delete_breaks: bool = True


class ChatSettingsUpdate(BaseModel):
    retain_history: bool | None = None
    e2e_enabled: bool | None = None
    expire_hours: int | None = Field(default=None, ge=1, le=24 * 90)
    system_events: bool | None = None
    push_enabled: bool | None = None
    chastity_sub_can_delete_breaks: bool | None = None


class SettingsRequestCreate(BaseModel):
    setting_key: str = Field(min_length=1, max_length=80)
    setting_label: str = Field(default="", max_length=200)
    requested_value: object | None = None
    note: str = Field(default="", max_length=1000)


class SettingsRequestResolve(BaseModel):
    decision: Literal["deny", "approve"]
    value: object | None = None


class DynamicPolicyOut(BaseModel):
    you_are_dominant: bool
    chastity_sub_can_delete_breaks: bool
    feelings_prompt_mode: str
    feelings_require_end_of_day: bool
    chat_system_events: bool
    chat_retain_history: bool
    enabled_features: list[str]
    locked_setting_keys: list[str]


class PushPublicKeyOut(BaseModel):
    public_key: str
    configured: bool


class PushSubscribeIn(BaseModel):
    endpoint: str = Field(min_length=8, max_length=512)
    keys: dict[str, str]
    expiration_time: int | None = None


class NativePushSubscribeIn(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    platform: str = Field(default="android", max_length=32)
    app_id: str = Field(default="ubetra-android", max_length=64)


class PushStatusOut(BaseModel):
    configured: bool
    push_enabled: bool
    subscription_count: int
    native_configured: bool = False
    native_subscription_count: int = 0


class PushSettingsUpdate(BaseModel):
    push_enabled: bool


class ChatKeyShareIn(BaseModel):
    key: str = Field(min_length=16, max_length=4096)


class ChatKeyShareOut(BaseModel):
    code: str
    expires_at: datetime
    redeem_hint: str


class ChatKeyRedeemIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)


class ChatKeyRedeemOut(BaseModel):
    key: str


class ChatSharedKeyOut(BaseModel):
    key: str
    configured: bool = True


class ChatSharedKeyIn(BaseModel):
    key: str = Field(min_length=16, max_length=4096)


class ChatMessageCreate(BaseModel):
    body: str = ""
    body_encrypted: str = ""
    message_type: ChatMessageType = ChatMessageType.text
    image_data: str = ""
    image_blurred: bool = True
    image_locked: bool = False
    vault_image_encrypted: str = ""
    save_to_vault: bool = True
    action: str = ""
    payload: dict = Field(default_factory=dict)


class ChatMessageOut(BaseModel):
    id: str
    sender_display_name: str
    is_yours: bool
    message_type: ChatMessageType
    body: str
    body_encrypted: str
    image_data: str
    image_blurred: bool
    image_locked: bool = False
    image_unlock_granted: bool = False
    action: str = ""
    payload: dict = {}
    created_at: datetime

    class Config:
        from_attributes = True


class ImageUnlockResolve(BaseModel):
    decision: Literal["approve", "deny"]


class TaskListOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    tasks: list[TaskOut]
    status: Literal["active", "completed"] = "active"

    class Config:
        from_attributes = True


class CoreKnowledgeUpdate(BaseModel):
    relationship_context: str = ""
    distance: str = ""
    space: str = ""
    budget: str = ""
    about_you: str = ""
    desires: str = ""


class CoreKnowledgeOut(CoreKnowledgeUpdate):
    submitted: bool
    updated_at: datetime
    is_yours: bool = True
    partner_display_name: str | None = None
    interview_completed: bool = False

    class Config:
        from_attributes = True


class CoreKnowledgeSummary(BaseModel):
    partner_display_name: str
    role: PartnerRole
    submitted: bool
    field_count: int


class CoreKnowledgeFieldOption(BaseModel):
    key: str
    label: str
    has_content: bool


class CoreKnowledgePartnerStatus(BaseModel):
    display_name: str
    submitted: bool
    updated_at: datetime | None = None


class AgreementOut(BaseModel):
    id: str
    title: str
    approved_content: str
    pending_content: str
    has_approved: bool
    has_pending: bool
    pending_by_display_name: str | None
    pending_at: datetime | None
    approved_at: datetime | None
    position: int
    created_at: datetime

    class Config:
        from_attributes = True


class AgreementListOut(BaseModel):
    agreements: list[AgreementOut]
    approved_count: int
    pending_count: int
    you_are_dominant: bool


class AgreementCreate(BaseModel):
    title: str = Field(default="", max_length=200)
    content: str = Field(min_length=1, max_length=50000)
    approve_now: bool = False


class AgreementUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content: str = Field(min_length=1, max_length=50000)
    approve_now: bool = False


class ActRequestIn(BaseModel):
    knowledge_focus: list[str] = Field(default_factory=list)
    act_type_id: str = ""


class ActCategoryOut(BaseModel):
    id: str
    title: str
    description: str
    example_acts: list[str] = Field(default_factory=list)


class MenuSummariesOut(BaseModel):
    org_tracking: str = ""
    chastity: str = ""
    tasks: str = ""
    acts: str = ""


class AssistantStatusOut(BaseModel):
    llm_configured: bool
    llm_provider: str
    llm_model: str
    using_server_default: bool
    your_core_knowledge_submitted: bool
    partner_core_knowledge_submitted: bool
    your_survey_submitted: bool
    partner_survey_submitted: bool
    your_interview_completed: bool = False
    partner_interview_completed: bool = False
    shared_interest_count: int
    active_act_id: str | None = None


class LlmProviderOption(BaseModel):
    id: str
    label: str
    description: str
    policy_notes: str = ""
    default_model: str
    models: list[str]
    key_url: str


class LlmSettingsOut(BaseModel):
    provider: str
    model: str
    api_key_set: bool
    api_key_hint: str | None
    configured: bool
    using_server_default: bool
    server_env_configured: bool
    active_key_source: str = "account"
    active_api_key_hint: str | None = None
    shared_dynamics_count: int = 0
    # Dynamic shared key (same for both partners) — independent of account provider UI
    shared_configured: bool = False
    shared_provider: str | None = None
    shared_model: str | None = None
    shared_api_key_hint: str | None = None
    active_dynamic_id: str | None = None


class LlmSettingsUpdate(BaseModel):
    provider: str
    model: str = ""
    api_key: str | None = None
    clear_api_key: bool = False


class LlmTestOut(BaseModel):
    ok: bool
    provider: str
    model: str
    active_key_source: str
    reply: str = ""
    detail: str = ""


class ActOfSubmissionOut(BaseModel):
    id: str
    status: ActStatus
    hint_text: str
    act_type_id: str = ""
    act_type_title: str = ""
    sub_response_text: str | None
    sub_rating: int | None
    dom_verified: bool | None
    dom_notes: str | None
    requested_by_display_name: str
    created_at: datetime
    completed_at: datetime | None
    verified_at: datetime | None

    class Config:
        from_attributes = True


class ActRespondRequest(BaseModel):
    response_text: str = Field(min_length=1, max_length=8000)
    rating: int | None = Field(default=None, ge=1, le=5)


class ActVerifyRequest(BaseModel):
    approved: bool
    notes: str = ""


class AssistantTaskCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    tags: list[str] = Field(default_factory=list)
    recurrence: TaskRecurrence = TaskRecurrence.none
    due_at: datetime | None = None


class RecommendationOut(BaseModel):
    category_name: str
    hint_text: str
    response_text: str


class PlaytimeSubjectsRequest(BaseModel):
    effort: str  # low | med | high
    lean: str  # sub | dom | equal
    exclude_subjects: list[str] = []
    note: str = ""


class PlaytimeSubjectOut(BaseModel):
    title: str
    blurb: str = ""


class PlaytimeSubjectsOut(BaseModel):
    effort: str
    lean: str
    subjects: list[PlaytimeSubjectOut]


class JournalAssistContextFlags(BaseModel):
    stories: bool = False
    journals: bool = False
    scenes: bool = False
    agreements: bool = False
    tracking: bool = False


class PlaytimeSceneRequest(BaseModel):
    effort: str
    lean: str
    subject: str
    avoid_summary: str = ""
    note: str = ""
    context_flags: JournalAssistContextFlags | None = None


class PlaytimeSceneOut(BaseModel):
    effort: str
    lean: str
    subject: str
    title: str
    summary: str = ""
    body: str


class PlaytimeFeedbackRequest(BaseModel):
    effort: str
    lean: str
    subject: str
    scene_title: str = ""
    scene_summary: str = ""
    rating: int | None = None  # 1-5 when accepting
    reject: bool = False
    note: str = ""
    regenerate: bool = False


class PlaytimeFeedbackOut(BaseModel):
    recorded: bool = True
    message: str = ""
    scene: PlaytimeSceneOut | None = None


class SpinWheelSuggestRequest(BaseModel):
    faces: int = Field(default=6, ge=2, le=20)


class SpinWheelOptionOut(BaseModel):
    id: str
    title: str
    description: str = ""
    value_label: str = ""
    uses_dice: bool = True
    share_with_sub: bool = True
    fail_behavior: str = "respin"
    once_only: bool = False
    source: str = "preset"


class SpinWheelSuggestOut(BaseModel):
    faces: int
    dominant_name: str
    submissive_name: str
    days_since_last_orgasm: int | None = None
    options: list[SpinWheelOptionOut]


class SpinPostOrgasmTasksOut(BaseModel):
    dominant_name: str
    submissive_name: str
    days_since_last_orgasm: int | None = None
    tasks: list[dict]


class SpinNextWaitRequest(BaseModel):
    verified_wait_days: int = Field(ge=1, le=3650)
    direction: str  # longer | shorter


class SpinNextWaitOut(BaseModel):
    verified_wait_days: int
    direction: str
    day_choices: list[int]


class SpinMidgameCheckOut(BaseModel):
    in_play_relevant: bool = True
    days_since_last_orgasm: int | None = None
    full_orgasms: list[dict] = []


class SpinGameOut(BaseModel):
    id: str | None = None
    status: str = "none"
    started_at: str | None = None
    updated_at: str | None = None
    public: dict = {}
    secret: dict | None = None
    your_role: str
    can_spin_post_orgasm: bool = False


class SpinPostOrgasmSetup(BaseModel):
    task_pool: list[dict]
    task_count: int = 1
    use_wheel: bool = True
    spinner: str = "either"  # dom | sub | either
    manual_picks: list[dict] = []


class SpinPostOrgasmSpinOut(BaseModel):
    picked: dict
    results: list[dict]
    complete: bool


class SpinFulfillRequest(BaseModel):
    kind: Literal["dom_orgasms", "wait_lockup", "sub_full_orgasm"]
    count: int = 1
    unit: str = "days"  # days | weeks (for wait_lockup)


class SpinFulfillOut(BaseModel):
    ok: bool = True
    kind: str
    count: int | None = None
    days: int | None = None
    extended: bool | None = None
    planned_end_at: str | None = None
    for_display_name: str | None = None


class InterviewMessageOut(BaseModel):
    id: str
    role: Literal["assistant", "user"]
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class InterviewOut(BaseModel):
    completed: bool
    summary: str
    message_count: int
    can_mark_complete: bool = False
    messages: list[InterviewMessageOut]


class InterviewReplyIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class ContextLinkCreate(BaseModel):
    """Legacy Drive URL create — prefer multipart upload."""

    category: ContextLinkCategory | None = None
    subject: str = "other"
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(default="", max_length=2000)
    notes: str = ""
    use_for_ai: bool = True
    partner_visible: bool = True
    text_content: str = ""


class ContextLinkUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    subject: str | None = None
    notes: str | None = None
    use_for_ai: bool | None = None
    partner_visible: bool | None = None


class ContextLinkOut(BaseModel):
    id: str
    category: ContextLinkCategory
    subject: str = "other"
    title: str
    url: str = ""
    notes: str
    filename: str = ""
    mime_type: str = ""
    file_size: int = 0
    use_for_ai: bool = True
    partner_visible: bool = True
    is_private_to_others: bool = False
    has_fetched_text: bool
    text_preview: str = ""
    added_by_display_name: str
    added_by_membership_id: str = ""
    created_at: datetime

    class Config:
        from_attributes = True


class ContextLinkCategoryOut(BaseModel):
    id: str
    label: str


class JournalEntryCreate(BaseModel):
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=50000)
    use_for_ai: bool = True
    llm_assisted: bool = False
    partner_visible: bool = True


class JournalEntryUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=50000)
    use_for_ai: bool | None = None
    partner_visible: bool | None = None


class JournalEntryOut(BaseModel):
    id: str
    title: str
    body: str
    use_for_ai: bool
    llm_assisted: bool
    partner_visible: bool = True
    is_private_to_others: bool = False
    author_display_name: str
    membership_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class JournalAssistRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    draft: str = Field(default="", max_length=50000)
    context_flags: JournalAssistContextFlags = Field(default_factory=JournalAssistContextFlags)


class JournalAssistOut(BaseModel):
    text: str


class JournalDommeReviewRequest(BaseModel):
    post_system_event: bool = False


class JournalDommeReviewOut(BaseModel):
    summary: str


class OrgasmDetailCreate(BaseModel):
    tags: list[str] = Field(default_factory=list)


class OrgasmDetailOut(BaseModel):
    id: str
    tags: list[str]
    position: int

    class Config:
        from_attributes = True


class OrgTrackingEntryCreate(BaseModel):
    for_membership_id: str
    event_type: OrgEventType
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    orgasms: list[OrgasmDetailCreate] = Field(default_factory=list)
    occurred_at: datetime | None = None
    ended_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    dominant_time_at: datetime | None = None
    submissive_time_at: datetime | None = None
    location: str = Field(default="", max_length=120)
    initiated_by_membership_id: str | None = None
    protection: str = Field(default="", max_length=32)
    satisfaction: int | None = Field(default=None, ge=1, le=5)
    edging_count: int | None = Field(default=None, ge=0, le=100)
    notes_private: bool = False


class OrgTrackingEntryUpdate(BaseModel):
    event_type: OrgEventType | None = None
    notes: str | None = None
    tags: list[str] | None = None
    orgasms: list[OrgasmDetailCreate] | None = None
    occurred_at: datetime | None = None
    ended_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    dominant_time_at: datetime | None = None
    submissive_time_at: datetime | None = None
    location: str | None = Field(default=None, max_length=120)
    initiated_by_membership_id: str | None = None
    protection: str | None = Field(default=None, max_length=32)
    satisfaction: int | None = Field(default=None, ge=1, le=5)
    edging_count: int | None = Field(default=None, ge=0, le=100)
    notes_private: bool | None = None


class OrgTrackingEntryOut(BaseModel):
    id: str
    for_membership_id: str
    for_display_name: str
    event_type: OrgEventType
    notes: str
    tags: list[str]
    orgasms: list[OrgasmDetailOut] = Field(default_factory=list)
    occurred_at: UtcDateTime
    ended_at: UtcDateTimeOptional = None
    duration_minutes: int | None = None
    dominant_time_at: UtcDateTimeOptional = None
    submissive_time_at: UtcDateTimeOptional = None
    location: str = ""
    initiated_by_membership_id: str | None = None
    initiated_by_display_name: str | None = None
    protection: str = ""
    satisfaction: int | None = None
    edging_count: int | None = None
    notes_private: bool = False
    notes_hidden: bool = False
    logged_by_display_name: str
    session_id: str | None = None
    during_lockup: bool = False
    during_own_lockup: bool = False
    locked_partner_names: list[str] = Field(default_factory=list)
    session_entry_count: int = 1


class OrgTrackingPrefsOut(BaseModel):
    fields: list[dict]
    metrics: list[dict]


class OrgTrackingPrefsUpdate(BaseModel):
    fields: dict[str, bool] = Field(default_factory=dict)
    metrics: dict[str, bool] = Field(default_factory=dict)


class OrgTrackingStatsOut(BaseModel):
    partners: list[dict[str, str | int]]
    recent_orgasm_label: str
    cumulative_30d: list[dict] = Field(default_factory=list)


class HistoryWeekBucket(BaseModel):
    label: str
    start: datetime
    end: datetime
    orgasms_by_partner: dict[str, int]
    chastity_locked_pct_by_partner: dict[str, float]
    avg_duration_by_partner: dict[str, float | None] = Field(default_factory=dict)
    play_by_partner: dict[str, int] = Field(default_factory=dict)
    ruined_by_partner: dict[str, int] = Field(default_factory=dict)


class HistoryPartnerSummary(BaseModel):
    membership_id: str
    name: str
    role: str
    orgasm_count: int
    play_count: int
    avg_duration_minutes: float | None = None
    chastity_enabled: bool
    percent_locked: float | None = None


class HistoryDashboardOut(BaseModel):
    dynamic_id: str
    dynamic_name: str
    days: int
    selected_tags: list[str]
    available_tags: list[str]
    partners: list[HistoryPartnerSummary]
    comparison_label: str
    weekly_buckets: list[HistoryWeekBucket]
    org_entries: list[OrgTrackingEntryOut]
    chastity_lockups: list["ChastityLockupOut"]
    chastity_any_enabled: bool
    you_are_dominant: bool


class HistoryChastityDayOut(BaseModel):
    date: str
    status: str
    locked_seconds: int


class HistoryChastityDaysPartnerOut(BaseModel):
    membership_id: str
    name: str
    days: list[HistoryChastityDayOut]
    whole_days: int
    partial_days: int
    free_days: int


class HistoryChastityDaysOut(BaseModel):
    year: int
    partners: list[HistoryChastityDaysPartnerOut]
    any_enabled: bool


class HistoryOrgasmMonthOut(BaseModel):
    month: str
    label: str
    orgasms: int = 0
    full_orgasm_days: int = 0
    ruined: int = 0
    play_sessions: int = 0
    avg_duration_minutes: float | None = None


class HistoryOrgasmPartnerOut(BaseModel):
    membership_id: str
    name: str
    role: str
    days_with_orgasms: int
    days_without_orgasms: int
    full_orgasm_days: int
    play_days: int
    total_orgasms: int
    orgasms_during_lockup: int = 0
    orgasms_during_own_lockup: int = 0
    orgasms_while_partner_locked: int = 0
    ruined_orgasms: int
    avg_duration_minutes: float | None = None
    avg_satisfaction: float | None = None
    avg_edging_count: float | None = None
    avg_orgasms_per_week: float | None = None
    avg_orgasms_per_month: float | None = None
    avg_ruined_per_month: float | None = None
    avg_play_days_per_month: float | None = None
    max_days_between_full: int | None = None
    min_days_between_full: int | None = None
    avg_days_between_full: float | None = None
    max_days_between_any: int | None = None
    avg_days_between_any: float | None = None
    monthly: list[HistoryOrgasmMonthOut] = Field(default_factory=list)


class HistoryOrgasmReportOut(BaseModel):
    year: int
    total_days: int
    selected_tags: list[str]
    partners: list[HistoryOrgasmPartnerOut]
    note: str


class HistorySessionsReportOut(BaseModel):
    days: int
    sessions: list["HistorySessionOut"]
    entry_session_map: dict[str, str]


class HistorySessionOut(BaseModel):
    session_id: str
    started_at: datetime
    ended_at: datetime
    entry_ids: list[str]
    entry_count: int
    during_lockup: bool
    locked_partner_names: list[str]
    orgasm_count: int
    entries: list[OrgTrackingEntryOut] = Field(default_factory=list)


class HistoryChastityMonthOut(BaseModel):
    month: str
    label: str
    percent_locked: float = 0
    locked_seconds: int = 0


class HistoryChastityStatsPartnerOut(BaseModel):
    membership_id: str
    name: str
    sessions_count: int
    max_locked_label: str
    min_locked_label: str
    avg_locked_label: str
    cumulative_locked_label: str
    cumulative_unlocked_label: str
    percent_locked: float
    percent_unlocked: float
    avg_session_days: float | None = None
    monthly: list[HistoryChastityMonthOut] = Field(default_factory=list)


class HistoryChastityStatsOut(BaseModel):
    year: int
    partners: list[HistoryChastityStatsPartnerOut]
    any_enabled: bool


class HistoryWeeklyOut(BaseModel):
    dynamic_name: str
    days: int
    comparison_label: str
    partners: list[HistoryPartnerSummary]
    weekly_buckets: list[HistoryWeekBucket]
    chastity_any_enabled: bool


class ChastityLockupStart(BaseModel):
    for_membership_id: str
    device_notes: str = Field(default="", max_length=500)
    started_at: datetime | None = None
    planned_end_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)


class ChastityLockupEnd(BaseModel):
    release_notes: str = Field(default="", max_length=500)
    ended_at: datetime | None = None
    tags: list[str] | None = None
    # unlocked | released_orgasm | released_timer
    ended_kind: Literal["unlocked", "released_orgasm", "released_timer"] = "released_orgasm"


class ChastityTimerExtend(BaseModel):
    hours: int = Field(ge=1, le=24 * 90)


class ChastityHistoricalCreate(BaseModel):
    for_membership_id: str
    started_at: datetime
    ended_at: datetime
    note: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list)


class ChastityLockupNoteUpdate(BaseModel):
    note: str = Field(default="", max_length=500)


class ChastityLockupUpdate(BaseModel):
    started_at: datetime | None = None
    ended_at: datetime | None = None
    planned_end_at: datetime | None = None
    device_notes: str | None = None
    release_notes: str | None = None
    tags: list[str] | None = None
    ended_kind: Literal["unlocked", "released_orgasm", "released_timer", "historical"] | None = None
    clear_ended_at: bool = False


class ChastityBreakCreate(BaseModel):
    break_type: str
    break_reason: str = Field(default="", max_length=255)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    note: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list)


class ChastityBreakFinish(BaseModel):
    ended_at: datetime | None = None
    break_type: str | None = None
    break_reason: str = Field(default="", max_length=255)


class ChastityBreakUpdate(BaseModel):
    started_at: datetime | None = None
    ended_at: datetime | None = None
    note: str | None = None
    break_reason: str | None = Field(default=None, max_length=255)
    break_type: str | None = None
    tags: list[str] | None = None
    clear_ended_at: bool = False


class ChastityBreakOut(BaseModel):
    id: str
    break_type: str
    break_reason: str
    started_at: datetime
    ended_at: datetime | None
    note: str
    tags: list[str] = Field(default_factory=list)
    created_by_display_name: str

    class Config:
        from_attributes = True


class ChastityLockupOut(BaseModel):
    id: str
    for_membership_id: str
    for_display_name: str
    started_by_display_name: str
    ended_by_display_name: str | None
    started_at: datetime
    ended_at: datetime | None
    planned_end_at: datetime | None
    device_notes: str
    release_notes: str
    tags: list[str] = Field(default_factory=list)
    ended_kind: str = ""
    timer_overdue: bool = False
    record_type: str
    status: str
    duration_label: str
    locked_duration_label: str
    breaks: list[ChastityBreakOut] = Field(default_factory=list)

    class Config:
        from_attributes = True


class ChastitySubSetting(BaseModel):
    membership_id: str
    display_name: str
    role: PartnerRole
    chastity_enabled: bool
    chastity_max_lock_hours: int | None
    enrollment_requested: bool = False


class ChastitySubSettingUpdate(BaseModel):
    membership_id: str
    chastity_enabled: bool
    chastity_max_lock_hours: int | None = None


class ChastitySettingsOut(BaseModel):
    max_lock_presets: list[dict[str, str | int | None]]
    break_types: list[dict[str, str]]
    emergency_break_types: list[str]
    submissives: list[ChastitySubSetting]
    you_are_dominant: bool
    you_membership_id: str
    can_disable_chastity: bool
    can_enable_self: bool
    any_enabled: bool
    sub_can_delete_breaks: bool = True


class ChastityPolicyUpdate(BaseModel):
    sub_can_delete_breaks: bool | None = None


class ChastityPartnerOverview(BaseModel):
    membership_id: str
    name: str
    role: str
    chastity_enabled: bool
    chastity_max_lock_hours: int | None
    state: str
    currently_locked: bool
    on_break: bool
    current_duration_label: str | None
    break_duration_label: str | None
    free_duration_label: str | None
    active_lockup_id: str | None
    active_break_id: str | None
    planned_end_at: datetime | None = None
    timer_overdue: bool = False
    percent_locked_all_time: float
    total_locked_label: str
    average_lockup_label: str | None
    longest_lockup_label: str | None
    lockup_count: int


class ChastityOverviewOut(BaseModel):
    summary_label: str
    partners: list[ChastityPartnerOverview]
    any_enabled: bool


class ChastityPartnerStats(BaseModel):
    membership_id: str
    name: str
    chastity_enabled: bool
    currently_locked: bool
    on_break: bool
    current_duration_label: str | None
    total_locked_days_90d: float
    longest_lockup_days_90d: float
    lockup_count_90d: int
    percent_locked_all_time: float


class ChastityStatsOut(BaseModel):
    partners: list[ChastityPartnerStats]
    summary_label: str
    any_enabled: bool


class AssistantToneOption(BaseModel):
    id: str
    label: str
    description: str


class AssistantSettingsOut(BaseModel):
    tone: str
    extra_instructions: str
    include_tracking: bool
    you_are_dominant: bool = True
    dynamic_id: str | None = None


class AssistantSettingsUpdate(BaseModel):
    tone: str
    extra_instructions: str = ""
    include_tracking: bool = True


class AccountImportSkipped(BaseModel):
    invite_code: str
    reason: str


class AccountImportResult(BaseModel):
    llm_restored: bool
    dynamics_restored: list[str]
    dynamics_skipped: list[AccountImportSkipped]
    warnings: list[str]


class GearCategoryOut(BaseModel):
    id: str
    label: str
    description: str = ""


class GearCatalogItemOut(BaseModel):
    id: str
    category: str
    name: str
    notes: str = ""
    tier: str = "common"
    owned: bool = False
    want: bool = False
    inventory_id: str | None = None


class GearInventoryItemOut(BaseModel):
    id: str
    catalog_item_id: str | None = None
    category: str
    name: str
    notes: str = ""
    owned: bool = False
    want: bool = False
    is_custom: bool = False
    tier: str = "common"
    created_at: datetime

    class Config:
        from_attributes = True


class GearInventoryUpsert(BaseModel):
    catalog_item_id: str | None = None
    category: str | None = None
    name: str | None = Field(default=None, max_length=200)
    notes: str = ""
    owned: bool = False
    want: bool = False


class GearInventoryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    owned: bool | None = None
    want: bool | None = None
    category: str | None = None


class GearBundleOut(BaseModel):
    categories: list[GearCategoryOut]
    catalog: list[GearCatalogItemOut]
    inventory: list[GearInventoryItemOut]
    owned_count: int = 0
    want_count: int = 0


class VaultImageOut(BaseModel):
    id: str
    title: str
    image_encrypted: str
    image_blurred: bool
    source_chat_message_id: str | None = None
    uploaded_by_membership_id: str
    is_yours: bool = False
    created_at: datetime
    expires_at: datetime | None = None

    class Config:
        from_attributes = True


class VaultImageCreate(BaseModel):
    title: str = Field(default="", max_length=200)
    image_encrypted: str = Field(min_length=1)
    image_blurred: bool = True
    source_chat_message_id: str | None = None
    expire_hours: int | None = Field(default=None, ge=1, le=24 * 30)


class VaultImageUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    image_blurred: bool | None = None


HistoryDashboardOut.model_rebuild()
