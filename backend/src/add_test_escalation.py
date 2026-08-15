from escalation_store import create_escalation


result = create_escalation(
    user_id="taksshak",
    issue_type="suspected_fraud",
    summary=(
        "Caller reported a suspicious banking message and requested "
        "authorized support."
    ),
    checked_information=[
        "Caller was advised not to share OTPs or PINs.",
        "Caller was directed to the official bank fraud channel.",
    ],
    urgency="urgent",
    language_preference="Hinglish",
    preferred_follow_up_method="phone",
    consent_given=True,
)

print(result)