def is_short_test_transcript(transcript: str) -> bool:
    normalized = "".join(ch for ch in transcript.lower() if ch.isalnum() or ch.isspace())
    words = normalized.split()
    compact = "".join(words)
    if len(compact) < 30:
        return True

    test_phrases = [
        "아아테스트테스트",
        "마이크테스트",
        "하나둘셋",
        "들리나요",
        "테스트테스트",
        "아아",
    ]
    if compact in test_phrases:
        return True

    meaningful_words = {
        word
        for word in words
        if word not in {"아", "아아", "어", "음", "테스트", "마이크", "하나", "둘", "셋", "들리나요"}
    }
    if not meaningful_words and len(words) <= 12:
        return True

    unique_words = set(words)
    return len(unique_words) <= 2 and len(words) <= 12
