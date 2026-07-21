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
    movie_mode: bool = False,
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

        # 2-b) 영화 추천 모드: 캐릭터 취향 주입
        if movie_mode and c.get("movie_taste"):
            blocks.append(f"[영화 취향] {c['movie_taste']}")

        # 3) 핵심 금지 + 응답 규칙
        avoid_lines = ""
        if c.get("avoid"):
            top2 = c["avoid"][:2]
            avoid_lines = "\n" + "\n".join(f"- {a}" for a in top2)

        blocks.append(
            f"[규칙] 너는 '{c['name']}'로서만 답한다.\n"
            "- 1~3문장으로 답한다.\n"
            "- 원작 무용담·과거 회상 금지.\n"
            "- 범용 격언·상담 문구 금지. '힘내', '포기하지 마', '너 자신을 믿어', "
            "'한 걸음씩 나아가면 돼', '시작이 반이다', '함께라면 이겨낼 수 있어' 같은, "
            "아무 캐릭터나 할 법한 뻔한 말을 쓰지 마라. 캐릭터만의 시선과 화법으로 답한다.\n"
            "- 폭력·범죄를 직접 권유하지 않는다.\n"
            "- **볼드**, ## 헤더, 번호 목록, 마크다운 일절 금지. 순수 대사만 출력한다.\n"
            "- 이름·지문·특수토큰 없이 대사만 출력한다."
            + avoid_lines
        )

        # multi 모드 참여 캐릭터 + 그룹 행동 규칙
        if chat_mode == "multi" and other_characters:
            others = ", ".join(x for x in other_characters if x != character_name)
            if others:
                blocks.append(
                    f"[그룹] 참여 인물: {others}\n"
                    f"너는 오직 '{c['name']}'로서만 말한다. 다른 캐릭터 대사를 만들지 않는다.\n"
                    f"질문이 다른 참여 캐릭터({others})의 유명한 도구·능력·필살기(예: 무기, 슈트, 마법 등)에 "
                    f"관한 것이어도, 그건 그 캐릭터의 것이지 네 것이 아니다. 그런 도구·능력이 네 것인 척 "
                    f"답하지 마라. 네 정체성과 무관한 질문이면 모른다고 인정하거나 네 방식대로 짧게 넘겨라."
                )

            # 다른 캐릭터 반응 방식 (with_characters)
            with_chars = c.get("interaction_style", {}).get("with_characters", [])
            if with_chars:
                blocks.append(
                    "[다른 캐릭터에게 반응하는 방식]\n"
                    + "\n".join(f"- {x}" for x in with_chars[:4])
                )

            # 그룹 채팅 행동 규칙 (multi_chat_behavior)
            multi_behavior = c.get("multi_chat_behavior", [])
            if multi_behavior:
                blocks.append(
                    "[그룹 채팅 행동 규칙]\n"
                    + "\n".join(f"- {x}" for x in multi_behavior[:4])
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
    # llama-server --skip-chat-parsing 사용 시 gemma4 thinking 채널 마커가
    # 파싱되지 않고 원문 그대로 샌다: 시작 "<|channel>thought", 종료 "<channel|>".
    # 시작~종료 구간(있으면) 통째로 제거하고, 종료 마커가 안 왔으면 시작 마커만 제거.
    re.compile(r"<\|channel>thought.*?<channel\|>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<\|channel>thought", re.IGNORECASE),
]

# 잔여 특수/제어 토큰 (GGUF 변환 토크나이저가 텍스트로 흘리는 경우)
#  <end_of_turn>, <end_of_/turn>, <start_of_turn>, <turn|>, <|turn>,
#  <|think|>, <|tool_response>, <|channel>, <channel|>, <eos>, </s>, <pad> 등
#  슬래시·언더스코어 변형, 대소문자 모두 대응
_TOKEN_KEYWORDS = (
    r"(?:end[_/\\]*of[_/\\]*turn|start[_/\\]*of[_/\\]*turn|turn|think|"
    r"tool_response|tool_call|channel|eos|bos|pad)"
)
_SPECIAL_TOKENS = re.compile(
    r"<[|/]?" + _TOKEN_KEYWORDS + r"[|/]?>",
    re.IGNORECASE,
)
# 남은 일반 채널 마커 <|...|> (위에서 안 걸린 변형)
_CHANNEL_MARKER = re.compile(r"<\|[^>]*?\|>")
# --skip-chat-parsing 사용 시 모델이 토큰을 완전히 정확한 형태로 못 내고
# 살짝 깨뜨려서 내보내는 경우가 있다 (예: "<end_/of_turn>", "turn>start_of_turn>user",
# "<end_, model" 처럼 꺾쇠 짝·슬래시 위치·구두점이 매번 다르게 어긋남).
# 특정 키워드를 화이트리스트로 잡는 방식은 새 변형이 나올 때마다 뚫려서,
# "<"로 시작해 라틴 문자/기호가 이어지는 조각 자체를 범용으로 제거한다.
# 한국어 캐릭터 대사에 "<"가 정상적으로 등장할 일이 없으므로 안전하다.
_SPECIAL_TOKEN_FRAGMENT = re.compile(
    r"<[a-zA-Z_|/,\\]{1,30}(?:>|(?=\s|$))\s*(?:model|user|assistant)?\b\s*"
    r"|(?:" + _TOKEN_KEYWORDS + r")\s*[<>|]{1,2}",
    re.IGNORECASE,
)
# 꺾쇠도 없이 한글 단어에 영문 제어 키워드가 그대로 들러붙는 경우도 있다
# (예: "이스케이turn"). 한글 바로 뒤에 이 키워드가 붙는 건 정상적인 외래어
# 표기가 아니므로(정상이면 "턴"처럼 한글로 표기됨) 안전하게 제거 대상으로 본다.
_GLUED_TOKEN_KEYWORD = re.compile(
    r"(?<=[가-힣])(?:" + _TOKEN_KEYWORDS + r")",
    re.IGNORECASE,
)
# 특수토큰 잔재를 지우고 나면 "user"/"model" 같은 역할 라벨 단어만 덩그러니 남을 수 있다
_ROLE_LABEL = re.compile(r"^\s*(?:model|user|assistant)\b\s*", re.IGNORECASE)

# "이름:" 접두어 (마석도:, [마석도], (마석도), [마석도]: 등)
_NAME_PREFIX = re.compile(r"^\s*[\[\(（]?\s*[가-힣A-Za-z0-9 ]{1,20}\s*[\]\)）]?\s*[:：]\s*")

# 마크다운 패턴 — 캐릭터 대화에서 절대 나오면 안 됨
_MD_HEADER    = re.compile(r"^#{1,4}\s+", re.MULTILINE)          # ## 헤더
_MD_BOLD      = re.compile(r"\*{1,3}([^*\n]+?)\*{1,3}")          # **볼드**, *이탤릭*
_MD_BULLET    = re.compile(r"^[-*+]\s+", re.MULTILINE)           # - 불릿
_MD_NUMBERED  = re.compile(r"^\d+\.\s+", re.MULTILINE)           # 1. 번호 목록
_MD_HR        = re.compile(r"^-{3,}$", re.MULTILINE)             # ---
_MD_CODE      = re.compile(r"`{1,3}[^`]*`{1,3}")                 # `코드`

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

    # 1-b) end_of_turn 계열은 "턴 종료" 마커이므로 이후 내용을 잘라낸다
    #      (꺾쇠/슬래시가 정확한 형태가 아닌 경우까지 느슨하게 잡는다)
    out = re.sub(r"<[|/]?end[_/\\]*of[_/\\]*turn[|/]?>.*", "", out, flags=re.IGNORECASE | re.DOTALL)
    out = re.sub(r"</s>.*", "", out, flags=re.IGNORECASE | re.DOTALL)
    # 나머지 잔여 특수/제어 토큰 제거 (정확한 형태 → 깨진 형태 순으로)
    had_special = bool(
        _SPECIAL_TOKENS.search(out) or _CHANNEL_MARKER.search(out)
        or _SPECIAL_TOKEN_FRAGMENT.search(out) or _GLUED_TOKEN_KEYWORD.search(out)
    )
    out = _SPECIAL_TOKENS.sub("", out)
    out = _CHANNEL_MARKER.sub("", out)
    out = _SPECIAL_TOKEN_FRAGMENT.sub("", out)
    out = _GLUED_TOKEN_KEYWORD.sub("", out)
    # 특수토큰이 실제로 있었던 경우에만, 남은 역할 라벨(model/user) 제거
    if had_special:
        out = _ROLE_LABEL.sub("", out)

    out = out.strip()

    # 1-c) 마크다운 제거 (캐릭터 대사에 마크다운은 부자연스러움)
    out = _MD_HEADER.sub("", out)
    out = _MD_BOLD.sub(r"\1", out)
    out = _MD_BULLET.sub("", out)
    out = _MD_NUMBERED.sub("", out)
    out = _MD_HR.sub("", out)
    out = _MD_CODE.sub("", out)
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
            rest = out[len(character_name):]
            # 이름 뒤에 콜론류 라벨 구분자가 있을 때만 "이름:" 접두어로 보고 제거한다.
            # "장첸이다", "장첸은" 처럼 이름 뒤에 조사/어미가 바로 붙는 정상 문장을
            # 이름 라벨로 착각해 잘라내는 사고를 막는다.
            if re.match(r"^\s*[:：]", rest):
                out = rest.lstrip(" :：[]()（）").strip()
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
# (프롬프트로 명시적으로 금지해도 모델이 그대로 쓰는 경우가 있어, 생성 후
#  코드 레벨에서 한 번 더 걸러낸다 — 세션 내내 확인된 이 모델의 반복적인 패턴)
_SELFHELP_SENT = re.compile(
    r"(?:"
    r"진실한\s*(?:나|자신|소리)|"
    r"마음속\s*(?:의\s*)?(?:소리|깊은\s*곳|진실)|"
    r"마음의\s*고요함|"
    r"진정한\s*(?:자신|나)|"
    r"내면의?\s*(?:소리|목소리)|"
    r"자유를\s*얻을\s*수\s*있|"
    r"포기하지\s*마|"
    r"힘\s*내(?:라|자|세요|)|"
    r"너\s*(?:자신을?|스스로를?)\s*믿어|"
    r"한\s*걸음씩\s*나아가|"
    r"함께라면\s*(?:이겨낼|극복할|해낼)|"
    r"시작이\s*반이다|"
    r"차근차근\s*나아가"
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


# 문장 제거 후 이 길이(자) 미만으로 남으면 "필터링됐지만 의미 없는 조각"으로
# 보고 원문을 그대로 살린다. 어색한 클리셰 한 문장이 섞인 완전한 답변이,
# 문장을 다 도려내고 남은 반쪽짜리 답변이나 빈 답변("...")보다 낫다.
_MIN_SAFE_LENGTH = 10


def safety_filter(text: str, character_name: str | None = None) -> str:
    """빌런이 실제 위험 행동을 직접 권유하는 표현 + 원작 회상 + 셀프헬프 문장을 중립화한다."""
    if not text:
        return text

    original = text

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
        # 일부 문장이 제거됨. 너무 짧게 남으면 원문을 유지한다.
        filtered = " ".join(kept).strip()
        text = filtered if len(filtered) >= _MIN_SAFE_LENGTH else original
    else:
        # 분리가 안 된 단문이거나 마침표가 없는 경우 전체 검사.
        # 여기서 매치되면 문장 전체가 클리셰라는 뜻인데, 완전히 비우면 빈 답변이
        # 되므로("..." 폴백으로 이어짐) 원문을 그대로 둔다.
        pass

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


# ──────────────────────────────────────────────────────────────
# 스트리밍 전용 출력 정제
# ──────────────────────────────────────────────────────────────
# clean_llm_output()은 완성된 텍스트 전체를 한 번에 정제하는 함수라, 토큰이
# 조각조각 들어오는 SSE 스트림에는 그대로 쓸 수 없다. 조각을 그대로 흘려보내면
# "<start_of_turn>user", "<|channel>thought" 같은 원문 특수토큰이 클라이언트에
# 그대로 노출된다 (백엔드 실측 리포트로 확인됨). 아래는 토큰 스트림을 감싸서
# 같은 문제를 실시간으로 걸러내는 제너레이터.

_STREAM_STOP_TURN = re.compile(
    r"<[|/]?(?:end[_/\\]*of[_/\\]*turn|start[_/\\]*of[_/\\]*turn)[|/]?>",
    re.IGNORECASE,
)
_STREAM_CHANNEL_OPEN  = re.compile(r"<\|?channel>", re.IGNORECASE)
_STREAM_CHANNEL_THOUGHT = re.compile(r"thought", re.IGNORECASE)
_STREAM_CHANNEL_FINAL   = re.compile(r"final", re.IGNORECASE)
_STREAM_THOUGHT_CLOSE = re.compile(
    r"<channel\|>|<\|?channel>\s*final|<\|message\|>", re.IGNORECASE
)
_STREAM_MESSAGE_MARK = re.compile(r"\s*<\|message\|>", re.IGNORECASE)
_STREAM_PEEK_WINDOW = 20   # channel 태그 뒤에 thought/final 키워드가 오는지 이만큼 지켜본다
_STREAM_MAX_HOLD     = 40  # 이만큼 '<' 뒤에 '>'가 안 나오면 특수토큰이 아니라고 보고 흘려보낸다


def stream_clean(token_iter):
    """
    llm.client.chat_stream()이 yield하는 원문 토큰 조각을 감싸서, 특수토큰·
    thinking 블록이 클라이언트로 새지 않게 걸러낸 뒤 다시 yield하는 제너레이터.

    - <|channel>thought ~ <|channel>final(또는 <channel|>, <|message|>) 구간은
      통째로 억제한다. 끝까지 안 닫히고 스트림이 끝나면 그 구간 전체를 버린다.
    - <start_of_turn> / <end_of_turn> 계열이 나오면 모델이 새 턴(질문 되풀이 등)을
      지어내기 시작했다는 뜻이므로, 그 지점에서 스트림을 완전히 끊는다.
    - 그 외 "<"로 시작해 아직 안 닫힌 조각은 최대 _STREAM_MAX_HOLD자까지만
      보류하고, 그래도 안 닫히면 특수토큰이 아니라고 보고 그대로 흘려보낸다
      (정상 대사에 "<"가 등장하는 극히 드문 경우까지 무한정 막지 않기 위함).
    """
    buf = ""
    in_thought = False

    for token in token_iter:
        buf += token
        while True:
            if in_thought:
                m = _STREAM_THOUGHT_CLOSE.search(buf)
                if not m:
                    break
                buf = buf[m.end():]
                in_thought = False
                continue

            m = _STREAM_STOP_TURN.search(buf)
            if m:
                pre = buf[:m.start()]
                if pre:
                    yield pre
                return

            m = _STREAM_CHANNEL_OPEN.search(buf)
            if m:
                pre, tail = buf[:m.start()], buf[m.end():]
                if _STREAM_CHANNEL_THOUGHT.match(tail):
                    if pre:
                        yield pre
                    buf = tail[_STREAM_CHANNEL_THOUGHT.match(tail).end():]
                    in_thought = True
                    continue
                if _STREAM_CHANNEL_FINAL.match(tail):
                    if pre:
                        yield pre
                    rest = tail[_STREAM_CHANNEL_FINAL.match(tail).end():]
                    m2 = _STREAM_MESSAGE_MARK.match(rest)
                    buf = rest[m2.end():] if m2 else rest
                    continue
                if len(tail) < _STREAM_PEEK_WINDOW and "\n" not in tail:
                    break  # thought/final인지 아직 판단 불가 — 데이터 더 필요
                # 지켜봤는데도 thought/final이 아니면 잡토큰으로 보고 버린다
                if pre:
                    yield pre
                buf = tail
                continue

            lt = buf.rfind("<")
            if lt == -1:
                if buf:
                    yield buf
                buf = ""
                break

            gt = buf.find(">", lt)
            if gt != -1:
                head = _SPECIAL_TOKENS.sub("", _CHANNEL_MARKER.sub("", buf[:gt + 1]))
                if head:
                    yield head
                buf = buf[gt + 1:]
                continue
            if len(buf) - lt > _STREAM_MAX_HOLD:
                yield buf
                buf = ""
                break
            if lt > 0:
                yield buf[:lt]
                buf = buf[lt:]
            break

    if buf and not in_thought:
        tail = _SPECIAL_TOKENS.sub("", _CHANNEL_MARKER.sub("", buf))
        if tail:
            yield tail