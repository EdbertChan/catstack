_STARTUP_INFRA_SIGNATURES = (
    "No space left on device",
    "Permission denied (publickey)",
)


def classify_repair_outcome(error):
    if error:
        if any(signature in error for signature in _STARTUP_INFRA_SIGNATURES):
            return "infra"
    return "task"
