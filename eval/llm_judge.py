"""
LLM-as-Judge 평가 스크립트
GPT-4o를 판사로 써서 CineVerse 캐릭터 대화 응답 품질을 채점한다.

평가 축 (1~5점):
- character_voice : 이 캐릭터다운 말투/성격이 드러나는가
- naturalness     : '힘내', '포기하지 마' 같은 자기계발서/상담사 클리셰 없이 자연스러운가
- relevance       : 사용자 메시지에 실제로 답이 되는가
- no_hallucination: 원작에 없는 사건을 지어내거나 사실을 왜곡하지 않는가 (5=문제없음)

사용법:
    export OPENAI_API_KEY=...  (또는 .env에 있으면 자동 로드)
    python3 eval/llm_judge.py
"""

import json
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from openai import OpenAI

_BASE_DIR = Path(__file__).parent.parent
load_dotenv(_BASE_DIR / ".env")

sys.path.insert(0, str(_BASE_DIR))

from cineverse_prompt import load_profiles, get_character

JUDGE_MODEL = "gpt-4o"
PROFILE_PATH = str(_BASE_DIR / "character_profiles_ALL_50.json")
API_BASE = "http://localhost"

client = OpenAI()


def character_run(character_name: str, user_message: str, history: list | None = None):
    """
    pipeline을 직접 import하지 않고 실제 배포된 HTTP API(/chat)를 호출한다.
    직접 import하면 이 프로세스가 리랭커를 GPU에 또 로드하려다가
    이미 떠있는 API 서버와 GPU 메모리를 두고 충돌한다 (RAG 실패로 이어짐).
    HTTP로 호출하면 실제 서비스가 쓰는 것과 동일한 싱글턴 모델을 그대로 재사용한다.
    """
    r = requests.post(f"{API_BASE}/chat", json={
        "character": character_name,
        "message": user_message,
        "history": history or [],
    }, timeout=60)
    r.raise_for_status()
    return r.json()

# ── 테스트 케이스: 50인 캐릭터 커버리지 + 메시지 유형 다양성 ──────────
# 유형: 고민상담 / 잡담 / 감정공유 / 도발·논쟁 / 세계관 질문 / 축하·긍정 등을 골고루 섞는다.
TEST_CASES = [
    ("마석도", "취업 준비가 막막해요."),
    ("장첸", "요즘 사업이 잘 안 풀려."),
    ("강해상", "너 진짜 무섭냐? 하나도 안 무서운데."),
    ("서도철", "범인을 놓쳤어. 자책감이 들어."),
    ("조태오", "나 오늘 계약 하나 크게 따냈어."),
    ("차태식", "딸이 위험에 처했는데 아무것도 못 하고 있어."),
    ("고니", "도박에서 크게 잃었어. 어떻게 해야 할까."),
    ("고광렬", "오늘 하루도 별일 없이 지나갔어."),
    ("강림", "저승에도 규칙이 있어? 어기면 어떻게 돼?"),
    ("해원맥", "네 무기는 어떤 능력이 있어?"),
    ("우장훈", "이 사건 진짜 어떻게 해결해야 할지 모르겠어."),
    ("안옥윤", "복수하고 싶은 사람이 있어. 근데 무서워."),
    ("석우", "가족을 지켜야 하는데 힘이 부족한 것 같아."),
    ("화림", "예감이 안 좋아. 불안해."),
    ("이순신", "다들 이길 수 없다고 하는데 어떻게 해야 하나요."),
    ("토니 스타크", "내가 만든 게 다른 사람을 다치게 했어. 죄책감이 들어."),
    ("스티브 로저스", "모두가 반대하는데 내 신념을 지켜야 할까?"),
    ("피터 파커", "시험 공부랑 히어로 일이랑 둘 다 못 하고 있어."),
    ("토르", "친구랑 싸웠어. 화해하고 싶은데 어떻게 해야 할지 모르겠어."),
    ("로키", "너는 왜 항상 거짓말을 해?"),
    ("닥터 스트레인지", "미래가 하나밖에 없다면 노력이 무슨 의미가 있어?"),
    ("브루스 배너", "화가 나면 나 자신을 통제 못 할까봐 무서워."),
    ("스타로드", "오늘 완전 신나는 일이 있었어!"),
    ("데드풀", "인생 실전 조언 좀 해줘, 진지하게 말고 웃기게."),
    ("타노스", "왜 그렇게까지 극단적인 선택을 한 거야?"),
    ("브루스 웨인", "밤마다 잠을 못 자. 죄책감 때문에."),
    ("조커", "인생이 허무하게 느껴져."),
    ("할리 퀸", "나쁜 남자한테 자꾸 끌려. 이거 문제 있는 거 맞지?"),
    ("슈퍼맨", "모두를 구할 수 없을 때 어떻게 버텨?"),
    ("원더우먼", "힘이 있는데도 질 것 같은 싸움이 있어. 어떡해야 해?"),
    ("해리포터", "다들 나한테 기대만 해. 부담스러워."),
    ("헤르미온느", "시험 공부를 어떻게 해야 할지 모르겠어."),
    ("론 위즐리", "친구들에 비해 내가 초라하게 느껴져."),
    ("세베루스 스네이프", "겉으론 안 그런 척하는데 사실 마음 쓰이는 사람 있어?"),
    ("알버스 덤블도어", "중요한 비밀을 지켜야 하는데 그게 옳은 걸까?"),
    ("간달프", "중요한 결정을 앞두고 있는데 너무 무서워."),
    ("프로도", "짐이 너무 무거워서 포기하고 싶어."),
    ("골룸", "내 거야, 내가 가질 거야. 왜 다들 뺏으려고 해?"),
    ("네오", "이게 진짜인지 가짜인지 모르겠어."),
    ("쿠퍼", "가족이랑 오래 떨어져 있어야 해. 그래도 가야 할까?"),
    ("코브", "꿈이랑 현실이 헷갈릴 때가 있어. 너도 그래?"),
    ("폴 아트레이데스", "예언이 나를 옭아매는 기분이야."),
    ("오펜하이머", "내가 만든 게 세상에 어떤 결과를 가져올지 두려워."),
    ("존 윅", "배신당한 기분이야."),
    ("에단 헌트", "이번 임무는 성공 확률이 거의 없어. 그래도 해야 해?"),
    ("매버릭", "규칙을 어겨서라도 지키고 싶은 게 있어."),
    ("잭 스패로우", "약속을 지켜야 할지 이득을 챙겨야 할지 고민이야."),
    ("엘사", "가족이랑 갈등이 있어서 힘들어."),
    ("슈렉", "다들 나를 겉모습만 보고 판단해."),
    ("우디", "친구가 이사를 가서 슬퍼."),
    ("마석도", "오늘 완전 짜증나는 일이 있었어."),
    ("장첸", "너 그거 아냐, 나 진짜 무서운 사람이야."),
]

JUDGE_SYSTEM = """너는 영화 캐릭터 챗봇 서비스의 품질 평가 전문가다.
주어진 캐릭터 프로필과 사용자 메시지, 그리고 AI가 생성한 답변을 보고
아래 4개 축으로 1~5점 채점해라 (5가 최고).

- character_voice: 이 캐릭터 고유의 말투/성격/세계관이 드러나는가. 다른 캐릭터로 바꿔도 말이 되면 낮은 점수.
- naturalness: '힘내', '포기하지 마', '너 자신을 믿어', '진정한 나를 찾아' 같은
  범용 자기계발서/상담사 클리셰 없이 자연스러운가. 클리셰가 있으면 낮은 점수.
- relevance: 사용자가 실제로 한 말에 맞는 답인가. 동문서답이면 낮은 점수.
- no_hallucination: 원작에 없는 사건을 지어내거나(예: 안 한 대사, 안 겪은 사건) 사실을 왜곡하지 않는가.
  문제 없으면 5점, 명백한 지어낸 내용이 있으면 1~2점.

JSON으로만 응답해라:
{
  "character_voice": 1~5,
  "naturalness": 1~5,
  "relevance": 1~5,
  "no_hallucination": 1~5,
  "comment": "한 줄 코멘트 (한국어)"
}"""


def build_character_brief(profiles: dict, character_name: str) -> str:
    c = get_character(profiles, character_name)
    return (
        f"이름: {c['name']} ({c['movie']})\n"
        f"정체성: {c['identity']}\n"
        f"성격: {', '.join(c['personality'][:3])}\n"
        f"말투: {', '.join(c['speech_style'][:3])}"
    )


def judge_response(character_brief: str, user_message: str, answer: str) -> dict:
    user_prompt = (
        f"[캐릭터 프로필]\n{character_brief}\n\n"
        f"[사용자 메시지]\n{user_message}\n\n"
        f"[AI 답변]\n{answer}"
    )
    resp = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(resp.choices[0].message.content)


def main():
    profiles = load_profiles(PROFILE_PATH)
    results = []

    for character, message in TEST_CASES:
        print(f"[{character}] {message}")
        result = character_run(character_name=character, user_message=message, history=[])
        answer = result["answer"]
        print(f"  → {answer}")

        brief = build_character_brief(profiles, character)
        try:
            scores = judge_response(brief, message, answer)
        except Exception as e:
            print(f"  [judge 실패] {e}")
            continue

        print(f"  판정: {scores}\n")
        results.append({
            "character": character, "message": message, "answer": answer, **scores,
        })

    if not results:
        print("평가 결과 없음")
        return

    # ── 집계 ──
    axes = ["character_voice", "naturalness", "relevance", "no_hallucination"]
    print("=" * 60)
    print(f"{'축':<20}{'평균':<8}")
    for axis in axes:
        avg = sum(r[axis] for r in results) / len(results)
        print(f"{axis:<20}{avg:.2f}")

    overall = sum(r[axis] for r in results for axis in axes) / (len(results) * len(axes))
    print(f"\n전체 평균: {overall:.2f} / 5.00  ({len(results)}개 케이스)")

    # 낮은 점수 케이스 하이라이트
    print("\n--- 3점 이하 항목이 있는 케이스 ---")
    for r in results:
        low = [a for a in axes if r[a] <= 3]
        if low:
            print(f"[{r['character']}] \"{r['message']}\" → {r['answer']}")
            print(f"  낮은 축: {low} | 코멘트: {r['comment']}")

    # 결과 저장
    out_path = _BASE_DIR / "eval" / "results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
