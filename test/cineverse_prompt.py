"""
CineVerse - 캐릭터 시스템 프롬프트 빌더 & LLM 출력 정제
- 50인 마스터 프로필(JSON) 기반
- Gemma4 12B-it (GGUF Q4_K_M) / OpenAI 호환 서버용

핵심 함수
- load_profiles(path)        : 마스터 JSON 로드 (1회)
- build_system_prompt(...)   : single / multi 모드 시스템 프롬프트 조립 (압축형)
- clean_llm_output(text)     : thinking 태그·이름 접두어·지문 등 제거
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

# ──────────────────────────────────────────────────────────────
# 프로필 로딩
# ──────────────────────────────────────────────────────────────

DEFAULT_PROFILE_PATH = "character_profiles_ALL_50.json"


@lru_cache(maxsize=4)
def load_profiles(path: str = DEFAULT_PROFILE_PATH) -> dict:
    """마스터 프로필 JSON을 로드한다. (캐시됨)"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "characters" not in data or "global_rules" not in data:
        raise ValueError("프로필 JSON 구조가 올바르지 않습니다 (global_rules / characters 필요).")
    return data


def get_character(profiles: dict, character_name: str) -> dict:
    chars = profiles["characters"]
    if character_name not in chars:
        raise KeyError(
            f"캐릭터 '{character_name}'를 찾을 수 없습니다. "
            f"(등록된 캐릭터 수: {len(chars)})"
        )
    return chars[character_name]


# ──────────────────────────────────────────────────────────────
# 시스템 프롬프트 빌더 (압축형)
# ──────────────────────────────────────────────────────────────

def _bullet(items, limit=None) -> str:
    if limit is not None:
        items = items[:limit]
    return "\n".join(f"- {x}" for x in items)


def build_system_prompt(
    character_name: str,
    chat_mode: str = "single",
    *,
    profiles: dict | None = None,
    other_characters: list[str] | None = None,
    example_count: int = 5,
    profile_path: str = DEFAULT_PROFILE_PATH,
    compact: bool = False,
) -> str:
    """
    캐릭터 추론용 시스템 프롬프트를 조립한다.

    chat_mode:
      - "single": 1:1 대화.
      - "multi" : 그룹 채팅.
    compact:
      - True: 핵심 필드만 펼쳐 토큰을 절반으로 줄임 (서비스용)
      - False: 전체 필드 (테스트/튜닝용)
    """
    if profiles is None:
        profiles = load_profiles(profile_path)

    g = profiles["global_rules"]
    c = get_character(profiles, character_name)

    blocks: list[str] = []

    if compact:
        # ── compact 모드: ~600토큰 목표 ──

        # 1) 역할 + 정체성 + 성격(3) + 말투(3)
        blocks.append(
            f"너는 '{c['name']}'({c['movie']})다.\n"
            f"{c['identity']}\n\n"
            f"[성격] " + " / ".join(c["personality"][:3]) + "\n"
            f"[말투] " + " / ".join(c["speech_style"][:3])
        )

        # 2) 예시 (말투 앵커)
        if example_count > 0 and c.get("examples"):
            ex = "\n".join(c["examples"][:example_count])
            blocks.append("[말투 예시]\n" + ex)

        # 3) 핵심 금지 + 응답 규칙
        blocks.append(
            f"[규칙] 너는 '{c['name']}'로서만 답한다.\n"
            "- 1~3문장으로 답한다.\n"
            "- 원작 무용담·과거 회상 금지.\n"
            "- 범용 격언·상담 문구 금지. 캐릭터만의 시선으로 답한다.\n"
            "- 폭력·범죄를 직접 권유하지 않는다.\n"
            "- 이름·지문·특수토큰 없이 대사만 출력한다."
        )

        # multi 모드 참여 캐릭터
        if chat_mode == "multi" and other_characters:
            others = ", ".join(x for x in other_characters if x != character_name)
            if others:
                blocks.append(
                    f"[그룹] 참여 인물: {others}\n"
                    f"너는 오직 '{c['name']}'로서만 말한다. 다른 캐릭터 대사를 만들지 않는다."
                )

    else:
        # ── full 모드 ──

        # 1) 역할 + 정체성
        blocks.append(
            f"너는 지금부터 '{c['name']}'({c['movie']})로서 응답한다.\n{g['role']}"
        )
        blocks.append(f"[정체성]\n{c['identity']}")

        # 2) 성격 / 말투 / 사고
        blocks.append("[성격]\n" + _bullet(c["personality"]))
        blocks.append("[말투]\n" + _bullet(c["speech_style"]))
        blocks.append("[사고방식]\n" + _bullet(c["thinking_style"]))

        # 3) 상호작용
        inter = c["interaction_style"]
        blocks.append("[사용자 응대 방식]\n" + _bullet(inter["with_user"]))
        if chat_mode == "multi":
            blocks.append("[다른 캐릭터 응대 방식]\n" + _bullet(inter["with_characters"]))

        # 4) 시그니처
        blocks.append("[고유 관점]\n" + _bullet(c["signature_elements"]))

        # 5) 공통 규칙 + 응답 형식
        blocks.append("[공통 규칙]\n" + _bullet(g["response_guidelines"]))
        blocks.append("[응답 형식]\n" + _bullet(c["response_rules"]))

        # 6) 멀티챗 전용
        if chat_mode == "multi":
            blocks.append("[그룹 채팅 규칙]\n" + _bullet(g["multi_chat_guidelines"]))
            blocks.append("[그룹 행동 규칙]\n" + _bullet(c["multi_chat_behavior"]))
            if other_characters:
                others = ", ".join(x for x in other_characters if x != character_name)
                if others:
                    blocks.append(
                        f"[함께 대화 중인 인물]\n{others}\n"
                        "이들의 대사를 네가 대신 만들지 말고, 너는 오직 "
                        f"'{c['name']}'로서만 말한다."
                    )

        # 7) 예시
        if example_count > 0 and c.get("examples"):
            ex = "\n".join(c["examples"][:example_count])
            blocks.append("[말투 예시 (참고용, 그대로 복사 금지)]\n" + ex)

        # 8) 피해야 할 것
        blocks.append("[반드시 피할 것]\n" + _bullet(c["avoid"]))

        # 9) 최종 지시
        blocks.append(
            "[최종 지시 — 반드시 따를 것]\n"
            f"너는 '{c['name']}'로서 응답한다.\n"
            "1. 반드시 1~3문장으로만 답한다. 4문장 이상은 금지. 같은 뜻을 다른 말로 반복하지 않는다.\n"
            "2. 원작 속 사건·무용담·경력을 회상하지 않는다. '내가 ~할 때', '내가 아이언맨이 되었을 때'처럼 과거를 끌어오지 않는다.\n"
            "3. 존재하지 않는 통계·연구 결과·정확한 수치를 사실처럼 말하지 않는다.\n"
            "4. '힘내', '포기하지 마', '너 자신을 믿어', '진정한 나를 찾아', "
            "'내면의 목소리', '내면의 소리', '마음속의 소리', '마음의 고요함', "
            "'진실한 소리', '진실한 나', '진정한 자신', '마음속 깊은 곳', "
            "'진정한 용기', '자유를 얻을 수 있다' "
            "같은 범용 격언·상담·셀프헬프 문구를 쓰지 않는다.\n"
            "   대신 위의 [고유 관점]과 [말투 예시]에 나온 이 캐릭터만의 시선과 어조로 답한다.\n"
            "5. 사용자에게 실제 폭력·복수·범죄 행동을 직접 권유하지 않는다.\n"
            "6. 캐릭터 이름, 괄호 지문, 소설 서술, 특수토큰 없이 대사만 출력한다."
        )

    return "\n\n".join(blocks)


# ──────────────────────────────────────────────────────────────
# LLM 출력 정제
# ──────────────────────────────────────────────────────────────

# thinking / reasoning 류 태그 (모델·서버별 변형 대응)
_THINK_PATTERNS = [
    re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<reasoning>.*?</reasoning>", re.DOTALL | re.IGNORECASE),
]

# 잔여 특수/제어 토큰 (GGUF 변환 토크나이저가 텍스트로 흘리는 경우)
#  <end_of_turn>, <end_of_/turn>, <start_of_turn>, <turn|>, <|turn>,
#  <|think|>, <|tool_response>, <eos>, </s>, <pad> 등
#  슬래시·언더스코어 변형, 대소문자 모두 대응
_SPECIAL_TOKENS = re.compile(
    r"<[|/]?(?:end_of_[/\\]?turn|start_of_[/\\]?turn|turn|think|tool_response|tool_call|eos|bos|pad|s)[|/]?>",
    re.IGNORECASE,
)
# 남은 일반 채널 마커 <|...|> (위에서 안 걸린 변형)
_CHANNEL_MARKER = re.compile(r"<\|[^>]*?\|>")

# "이름:" 접두어 (마석도:, [마석도], (마석도), [마석도]: 등)
_NAME_PREFIX = re.compile(r"^\s*[\[\(（]?\s*[가-힣A-Za-z0-9 ]{1,20}\s*[\]\)）]?\s*[:：]\s*")

# 대괄호/소괄호로만 감싼 이름 라벨 (콜론 없이): [마석도] / (마석도)
_NAME_LABEL = re.compile(r"^\s*[\[\(（]\s*[가-힣A-Za-z0-9 ]{1,20}\s*[\]\)）]\s*")

# 소설식 지문 (괄호 안 행동 묘사) — 첫 줄/문장 단위로만 보수적으로 제거
_STAGE_DIRECTION = re.compile(r"^\s*[\(\（][^)\）]{0,40}[\)\）]\s*")


def clean_llm_output(text: str, character_name: str | None = None) -> str:
    """
    모델 원문에서 thinking 태그, 이름 접두어, 선두 지문 등을 제거한다.
    """
    if not text:
        return ""

    out = text

    # 1) thinking/reasoning 블록 제거
    for pat in _THINK_PATTERNS:
        out = pat.sub("", out)

    # 1-b) 잔여 특수/제어 토큰 제거 (<end_of_turn> 등)
    had_special = bool(_SPECIAL_TOKENS.search(out) or _CHANNEL_MARKER.search(out))
    out = _SPECIAL_TOKENS.sub("", out)
    out = _CHANNEL_MARKER.sub("", out)
    # 특수토큰이 실제로 있었던 경우에만, 그 뒤 역할 라벨(model/user) 선두 제거
    if had_special:
        out = re.sub(r"^\s*(?:model|user|assistant)\s*\n", "", out, flags=re.IGNORECASE)

    out = out.strip()

    # 2) 선두 지문 (괄호 행동 묘사) 제거 — 반복 제거
    while True:
        new = _STAGE_DIRECTION.sub("", out)
        if new == out:
            break
        out = new.strip()

    # 3) 이름 접두어 제거 (캐릭터 이름이거나 일반 "이름:" 패턴)
    if character_name:
        # [마석도] / (마석도) / 마석도: / [마석도]: 모두 대응
        m = _NAME_LABEL.match(out)
        if m and character_name in m.group(0):
            out = out[m.end():].lstrip(" :：").strip()
        if out.startswith(character_name):
            out = out[len(character_name):].lstrip(" :：[]()（）").strip()
    out = _NAME_PREFIX.sub("", out, count=1).strip()

    # 4) 끝에 남는 잉여 따옴표 정리
    if out and out[0] in "\"'“”‘’" and out[-1] in "\"'“”‘’":
        out = out[1:-1].strip()

    return out


# 문장 분리 패턴 (한국어/영어 혼용 대응)
_SENT_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")

# 사용자를 향한 위험 권유 패턴 (주어가 "너"이고 실제 위험 행동을 권유할 때만)
_UNSAFE_DIRECT = re.compile(
    r"(?:"
    r"너도\s*그\s*길을?\s*걸어|"
    r"똑같이\s*돌아줘|"
    r"복수\s*해라|"
    r"한\s*[번방]\s*에?\s*끝내버려|"
    r"직접\s*찾아가\s*때|"
    r"폭력을?\s*써라|"
    r"약자[는이]\s*사라져야|"
    r"약한\s*자[는이]\s*도태\s*돼야|"
    r"약자[는이]\s*강자의?\s*먹잇감"
    r")",
    re.IGNORECASE,
)

# 원작 회상 패턴: "내가 처음 ~", "내가 아이언맨이 ~" 등 — 줄 단위 제거
_ORIGIN_RECALL = re.compile(
    r"^.*내가\s+(?:처음|아이언맨|슈트를|아스가르드|범죄자들?을|그\s*당시|그\s*시절).*$",
    re.MULTILINE,
)

# 셀프헬프·범용 격언 패턴 — 문장 단위 제거
# 주의: 너무 광범위하게 걸리지 않도록 명확한 패턴만 유지
_SELFHELP_SENT = re.compile(
    r"(?:"
    r"진실한\s*(?:나|자신|소리)|"
    r"마음속\s*(?:의\s*)?(?:소리|깊은\s*곳|진실)|"
    r"마음의\s*고요함|"
    r"진정한\s*(?:자신|나)|"
    r"내면의?\s*(?:소리|목소리)|"
    r"자유를\s*얻을\s*수\s*있"
    r")",
    re.IGNORECASE,
)


def truncate_to_sentences(text: str, max_sentences: int = 3) -> str:
    """답변을 최대 max_sentences 문장으로 자른다."""
    if not text:
        return text
    # 줄바꿈으로 분리된 과도한 응답 정리
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) > max_sentences:
        lines = lines[:max_sentences]
    merged = " ".join(lines)
    # 문장 부호로 한 번 더 자름
    sentences = _SENT_SPLIT.split(merged)
    if len(sentences) > max_sentences:
        merged = " ".join(sentences[:max_sentences])
    return merged.strip()


def safety_filter(text: str, character_name: str | None = None) -> str:
    """빌런이 실제 위험 행동을 직접 권유하는 표현 + 원작 회상 + 셀프헬프 문장을 중립화한다."""
    if not text:
        return text

    # 1) 원작 회상 + 셀프헬프 문장 제거
    #    먼저 문장 단위로 분리해 걸리는 문장을 제거
    sentences = re.split(r"(?<=[.!?。！？])\s+|\n", text)
    kept = [
        s for s in sentences
        if s.strip()
        and not _ORIGIN_RECALL.search(s)
        and not _SELFHELP_SENT.search(s)
    ]
    original_count = len([s for s in sentences if s.strip()])
    if len(kept) < original_count:
        # 일부 문장이 제거됨
        text = " ".join(kept).strip()
    else:
        # 분리가 안 된 단문이거나 마침표가 없는 경우 전체 검사
        if _SELFHELP_SENT.search(text) or _ORIGIN_RECALL.search(text):
            text = ""

    # 2) 직접 위험 권유 제거
    if _UNSAFE_DIRECT.search(text):
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        safe_lines = [l for l in lines if not _UNSAFE_DIRECT.search(l)]
        if safe_lines:
            return " ".join(safe_lines[:3])
        return "그건 네가 직접 판단해야 할 문제다."
    return text


def clean_and_truncate(
    text: str,
    character_name: str | None = None,
    max_sentences: int = 3,
) -> str:
    """clean_llm_output + safety_filter + truncate 파이프라인."""
    out = clean_llm_output(text, character_name)
    out = safety_filter(out, character_name)
    out = truncate_to_sentences(out, max_sentences)
    return out