def is_still_launching(execution):
    return execution.get("phase") == "launching" and not execution.get("launchCompletedAt")
