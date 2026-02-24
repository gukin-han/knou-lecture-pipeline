# CLAUDE.md — 프로젝트 가이드

이 파일은 Claude Code 세션에서 이 프로젝트를 반복적으로 작업할 때 참고하는 컨텍스트 문서입니다.

---

## 프로젝트 개요

방송통신대학교(KNOU) 강의 MP3 파일을 읽을 수 있는 마크다운 문서로 자동 변환하는 파이프라인.

- **STT**: `faster-whisper` (로컬, 오프라인, 한국어 특화 initial_prompt)
- **LLM Pass 1**: 텍스트 교정 (구두점, 필러 제거, CS 용어 복원)
- **LLM Pass 2**: 마크다운 구조화 (헤더, 표, 코드블록, 복잡도 표기)
- **Web UI**: FastAPI + SSE 실시간 진행률, 드래그앤드롭 업로드·다운로드
- **재시작 내성**: 세그먼트·청크 단위 중간 저장, 재실행 시 완료된 지점부터 재개

---

## 빠른 실행

```bash
# 최초 실행 (이미지 빌드 포함)
docker compose up --build

# 이후 실행
docker compose up

# 백그라운드 실행
docker compose up -d

# 중지
docker compose down
```

Web UI: **http://localhost:8000**

---

## 환경 변수 (.env)

`.env.example`을 복사해서 사용:

```bash
cp .env.example .env
```

주요 설정:

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `LLM_PROVIDER` | `openai` | `openai` 또는 `anthropic` |
| `OPENAI_API_KEY` | — | OpenAI API 키 |
| `OPENAI_MODEL` | `gpt-4o` | 사용 모델 |
| `ANTHROPIC_API_KEY` | — | Anthropic API 키 |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | 사용 모델 |
| `WHISPER_MODEL_SIZE` | `small` | `tiny` · `small` · `medium` · `large-v3` |
| `CHUNK_SIZE` | `6000` | LLM 청크 크기 (문자 수) |

---

## 프로젝트 구조

```
knou-lecture-pipeline/
├── CLAUDE.md                # 이 파일
├── config/settings.py       # Pydantic BaseSettings (.env 자동 로드)
├── pipeline/
│   ├── llm_client.py        # LLM 벤더 추상화 (Anthropic / OpenAI)
│   ├── transcriber.py       # faster-whisper STT (세그먼트별 flush)
│   ├── cleaner.py           # LLM Pass 1: 텍스트 교정
│   ├── structurer.py        # LLM Pass 2: 마크다운 구조화
│   └── processor.py         # 파이프라인 오케스트레이터
├── web/
│   ├── app.py               # FastAPI 엔드포인트
│   ├── job_manager.py       # 작업 큐 + SSE 이벤트 배포
│   └── static/              # HTML / CSS / JS
├── watcher/
│   ├── cli.py               # Click CLI (watch / process / resume)
│   └── folder_watcher.py    # watchfiles 기반 폴더 감시
├── prompts/
│   ├── pass1_cleanup.txt    # CS 특화 교정 프롬프트
│   └── pass2_structure.txt  # CS 특화 구조화 프롬프트
├── utils/
│   ├── file_utils.py        # 문장 경계 기반 청크 분할
│   ├── logger.py
│   └── retry.py             # tenacity 재시도 데코레이터
├── data/
│   ├── input/               # MP3 입력 위치
│   ├── output/              # 최종 .md 출력
│   ├── intermediate/        # 중간 파일 (재시작 지원)
│   ├── processed/           # 완료된 MP3 보관
│   └── failed/              # 실패한 파일 격리
└── examples/                # 강의별 결과물 샘플 (원본 + 강화본)
    └── 컴퓨터보안/
        ├── KNOU255800120261001.md   # 원본 (파이프라인 출력)
        ├── KNOU255800120261001e.md  # 강화본 (Mermaid·표 추가)
        ├── KNOU255800120261002.md
        └── KNOU255800120261002e.md
```

---

## 파일 네이밍 규칙

KNOU 파일명 패턴: `KNOU{과목코드}{강의번호}.md`

| 파일 | 설명 |
|------|------|
| `KNOU255800120261001.md` | 파이프라인 출력 원본 (자동 생성) |
| `KNOU255800120261001e.md` | 강화본 (`e` 접미사 = enhanced) |

---

## Git / GitHub 워크플로

이 저장소는 **개인 계정 (`gukin-han`)** SSH 키를 사용한다.

```bash
# SSH 설정 확인 (~/.ssh/config)
# Host github-personal
#   HostName github.com
#   User git
#   IdentityFile ~/.ssh/id_ed25519_personal

# remote URL 확인
git remote -v
# origin  git@github-personal:gukin-han/knou-lecture-pipeline.git

# 커밋 & 푸시
git add <파일>
git commit -m "메시지"
git push origin main

# 계정 전환이 필요한 경우
gh auth switch --user gukin-han
```

---

## 강의 MD 파일 강화 작업 (e 파일 생성)

파이프라인이 출력한 원본 `.md` 파일을 읽고, Mermaid 다이어그램·비교표·실무 내용을 추가한 `e` 버전을 만드는 작업.

### 프로세스

1. 원본 파일 읽기: `examples/{과목명}/KNOU...NNN.md`
2. 강화본 작성: `examples/{과목명}/KNOU...NNNe.md`
   - 파일 상단에 **목차(TOC)** 추가
   - 핵심 개념을 **Mermaid** 다이어그램으로 시각화
   - 용어·개념 **비교표** 추가
   - **실무 적용** 섹션 추가 (현업에서 쓰이는 도구·프로토콜·사례)
   - **역사 타임라인** 추가 (Mermaid timeline)
3. 커밋·푸시

### Mermaid 다이어그램 선택 기준

| 상황 | 다이어그램 종류 |
|------|---------------|
| 개념 간 관계·분류 | `mindmap` |
| 데이터·프로세스 흐름 | `flowchart LR` / `flowchart TD` |
| 시간 순서 | `timeline` |
| 시스템 간 메시지 교환 | `sequenceDiagram` |
| 상태 전이 | `stateDiagram-v2` |

### 작업 예시 프롬프트

```
examples/{과목명}/ 안의 KNOU...NNN.md 파일들을 읽고, mermaid 다이어그램·표·실무 내용을 추가하여
목차(TOC) 포함한 강화본을 e 접미사 파일로 저장해줘.
완료 후 커밋·푸시도 해줘.
```

---

## examples 폴더 구성 원칙

- `examples/{과목명}/` 폴더에 강의별로 묶어서 보관
- 한 학기 강의가 끝나도 계속 누적
- 원본(파이프라인 출력)과 강화본(e 파일) 모두 보관
- `data/` 폴더(중간파일·MP3)는 `.gitignore`로 제외, `examples/`만 커밋

---

## 재시작 내성 구조

파이프라인이 중간에 종료돼도 `data/intermediate/`의 파일을 재사용해 이어서 실행:

| 중단 시점 | 저장 파일 | 재시작 동작 |
|-----------|-----------|-------------|
| STT 중 | `{stem}.stt.txt` (세그먼트마다 flush) | `.stt.txt` 재사용, STT 건너뜀 |
| LLM Pass 1 중 | `.clean_chunks/clean.NNNN.txt` | 완료 청크 재사용, 미완료부터 재개 |
| LLM Pass 2 중 | `.struct_chunks/struct.NNNN.txt` | 완료 청크 재사용, 미완료부터 재개 |

---

## 자주 발생하는 문제와 해결법

### Docker 빌드 캐시 오류
```bash
docker builder prune -f
docker compose build
```

### Whisper 모델 다운로드 지연
첫 실행 시 `whisper-cache` 볼륨에 모델 다운로드 (small: ~244MB). 이후 실행은 캐시 사용.

### LLM API 오류
`utils/retry.py`의 tenacity 재시도(지수 백오프)가 자동 처리. 반복 실패 시 해당 청크 파일 삭제 후 재실행.

### `file_utils.py` 정규식 오류
청크 분할 정규식에 따옴표 포함 시 raw string 삼중따옴표 필요:
```python
_SENTENCE_END = re.compile(r"""[.!?][)\]"']*\s+""")
```
