# CineVerse AI API 명세서

**Base URL**: `http://210.109.15.251`  
**Port**: 80 (HTTP)  
**Version**: 2.0.0

---

## 백엔드 반영 필요 사항 (액션 아이템)

이번 업데이트로 백엔드 코드에서 아래 항목을 확인/수정해주세요.

1. **`app/ai_client/chat.py` — `request_character_chat`**
   호출 URL을 `/chat` → **`/chat/auto`** 로 변경해야 합니다.
   `/chat`은 인텐트 분류 없이 무조건 캐릭터 대화만 하기 때문에, 캐릭터 대화 중 영화 추천을 요청해도 실제 검색 없이 캐릭터가 아는 지식으로만 답합니다. `/chat/auto`로 바꾸면 `character`는 그대로 고정되면서, 영화 추천 인텐트일 때만 자동으로 실제 검색 결과(`movies`)가 채워집니다. 응답 스키마는 `answer`/`character` 그대로 유지되고 `movies`, `intent` 필드만 추가되는 구조라 기존 파싱 코드 그대로 호환됩니다.

2. **`chat_service.py` — `process_group_chat_message`**
   반환값에서 `"rounds"`, `"movies"` 키가 오타 없이 정확히 들어가는지 확인해주세요 (`"rouds"`, `"movie"`처럼 철자가 틀리면 프론트가 못 읽습니다).

3. **그룹챗은 `/chat/group/auto` 사용 권장**
   `/chat/group`, `/chat/group/rounds`는 캐릭터 대화만 되고 영화 추천은 안 됩니다. 그룹챗에서 영화 추천까지 지원하려면 `request_group_chat`이 **`/chat/group/auto`**를 호출해야 합니다 (이미 반영되어 있다면 확인만 하시면 됩니다).

4. **캐릭터 이름 처리 — 이제 모든 엔드포인트에서 별칭 지원**
   `/chat`, `/chat/stream`, `/chat/group`, `/chat/group/rounds`, `/chat/group/auto` 전부 `character`/`characters`에 별칭을 넣어도 자동으로 정식 이름으로 변환됩니다 (예: `"아이언맨"` → `"토니 스타크"`). `/chat/auto`는 `character`를 아예 안 보내도 메시지 안의 별칭을 감지합니다.
   없는 캐릭터를 넘기면 모든 엔드포인트에서 `404 { "detail": "..." }` 로 응답합니다. 백엔드에서 이 케이스를 사용자에게 "지원하지 않는 캐릭터입니다" 식으로 안내하도록 처리되어 있는지 확인해주세요.

---

## 공통 사항

### history 형식
모든 엔드포인트의 `history` 필드는 동일한 형식을 사용합니다.

```json
[
  { "role": "user",      "content": "안녕" },
  { "role": "assistant", "content": "어, 뭔일이야." }
]
```

### 오류 응답
```json
{ "detail": "오류 메시지" }
```

| 코드 | 의미 |
|------|------|
| 400  | 잘못된 요청 (필수 필드 누락, 캐릭터 수 초과 등) |
| 404  | 캐릭터를 찾을 수 없음 |
| 500  | 서버 내부 오류 |

---

## 엔드포인트

### GET /health
서버 상태 확인

**응답**
```json
{
  "status": "ok",
  "version": "2.0.0",
  "components": {
    "llm": "ok",
    "milvus": "ok (3 collections)",
    "embedder": "ok"
  }
}
```

- `status`: `"ok"` | `"degraded"`

---

### POST /chat/auto
인텐트를 자동 분류해 영화 추천 또는 캐릭터 대화로 라우팅합니다.  
**백엔드에서 주로 사용하는 엔드포인트입니다.**

**요청**
```json
{
  "character": "마석도",
  "message":   "취업 준비가 막막해요.",
  "history":   []
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| character | string | 선택 | 캐릭터 이름. 생략 가능 (아래 "캐릭터 자동 감지" 참고) |
| message   | string | **필수** | 사용자 메시지 |
| history   | array  | 선택 | 대화 히스토리 (기본값: `[]`) |

**응답**
```json
{
  "intent":    "character_chat",
  "character": "마석도",
  "answer":    "목표 하나 정하고 밀어붙여봐.",
  "movies":    []
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| intent    | string | `"character_chat"` \| `"movie_recommend"` |
| character | string | 응답에 실제로 적용된 캐릭터 이름. 캐릭터 없이 범용 대화로 응답했으면 빈 문자열 `""` |
| answer    | string | 캐릭터(또는 범용 어시스턴트) 답변 |
| movies    | array  | 영화 추천 시 영화 목록, 캐릭터 대화 시 `[]` |

#### 캐릭터 자동 감지 (character 필드를 생략했을 때)

`character`를 안 보내고 `message`만 보내도 됩니다. 인텐트가 `character_chat`으로 분류되면 메시지 내용을 보고 다음 순서로 판단합니다.

1. **50인 명단(또는 별칭) 중 이름이 언급됨** → 그 캐릭터로 자동 전환해서 응답. 응답의 `character` 필드에 어떤 캐릭터가 적용됐는지 나오므로, 이후 턴부터는 그 값을 `character`로 넘겨서 대화를 이어가면 됩니다.
   - 별칭 예시: "아이언맨"→토니 스타크, "스파이더맨"→피터 파커, "배트맨"→브루스 웨인, "헐크"→브루스 배너, "캡틴"→스티브 로저스, "덤블도어"→알버스 덤블도어, "스네이프"→세베루스 스네이프, "다이애나"→원더우먼, "클라크 켄트"→슈퍼맨, "스트레인지"→닥터 스트레인지 등
2. **"OOO랑 얘기하고 싶어", "OOO 불러줘"처럼 캐릭터를 요청하는 문구는 있는데 명단에 없는 이름** → `character: ""`, 아래처럼 안내 + 랜덤 3명 추천
   ```json
   { "intent": "character_chat", "character": "", "answer": "앗, 해당 캐릭터는 아직 업데이트 전입니다. 대신 이 친구들은 어때요? 닥터 스트레인지, 알버스 덤블도어, 엘사", "movies": [] }
   ```
3. **캐릭터 언급이 전혀 없음** (예: "요즘 힘들어") → `character: ""`, 범용 대화 어시스턴트로 응답

---

### POST /chat
특정 캐릭터와 1:1 대화

**요청**
```json
{
  "character": "마석도",
  "message":   "요즘 힘들어요.",
  "history":   [],
  "use_rag":   true
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| character | string | **필수** | 캐릭터 이름 (별칭 가능, 자동으로 정식 이름 변환) |
| message   | string | **필수** | 사용자 메시지 |
| history   | array  | 선택 | 대화 히스토리 |
| use_rag   | bool   | 선택 | RAG 사용 여부 (기본값: `true`) |

**응답**
```json
{
  "character":    "마석도",
  "answer":       "그냥 버텨. 답은 행동에 있어.",
  "finish_reason": "stop",
  "rag_used":     true
}
```

> ⚠️ `/chat`은 인텐트 분류가 없어 영화 추천 요청에도 실제 검색이 안 됩니다 (액션 아이템 1번 참고 — `/chat/auto` 사용 권장).

---

### POST /chat/group
여러 캐릭터가 동시에 사용자 메시지에 답변 (단순 1라운드)

**요청**
```json
{
  "characters": ["마석도", "토르", "조커"],
  "message":    "스트레스가 심해.",
  "history":    []
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| characters | array  | **필수** | 캐릭터 이름 목록 (2~5명). 별칭 가능 (자동으로 정식 이름 변환) |
| message    | string | **필수** | 사용자 메시지 |
| history    | array  | 선택 | 대화 히스토리 |

**응답**
```json
{
  "responses": [
    { "character": "마석도", "answer": "행동해.", "finish_reason": "stop", "rag_used": false },
    { "character": "토르",   "answer": "정면으로 맞서라.", "finish_reason": "stop", "rag_used": false },
    { "character": "조커",   "answer": "즐겨봐.", "finish_reason": "stop", "rag_used": false }
  ]
}
```

**에러**: `characters`에 명단·별칭 어디에도 없는 이름이 포함되면 `404 { "detail": "캐릭터를 찾을 수 없습니다: OOO" }`

---

### POST /chat/group/rounds
여러 캐릭터가 대화하며 서로 반응하는 2라운드 그룹 채팅

- **Round 1**: 각 캐릭터가 사용자 메시지에 순차 답변
- **Round 2**: 1라운드 대화를 보고 각 캐릭터가 자율 반응. 할 말 없으면 침묵 (응답 목록에서 제외)

**요청** (동일: `/chat/group` 과 같은 형식)
```json
{
  "characters": ["마석도", "장첸", "토르"],
  "message":    "스트레스가 심해.",
  "history":    []
}
```

**응답**
```json
{
  "rounds": [
    {
      "round": 1,
      "label": "첫 번째 답변",
      "responses": [
        { "character": "마석도", "answer": "행동해.", "finish_reason": "stop", "rag_used": false },
        { "character": "장첸",   "answer": "약한 소리.", "finish_reason": "stop", "rag_used": false },
        { "character": "토르",   "answer": "정면으로 맞서라.", "finish_reason": "stop", "rag_used": false }
      ]
    },
    {
      "round": 2,
      "label": "반응",
      "responses": [
        { "character": "장첸", "answer": "마석도 말도 맞지만 더 냉정하게 봐.", "finish_reason": "stop", "rag_used": false }
      ]
    }
  ]
}
```

> Round 2 `responses`는 반응한 캐릭터만 포함 (0개일 수도 있음)

**에러**: `/chat/group`과 동일하게 명단·별칭에 없는 캐릭터가 있으면 `404`

---

### POST /chat/group/auto
인텐트를 자동 분류해 그룹 채팅 또는 그룹 영화 추천으로 라우팅. **그룹 채팅에서 영화 추천도 받고 싶으면 이 엔드포인트를 씁니다.**

- 영화 추천 인텐트: 영화를 한 번만 검색하고, 각 캐릭터가 같은 목록을 자기 톤으로 소개(라운드1) → 서로의 추천에 반응(라운드2)
- 캐릭터 대화 인텐트: `/chat/group/rounds`와 동일하게 동작 (영화 검색 없음)

**요청** (`/chat/group`과 동일한 형식)
```json
{
  "characters": ["마석도", "장첸", "토르"],
  "message":    "액션 영화 추천해줘",
  "history":    []
}
```

**응답**
```json
{
  "intent": "movie_recommend",
  "movies": [
    { "title": "업그레이드", "year": 2018, "poster_url": "...", "...": "..." }
  ],
  "rounds": [
    {
      "round": 1,
      "label": "첫 번째 답변",
      "responses": [
        { "character": "마석도", "answer": "'업그레이드'는 내가 좋아하는 스타일이야...", "finish_reason": "stop", "rag_used": false }
      ]
    },
    {
      "round": 2,
      "label": "반응",
      "responses": []
    }
  ]
}
```

- `intent`가 `"character_chat"`이면 `movies`는 빈 배열
- `movies` 필드 구조는 `/recommend` 응답과 동일 (`poster_url` 포함)

---

### POST /chat/stream
캐릭터 1:1 대화를 SSE(Server-Sent Events)로 스트리밍. 토큰 단위로 실시간 수신 가능.

**요청** (`/chat`과 동일한 형식)
```json
{
  "character": "마석도",
  "message":   "요즘 힘든 일이 많아",
  "history":   [],
  "use_rag":   true
}
```

**응답**: `Content-Type: text/event-stream`

```
data: "힘든"

data: " 건"

data: " 언제나"

...

data: [DONE]
```

- 각 `data:` 라인은 JSON 문자열로 인코딩된 토큰 조각 하나
- 스트림 종료 시 `data: [DONE]` 전송
- 중간 에러 시 `data: {"error": "메시지"}` 후 바로 `[DONE]`

**제약**
- `character` 필수 — 영화 추천/자동 인텐트 분류(`/chat/auto`) 기능 없음, 캐릭터 1:1 대화 전용
- 그룹 채팅 미지원

---

### POST /recommend
영화 추천 (캐릭터 없이 순수 추천도 가능)

**요청**
```json
{
  "message":    "액션 영화 추천해줘.",
  "character":  "마석도",
  "history":    [],
  "genre":      "액션",
  "actor":      null,
  "director":   null,
  "language":   null,
  "year_from":  2010,
  "year_to":    2024,
  "min_rating": 7.0
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| message    | string | **필수** | 사용자 메시지 |
| character  | string | 선택 | 캐릭터 스타일로 추천 |
| history    | array  | 선택 | 대화 히스토리 |
| genre      | string | 선택 | 장르 필터 |
| actor      | string | 선택 | 배우 필터 |
| director   | string | 선택 | 감독 필터 |
| language   | string | 선택 | 언어 필터 |
| year_from  | int    | 선택 | 개봉연도 시작 |
| year_to    | int    | 선택 | 개봉연도 끝 |
| min_rating | float  | 선택 | 최소 평점 |

**응답**
```json
{
  "answer": "이런 영화 어때요.",
  "movies": [
    {
      "title":        "범죄도시2",
      "year":         2022,
      "genres":       "액션, 범죄",
      "director":     "이상용",
      "cast":         "마동석, 손석구",
      "vote_average": 7.3,
      "overview":     "...",
      "poster_url":   "https://image.tmdb.org/t/p/w500/xxxxx.jpg",
      "tmdb_id":      "123456"
    }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| title        | string | 영화 제목 |
| year         | int    | 개봉연도 |
| genres       | string | 장르 |
| director     | string | 감독 |
| cast         | string | 출연진 |
| vote_average | float  | 평점 |
| overview     | string | 줄거리 |
| poster_url   | string | 포스터 이미지 전체 URL (TMDB CDN, `w500` 사이즈). 포스터 없으면 빈 문자열 |
| tmdb_id      | string | TMDB 영화 ID |

---

## 사용 가능한 캐릭터 (50개)

| 출처 | 캐릭터 |
|------|--------|
| 범죄도시 시리즈 | 마석도, 장첸, 강해상, 서도철, 조태오, 차태식 |
| 한국 영화 | 고니, 고광렬, 강림, 해원맥, 우장훈, 안옥윤, 석우, 화림, 이순신 |
| 마블 | 토니 스타크, 스티브 로저스, 피터 파커, 토르, 로키, 닥터 스트레인지, 브루스 배너, 스타로드, 데드풀, 타노스 |
| DC | 브루스 웨인, 조커, 할리 퀸, 슈퍼맨, 원더우먼 |
| 해리포터 | 해리포터, 헤르미온느, 론 위즐리, 세베루스 스네이프, 알버스 덤블도어 |
| 반지의 제왕 | 간달프, 프로도, 골룸 |
| 기타 | 네오, 쿠퍼, 코브, 폴 아트레이데스, 오펜하이머, 존 윅, 에단 헌트, 매버릭, 잭 스패로우, 엘사, 슈렉, 우디 |
