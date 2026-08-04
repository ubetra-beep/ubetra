import enum
import secrets
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _invite_code() -> str:
    return secrets.token_urlsafe(6).upper().replace("-", "")[:8]


class PartnerRole(str, enum.Enum):
    dominant = "dominant"
    submissive = "submissive"


class InterestValue(str, enum.Enum):
    want = "want"
    if_partner = "if_partner"
    not_into = "not_into"
    no_answer = "no_answer"


class TaskVisibility(str, enum.Enum):
    visible = "visible"
    after_prior = "after_prior"


class TaskApprovalStatus(str, enum.Enum):
    approved = "approved"
    pending = "pending"
    rejected = "rejected"


class TaskSource(str, enum.Enum):
    dom = "dom"
    sub = "sub"
    assistant = "assistant"
    act = "act"


class TaskRecurrence(str, enum.Enum):
    none = "none"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class ChatMessageType(str, enum.Enum):
    text = "text"
    image = "image"
    system = "system"


class ActStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    verified = "verified"
    cancelled = "cancelled"


class LlmProvider(str, enum.Enum):
    server = "server"
    gemini = "gemini"
    openai = "openai"


class ContextLinkCategory(str, enum.Enum):
    fictional_story = "fictional_story"
    contract = "contract"
    reference_guide = "reference_guide"
    scene_inspiration = "scene_inspiration"
    other = "other"


class OrgEventType(str, enum.Enum):
    orgasm = "orgasm"
    no_orgasm = "no_orgasm"
    sex = "sex"
    both = "both"


class LockupStatus(str, enum.Enum):
    active = "active"
    ended = "ended"


class ChastityRecordType(str, enum.Enum):
    normal = "normal"
    historical = "historical"


class ChastityEndedKind(str, enum.Enum):
    """How a lockup period ended — drives timeline title."""

    unlocked = "unlocked"  # ordinary end → "Unlocked"
    released_orgasm = "released_orgasm"  # full orgasm → "Released!"
    released_timer = "released_timer"  # planned end confirmed → "Released!"
    historical = "historical"


class ProposalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ChastityBreakType(str, enum.Enum):
    authorized_hygiene = "authorized_hygiene"
    authorized_sleep = "authorized_sleep"
    authorized_play = "authorized_play"
    authorized_denial = "authorized_denial"
    authorized_ruin = "authorized_ruin"
    authorized_other = "authorized_other"
    authorized_undecided = "authorized_undecided"
    emergency_hygiene = "emergency_hygiene"
    emergency_medical = "emergency_medical"
    emergency_discomfort = "emergency_discomfort"
    emergency_security = "emergency_security"
    emergency_other = "emergency_other"
    unauthorized_misbehavior = "unauthorized_misbehavior"


class InterviewRole(str, enum.Enum):
    assistant = "assistant"
    user = "user"


class GearCategory(str, enum.Enum):
    vanilla_toys = "vanilla_toys"
    kinky_stuff = "kinky_stuff"
    outfits = "outfits"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), default="", index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    llm_provider: Mapped[str] = mapped_column(String(32), default=LlmProvider.server.value)
    llm_api_key: Mapped[str] = mapped_column(String(512), default="")
    llm_model: Mapped[str] = mapped_column(String(120), default="")
    assistant_tone: Mapped[str] = mapped_column(String(32), default="balanced")
    assistant_extra_instructions: Mapped[str] = mapped_column(Text, default="")
    assistant_include_tracking: Mapped[bool] = mapped_column(Boolean, default=True)
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    google_refresh_token: Mapped[str] = mapped_column(Text, default="")
    google_tasks_list_id: Mapped[str] = mapped_column(String(128), default="@default")
    # male | female | intersex | prefer_not_to_say | "" (unset)
    biological_sex: Mapped[str] = mapped_column(String(32), default="")

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")
    push_subscriptions: Mapped[list["PushSubscription"]] = relationship(back_populates="user")
    native_push_tokens: Mapped[list["NativePushToken"]] = relationship(back_populates="user")
    mfa_challenges: Mapped[list["MfaChallenge"]] = relationship(back_populates="user")


class MfaChallenge(Base):
    __tablename__ = "mfa_challenges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="mfa_challenges")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    p256dh: Mapped[str] = mapped_column(String(256))
    auth: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="push_subscriptions")


class NativePushToken(Base):
    """FCM device tokens from the Capacitor Android APK (not Web Push endpoints)."""

    __tablename__ = "native_push_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(32), default="android")
    app_id: Mapped[str] = mapped_column(String(64), default="ubetra-android")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="native_push_tokens")


class Dynamic(Base):
    __tablename__ = "dynamics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), default="Our dynamic")
    invite_code: Mapped[str] = mapped_column(String(12), unique=True, default=_invite_code)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    tag_presets: Mapped[str] = mapped_column(
        Text,
        default=(
            "full orgasm,ruined orgasm,denied,milking,partial-milking,dildo,handjob,piv,"
            "finger,oral,vibrator,masturbation,cheated,anal,prostate"
        ),
    )
    # Shared chastity lockup tag chips — starts empty; custom tags become permanent for both partners.
    chastity_tag_presets: Mapped[str] = mapped_column(Text, default="")
    chat_retain_history: Mapped[bool] = mapped_column(Boolean, default=False)
    chat_e2e_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Shared AES key (base64) for encrypted chat — same model as shared_llm_api_key.
    # Server can decrypt; any logged-in member device can fetch and use it.
    chat_shared_key: Mapped[str] = mapped_column(Text, default="")
    chat_expire_hours: Mapped[int] = mapped_column(Integer, default=720)  # 30 days
    chat_system_events: Mapped[bool] = mapped_column(Boolean, default=True)
    chat_push_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # When False, only the keyholder can delete temporary unlock log entries
    chastity_sub_can_delete_breaks: Mapped[bool] = mapped_column(Boolean, default=True)
    shared_llm_provider: Mapped[str] = mapped_column(String(32), default="")
    shared_llm_api_key: Mapped[str] = mapped_column(String(512), default="")
    shared_llm_model: Mapped[str] = mapped_column(String(120), default="")
    shared_llm_set_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("memberships.id"), nullable=True
    )
    enabled_features: Mapped[str] = mapped_column(Text, default="")
    act_categories: Mapped[str] = mapped_column(Text, default="")
    # soft | hard
    feelings_prompt_mode: Mapped[str] = mapped_column(String(16), default="soft")
    feelings_require_end_of_day: Mapped[bool] = mapped_column(Boolean, default=True)
    # JSON: { fields: {...}, metrics: {...} } — couple opt-in tracking detail
    org_tracking_prefs: Mapped[str] = mapped_column(Text, default="")
    # JSON: keyholder unlock / gift goals
    chastity_goals: Mapped[str] = mapped_column(Text, default="")
    # Dom-controlled assistant voice for this dynamic
    assistant_tone: Mapped[str] = mapped_column(String(32), default="balanced")
    assistant_extra_instructions: Mapped[str] = mapped_column(Text, default="")

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="dynamic",
        foreign_keys="Membership.dynamic_id",
    )
    task_lists: Mapped[list["TaskList"]] = relationship(back_populates="dynamic")
    acts: Mapped[list["ActOfSubmission"]] = relationship(back_populates="dynamic")
    context_links: Mapped[list["ContextLink"]] = relationship(back_populates="dynamic")
    journal_entries: Mapped[list["JournalEntry"]] = relationship(back_populates="dynamic")
    org_entries: Mapped[list["OrgTrackingEntry"]] = relationship(back_populates="dynamic")
    chastity_lockups: Mapped[list["ChastityLockup"]] = relationship(back_populates="dynamic")
    chastity_limit_proposals: Mapped[list["ChastityLimitProposal"]] = relationship(
        back_populates="dynamic"
    )
    agreements: Mapped[list["Agreement"]] = relationship(
        back_populates="dynamic", order_by="Agreement.position"
    )
    chat_messages: Mapped[list["ChatMessage"]] = relationship(back_populates="dynamic")
    chat_key_transfers: Mapped[list["ChatKeyTransfer"]] = relationship(back_populates="dynamic")
    gear_items: Mapped[list["GearInventoryItem"]] = relationship(back_populates="dynamic")
    vault_images: Mapped[list["VaultImage"]] = relationship(back_populates="dynamic")
    spin_sessions: Mapped[list["SpinGameSession"]] = relationship(back_populates="dynamic")
    feeling_checkins: Mapped[list["FeelingCheckIn"]] = relationship(back_populates="dynamic")
    punishment_reports: Mapped[list["PunishmentReport"]] = relationship(back_populates="dynamic")


class PunishmentReport(Base):
    """Self-reported action needing punishment; keyholder assigns goal bumps."""

    __tablename__ = "punishment_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"), index=True)
    reported_by_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"), index=True)
    action_text: Mapped[str] = mapped_column(Text, default="")
    # pending | assigned | ideas | remind | covered
    status: Mapped[str] = mapped_column(String(32), default="pending")
    applied_changes: Mapped[str] = mapped_column(Text, default="[]")
    ideas: Mapped[str] = mapped_column(Text, default="[]")
    remind_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("memberships.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    dynamic: Mapped[Dynamic] = relationship(back_populates="punishment_reports")


class ChatKeyTransfer(Base):
    __tablename__ = "chat_key_transfers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"), index=True)
    code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    key_payload: Mapped[str] = mapped_column(Text)
    created_by_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    redeemed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("memberships.id"), nullable=True
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    dynamic: Mapped[Dynamic] = relationship(back_populates="chat_key_transfers")


class SpinGameSession(Base):
    """Shared spin-the-wheel game state. Secret JSON is never returned to submissives."""

    __tablename__ = "spin_game_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"), index=True)
    created_by_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    status: Mapped[str] = mapped_column(String(32), default="active")
    # active | awaiting_post_spin | completed | paused
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    secret_json: Mapped[str] = mapped_column(Text, default="{}")
    public_json: Mapped[str] = mapped_column(Text, default="{}")

    dynamic: Mapped[Dynamic] = relationship(back_populates="spin_sessions")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "dynamic_id", name="uq_user_dynamic"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"))
    role: Mapped[PartnerRole] = mapped_column(Enum(PartnerRole))
    display_name: Mapped[str] = mapped_column(String(64))
    survey_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    survey_submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    survey_skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    share_kinks: Mapped[bool] = mapped_column(Boolean, default=False)
    interview_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    interview_summary: Mapped[str] = mapped_column(Text, default="")
    chastity_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    chastity_max_lock_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chastity_enrollment_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    spti_data: Mapped[str] = mapped_column(Text, default="")
    spti_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Last time this member dismissed the frosted inbox overlay
    inbox_acked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="memberships")
    dynamic: Mapped[Dynamic] = relationship(
        back_populates="memberships",
        foreign_keys=[dynamic_id],
    )
    interest_responses: Mapped[list["InterestResponse"]] = relationship(
        back_populates="membership"
    )
    core_knowledge: Mapped["CoreKnowledge | None"] = relationship(
        back_populates="membership", uselist=False
    )
    requested_acts: Mapped[list["ActOfSubmission"]] = relationship(
        back_populates="requested_by"
    )
    interview_messages: Mapped[list["InterviewMessage"]] = relationship(
        back_populates="membership", order_by="InterviewMessage.created_at"
    )
    context_links: Mapped[list["ContextLink"]] = relationship(back_populates="added_by")
    journal_entries: Mapped[list["JournalEntry"]] = relationship(back_populates="membership")


class InterestCategory(Base):
    __tablename__ = "interest_categories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    interests: Mapped[list["Interest"]] = relationship(back_populates="category")


class Interest(Base):
    __tablename__ = "interests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("interest_categories.id"))
    display_copy: Mapped[str] = mapped_column(String(255))
    submissive_display_override: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    category: Mapped[InterestCategory] = relationship(back_populates="interests")


class InterestResponse(Base):
    __tablename__ = "interest_responses"
    __table_args__ = (
        UniqueConstraint("membership_id", "interest_id", name="uq_membership_interest"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    interest_id: Mapped[str] = mapped_column(ForeignKey("interests.id"))
    value: Mapped[InterestValue] = mapped_column(Enum(InterestValue))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    membership: Mapped[Membership] = relationship(back_populates="interest_responses")


class TaskList(Base):
    __tablename__ = "task_lists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"))
    title: Mapped[str] = mapped_column(String(200))
    created_by_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    dynamic: Mapped[Dynamic] = relationship(back_populates="task_lists")
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="task_list", order_by="Task.position"
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_list_id: Mapped[str] = mapped_column(ForeignKey("task_lists.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    visibility: Mapped[TaskVisibility] = mapped_column(
        Enum(TaskVisibility), default=TaskVisibility.visible
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("memberships.id"), nullable=True
    )
    tags: Mapped[str] = mapped_column(String(500), default="")
    approval_status: Mapped[TaskApprovalStatus] = mapped_column(
        Enum(TaskApprovalStatus), default=TaskApprovalStatus.approved
    )
    source: Mapped[TaskSource] = mapped_column(Enum(TaskSource), default=TaskSource.dom)
    recurrence: Mapped[TaskRecurrence] = mapped_column(
        Enum(TaskRecurrence), default=TaskRecurrence.none
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    act_id: Mapped[str | None] = mapped_column(
        ForeignKey("acts_of_submission.id"), nullable=True
    )
    assigned_to_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("memberships.id"), nullable=True, index=True
    )
    # Private = only creator + assignee; shared = whole dynamic
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    public_code_word: Mapped[str] = mapped_column(String(200), default="")
    google_task_id: Mapped[str] = mapped_column(String(128), default="")

    task_list: Mapped[TaskList] = relationship(back_populates="tasks")
    assigned_to: Mapped["Membership | None"] = relationship(
        foreign_keys=[assigned_to_membership_id]
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"), index=True)
    sender_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    message_type: Mapped[ChatMessageType] = mapped_column(
        Enum(ChatMessageType), default=ChatMessageType.text
    )
    body: Mapped[str] = mapped_column(Text, default="")
    body_encrypted: Mapped[str] = mapped_column(Text, default="")
    image_data: Mapped[str] = mapped_column(Text, default="")
    image_blurred: Mapped[bool] = mapped_column(Boolean, default=True)
    # Dom-locked image: partner must get permission before reveal
    image_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    image_unlock_granted: Mapped[bool] = mapped_column(Boolean, default=False)
    # Structured activity: e.g. orgasm_logged, lockup_started
    action: Mapped[str] = mapped_column(String(64), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    dynamic: Mapped[Dynamic] = relationship(back_populates="chat_messages")
    sender: Mapped["Membership"] = relationship(foreign_keys=[sender_membership_id])


class FeelingEmotion(Base):
    """Feelings-wheel taxonomy: core → mid → outer (parent_id hierarchy)."""

    __tablename__ = "feeling_emotions"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    label: Mapped[str] = mapped_column(String(80))
    # 1=core, 2=mid, 3=outer
    level: Mapped[int] = mapped_column(Integer, default=1)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("feeling_emotions.id"), nullable=True, index=True
    )
    color: Mapped[str] = mapped_column(String(16), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    parent: Mapped["FeelingEmotion | None"] = relationship(
        remote_side=[id], back_populates="children"
    )
    children: Mapped[list["FeelingEmotion"]] = relationship(back_populates="parent")


class FeelingCheckIn(Base):
    """Structured feelings-wheel check-in (not a journal)."""

    __tablename__ = "feeling_checkins"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"), index=True)
    for_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"), index=True)
    logged_by_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    # ad_hoc | before_play | after_play | end_of_day
    context: Mapped[str] = mapped_column(String(32), default="ad_hoc")
    # Legacy JSON kept for older rows; new rows also use feeling_checkin_selections
    selections_json: Mapped[str] = mapped_column(Text, default="[]")
    # Optional 0–10 arousal intensity (can be logged without wheel selections)
    horny_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    org_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey("org_tracking_entries.id"), nullable=True
    )
    chastity_lockup_id: Mapped[str | None] = mapped_column(
        ForeignKey("chastity_lockups.id"), nullable=True
    )
    spin_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("spin_game_sessions.id"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    dynamic: Mapped[Dynamic] = relationship(back_populates="feeling_checkins")
    selections: Mapped[list["FeelingCheckInSelection"]] = relationship(
        back_populates="checkin", cascade="all, delete-orphan"
    )


class FeelingCheckInSelection(Base):
    __tablename__ = "feeling_checkin_selections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    checkin_id: Mapped[str] = mapped_column(ForeignKey("feeling_checkins.id"), index=True)
    emotion_id: Mapped[str] = mapped_column(ForeignKey("feeling_emotions.id"), index=True)

    checkin: Mapped[FeelingCheckIn] = relationship(back_populates="selections")
    emotion: Mapped[FeelingEmotion] = relationship()


class CoreKnowledge(Base):
    __tablename__ = "core_knowledge"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    membership_id: Mapped[str] = mapped_column(
        ForeignKey("memberships.id"), unique=True, index=True
    )
    relationship_context: Mapped[str] = mapped_column(Text, default="")
    distance: Mapped[str] = mapped_column(Text, default="")
    space: Mapped[str] = mapped_column(Text, default="")
    budget: Mapped[str] = mapped_column(Text, default="")
    about_you: Mapped[str] = mapped_column(Text, default="")
    desires: Mapped[str] = mapped_column(Text, default="")
    submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    membership: Mapped[Membership] = relationship(back_populates="core_knowledge")


class ActOfSubmission(Base):
    __tablename__ = "acts_of_submission"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"), index=True)
    requested_by_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    status: Mapped[ActStatus] = mapped_column(Enum(ActStatus), default=ActStatus.active)
    hint_text: Mapped[str] = mapped_column(Text)
    knowledge_focus: Mapped[str] = mapped_column(String(255), default="")
    act_type_id: Mapped[str] = mapped_column(String(80), default="")
    act_type_title: Mapped[str] = mapped_column(String(120), default="")
    sub_response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sub_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dom_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    dom_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    dynamic: Mapped[Dynamic] = relationship(back_populates="acts")
    requested_by: Mapped[Membership] = relationship(back_populates="requested_acts")


class InterviewMessage(Base):
    __tablename__ = "interview_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"), index=True)
    role: Mapped[InterviewRole] = mapped_column(Enum(InterviewRole))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    membership: Mapped[Membership] = relationship(back_populates="interview_messages")


class ContextLink(Base):
    __tablename__ = "context_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"), index=True)
    added_by_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    category: Mapped[ContextLinkCategory] = mapped_column(
        Enum(ContextLinkCategory), default=ContextLinkCategory.other
    )
    # stories | journals | scenes | other — preferred subject tag for AI / UI
    subject: Mapped[str] = mapped_column(String(32), default="other")
    title: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(2000), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    fetched_text: Mapped[str] = mapped_column(Text, default="")
    filename: Mapped[str] = mapped_column(String(255), default="")
    mime_type: Mapped[str] = mapped_column(String(120), default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    use_for_ai: Mapped[bool] = mapped_column(Boolean, default=True)
    partner_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    dynamic: Mapped[Dynamic] = relationship(back_populates="context_links")
    added_by: Mapped[Membership] = relationship(back_populates="context_links")


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"), index=True)
    membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    use_for_ai: Mapped[bool] = mapped_column(Boolean, default=True)
    llm_assisted: Mapped[bool] = mapped_column(Boolean, default=False)
    partner_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    dynamic: Mapped[Dynamic] = relationship(back_populates="journal_entries")
    membership: Mapped[Membership] = relationship(back_populates="journal_entries")


class OrgTrackingEntry(Base):
    __tablename__ = "org_tracking_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"), index=True)
    logged_by_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    for_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    event_type: Mapped[OrgEventType] = mapped_column(Enum(OrgEventType))
    notes: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(500), default="")
    dominant_time_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submissive_time_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location: Mapped[str] = mapped_column(String(120), default="")
    initiated_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("memberships.id"), nullable=True
    )
    protection: Mapped[str] = mapped_column(String(32), default="")  # protected|unprotected|n_a|""
    satisfaction: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5
    edging_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes_private: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    dynamic: Mapped[Dynamic] = relationship(back_populates="org_entries")
    orgasms: Mapped[list["OrgTrackingOrgasm"]] = relationship(
        back_populates="entry", order_by="OrgTrackingOrgasm.position", cascade="all, delete-orphan"
    )


class OrgTrackingOrgasm(Base):
    __tablename__ = "org_tracking_orgasms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    entry_id: Mapped[str] = mapped_column(ForeignKey("org_tracking_entries.id"), index=True)
    tags: Mapped[str] = mapped_column(String(500), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    entry: Mapped[OrgTrackingEntry] = relationship(back_populates="orgasms")


class ChastityLimitProposal(Base):
    __tablename__ = "chastity_limit_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"), index=True)
    for_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    proposed_max_hours: Mapped[int] = mapped_column(Integer)
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus), default=ProposalStatus.pending
    )
    proposed_by_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    reviewed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("memberships.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    dynamic: Mapped[Dynamic] = relationship(back_populates="chastity_limit_proposals")


class ChastityLockup(Base):
    __tablename__ = "chastity_lockups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"), index=True)
    for_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    started_by_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    ended_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("memberships.id"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    planned_end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    device_notes: Mapped[str] = mapped_column(Text, default="")
    release_notes: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(500), default="")
    # unlocked | released_orgasm | released_timer | historical | "" while active
    ended_kind: Mapped[str] = mapped_column(String(32), default="")
    # When we last pushed the keyholder about planned_end_at passing
    timer_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    record_type: Mapped[ChastityRecordType] = mapped_column(
        Enum(ChastityRecordType), default=ChastityRecordType.normal
    )
    status: Mapped[LockupStatus] = mapped_column(Enum(LockupStatus), default=LockupStatus.active)

    dynamic: Mapped[Dynamic] = relationship(back_populates="chastity_lockups")
    breaks: Mapped[list["ChastityBreak"]] = relationship(
        back_populates="lockup", order_by="ChastityBreak.started_at"
    )


class ChastityBreak(Base):
    __tablename__ = "chastity_breaks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    lockup_id: Mapped[str] = mapped_column(ForeignKey("chastity_lockups.id"), index=True)
    break_type: Mapped[ChastityBreakType] = mapped_column(Enum(ChastityBreakType))
    break_reason: Mapped[str] = mapped_column(String(255), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(500), default="")
    created_by_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))

    lockup: Mapped[ChastityLockup] = relationship(back_populates="breaks")


class Agreement(Base):
    __tablename__ = "agreements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    approved_content: Mapped[str] = mapped_column(Text, default="")
    pending_content: Mapped[str] = mapped_column(Text, default="")
    pending_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("memberships.id"), nullable=True
    )
    pending_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("memberships.id"), nullable=True
    )
    created_by_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    dynamic: Mapped[Dynamic] = relationship(back_populates="agreements")


class GearInventoryItem(Base):
    __tablename__ = "gear_inventory_items"
    __table_args__ = (
        UniqueConstraint("dynamic_id", "catalog_item_id", name="uq_gear_catalog_item"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"), index=True)
    catalog_item_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(32), default=GearCategory.kinky_stuff.value)
    name: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    owned: Mapped[bool] = mapped_column(Boolean, default=False)
    want: Mapped[bool] = mapped_column(Boolean, default=False)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    tier: Mapped[str] = mapped_column(String(32), default="common")
    added_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("memberships.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    dynamic: Mapped[Dynamic] = relationship(back_populates="gear_items")


class VaultImage(Base):
    __tablename__ = "vault_images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dynamic_id: Mapped[str] = mapped_column(ForeignKey("dynamics.id"), index=True)
    uploaded_by_membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    source_chat_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("chat_messages.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), default="")
    image_encrypted: Mapped[str] = mapped_column(Text, default="")
    image_blurred: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    dynamic: Mapped[Dynamic] = relationship(back_populates="vault_images")
