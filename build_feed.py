def matches_filters(title: str, summary: str, keywords: list[str], exclude_keywords: list[str]) -> bool:
    blob = f"{title} {summary}".lower()

    if exclude_keywords:
        if any(bad.lower() in blob for bad in exclude_keywords):
            return False

    if not keywords:
        return True

    return any(k.lower() in blob for k in keywords)
