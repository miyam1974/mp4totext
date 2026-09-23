"""Language-dependent display formatting, independent of history persistence."""

from mp4totext.gui.i18n import Language


def format_duration(seconds: float, language: Language = Language.JA) -> str:
    total_seconds = max(round(seconds), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if language is Language.EN:
        if hours:
            return f"{hours}h {minutes:02}m {seconds:02}s"
        if minutes:
            return f"{minutes}m {seconds:02}s"
        return f"{seconds}s"
    if hours:
        return f"{hours}時間{minutes:02}分{seconds:02}秒"
    if minutes:
        return f"{minutes}分{seconds:02}秒"
    return f"{seconds}秒"
