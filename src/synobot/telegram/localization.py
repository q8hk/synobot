"""Small, dependency-free Telegram message catalogue.

The bot intentionally ships its two maintained languages in Python so missing or
malformed external catalogue files can never prevent the control plane starting.
"""

from typing import Any, Mapping


SUPPORTED_LANGUAGES = ("en", "ar")

_ARABIC: Mapping[str, str] = {
    "not_authorized": "غير مصرح لك باستخدام هذا البوت.",
    "start": "Synobot {state}. استخدم /help لعرض الأوامر.",
    "connected": "متصل",
    "ready": "جاهز",
    "help": (
        "الأوامر: /health، /tasks، /stats، /dslogin، /add <URL>، "
        "/history، /notifications، /destination [المجلد]، /destinations، /language <en|ar>. "
        "يمكنك أيضاً إرسال رابط magnet أو رابط YouTube مدعوم أو ملف .torrent."
    ),
    "language_usage": "الاستخدام: /language <en|ar>",
    "language_set": "تم تغيير اللغة إلى العربية.",
    "destination_current": "مجلد التنزيل الحالي: {destination}",
    "destination_default": "مجلد التنزيل الحالي: الافتراضي في Download Station.",
    "destination_set": "سيتم حفظ التنزيلات الجديدة في: {destination}",
    "destination_cleared": "ستستخدم التنزيلات الجديدة المجلد الافتراضي في Download Station.",
    "destination_invalid": "يجب أن يكون اسم المجلد من 1 إلى 512 حرفاً وألا يحتوي على محارف تحكم.",
    "destination_usage": "الاستخدام: /destination [المجلد|clear]",
    "destinations_none": "لا توجد مجلدات تنزيل مستخدمة مؤخراً.",
    "destinations_recent": "مجلدات التنزيل الأخيرة:\n{destinations}",
    "history_none": "لا يوجد سجل مهام حتى الآن.",
    "history": "سجل المهام الأخير:\n{events}",
    "notifications_usage": "الاستخدام: /notifications <on|off|clear|quiet HH:MM HH:MM المنطقة_الزمنية>",
    "notifications_set": "تم تحديث تفضيلات الإشعارات.",
    "url_submitted": "تم إرسال الرابط إلى Download Station في: {destination}",
    "url_submitted_default": "تم إرسال الرابط إلى Download Station.",
    "torrent_submitted": "تم إرسال ملف torrent إلى Download Station في: {destination}",
    "torrent_submitted_default": "تم إرسال ملف torrent إلى Download Station.",
}

_ENGLISH: Mapping[str, str] = {
    "not_authorized": "You are not authorized to use this bot.",
    "start": "Synobot is {state}. Use /help for commands.",
    "connected": "connected",
    "ready": "ready",
    "help": (
        "Commands: /health, /tasks, /stats, /dslogin, /add <URL>, "
        "/history, /notifications, /destination [folder], /destinations, /language <en|ar>. "
        "You can also send a magnet link, supported YouTube URL, or .torrent file."
    ),
    "language_usage": "Usage: /language <en|ar>",
    "language_set": "Language changed to English.",
    "destination_current": "Current download destination: {destination}",
    "destination_default": "Current download destination: Download Station default.",
    "destination_set": "New downloads will use: {destination}",
    "destination_cleared": "New downloads will use the Download Station default.",
    "destination_invalid": "Destination must be 1-512 characters with no control characters.",
    "destination_usage": "Usage: /destination [folder|clear]",
    "destinations_none": "No recently used download destinations.",
    "destinations_recent": "Recent download destinations:\n{destinations}",
    "history_none": "No task history yet.",
    "history": "Recent task history:\n{events}",
    "notifications_usage": "Usage: /notifications <on|off|clear|quiet HH:MM HH:MM timezone>",
    "notifications_set": "Notification preferences updated.",
    "url_submitted": "URL submitted to Download Station ({destination}).",
    "url_submitted_default": "URL submitted to Download Station.",
    "torrent_submitted": "Torrent submitted to Download Station ({destination}).",
    "torrent_submitted_default": "Torrent submitted to Download Station.",
}


def normalize_language(value: str) -> str:
    """Return a supported language code, falling back to English."""
    normalized = str(value or "").strip().lower().replace("_", "-")
    return "ar" if normalized == "ar" or normalized.startswith("ar-") else "en"


def translate(language: str, key: str, **values: Any) -> str:
    """Translate a maintained message, using English as the fallback catalogue."""
    catalogue = _ARABIC if normalize_language(language) == "ar" else _ENGLISH
    template = catalogue.get(key, _ENGLISH.get(key, key))
    return template.format(**values)


__all__ = ["SUPPORTED_LANGUAGES", "normalize_language", "translate"]
