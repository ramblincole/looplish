"""本地识别引擎（faster-whisper、mlx-whisper）共用的解码参数。"""

# Whisper 会模仿提示词的书写风格；没有带标点的示范时，长段口语常常整段不带标点，
# 切句只能退回按停顿切，完整的一句话会被切成几段。
PUNCTUATED_PROMPT = (
    "Hello, everyone. Welcome back! Today, I'm going to show you my routine. "
    "Are you ready? Let's go."
)


def decoding_options(language: str | None) -> dict[str, object]:
    # 承接上一段已识别的文本，示范句的标点风格才能延续到整段音频。
    options: dict[str, object] = {"condition_on_previous_text": True}
    # 英文示范句会把其他语言带偏成英文，只在英文或自动检测时使用。
    if language is None or language.lower().startswith("en"):
        options["initial_prompt"] = PUNCTUATED_PROMPT
    return options
