# meeting-summary-agent

네이버 클로바노트 TXT 파일을 자동 감지하거나, 웹에서 직접 회의를 녹음해 OpenAI API로 회의록을 생성하는 에이전트입니다. 결과는 Markdown 파일과 SQLite DB에 저장되고, 웹 화면에서 검색, 캘린더, 상세 회의록, 액션 아이템, Flow 공유 문구를 확인할 수 있습니다.

이 프로젝트는 새로 만든 독립 프로젝트입니다. 기존 회의록 프로젝트의 코드, 폴더, DB를 사용하지 않습니다.

## 폴더 구조

```text
meeting-summary-agent/
  app.py
  summarizer.py
  watcher.py
  transcriber.py
  database.py
  prompts.py
  requirements.txt
  README.md
  .env.example

  input/
    clova_txt/

  storage/
    raw/
    summaries/
    flow/
    audio/
    transcripts/

  data/
    meetings.db

  web/
    index.html
    style.css
    script.js
```

## 하는 일

1. TXT 방식: 기획팀이 `input/clova_txt/` 폴더에 클로바노트 TXT 파일을 넣으면 `watchdog` 감시기가 자동 감지합니다.
2. 웹 녹음 방식: 사용자가 웹에서 녹음 시작/종료를 누르면 브라우저 음성 파일이 서버로 업로드됩니다.
3. 녹음 파일은 `storage/audio/`, 전사 텍스트는 `storage/transcripts/`에 저장됩니다.
4. OpenAI STT가 음성을 텍스트로 변환하고, `summarizer.py`가 회의록 Markdown을 생성합니다.
5. 원문은 `storage/raw/`, 요약본은 `storage/summaries/`, Flow 공유문은 `storage/flow/`에 저장됩니다.
6. 회의록 메타데이터와 본문은 `data/meetings.db` SQLite DB에 저장됩니다.
7. 웹 화면은 Flask API에서 DB 데이터를 불러와 목록, 검색, 캘린더, 상세 화면을 표시합니다.
8. 회의록 상세 화면에서 삭제하면 DB 행과 관련 저장 파일이 함께 삭제됩니다.

## Mac에서 처음 실행하기

터미널에서 프로젝트 폴더로 이동합니다.

```bash
cd /Users/1thefull/Desktop/에이전트/meeting-summary-agent
```

Python 가상환경을 만듭니다.

```bash
python3 -m venv .venv
```

가상환경을 켭니다.

```bash
source .venv/bin/activate
```

필요한 패키지를 설치합니다.

```bash
pip install -r requirements.txt
```

환경 변수 파일을 만듭니다.

```bash
cp .env.example .env
```

`.env` 파일을 열어 `OPENAI_API_KEY`에 실제 OpenAI API 키를 넣습니다.

```text
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENAI_STT_MODEL=whisper-1
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
```

## 실행 방법

웹 서버와 TXT 자동 감시를 함께 실행합니다. 이제 `python app.py`만 실행해도 자동 감시가 기본으로 켜지고, 서버 시작 시 `input/clova_txt/` 안의 기존 TXT도 먼저 처리합니다.

```bash
python app.py
```

브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:5000
```

이제 클로바노트 TXT 파일을 아래 폴더에 넣으면 자동으로 처리됩니다.

```text
input/clova_txt/
```

## 웹 녹음 기능 사용하기

1. `python app.py`로 서버를 실행합니다.
2. 브라우저에서 `http://127.0.0.1:5000`에 접속합니다.
3. 상단의 `녹음 시작` 버튼을 누릅니다.
4. 브라우저가 마이크 권한을 요청하면 허용합니다.
5. 회의가 끝나면 `녹음 종료` 버튼을 누릅니다.
6. 화면에 업로드, 음성 변환, 요약 진행 상태가 표시됩니다.
7. 처리가 끝나면 회의록 목록과 캘린더가 자동으로 새로고침됩니다.
8. 완료 메시지와 녹음 시간은 3초 뒤 기본 상태로 자동 초기화됩니다.

웹 녹음 결과 저장 위치:

```text
storage/audio/        # 브라우저에서 업로드된 녹음 파일
storage/transcripts/  # STT로 변환된 텍스트
storage/raw/          # 요약에 사용된 원문 텍스트 복사본
storage/summaries/    # 회의록 Markdown
storage/flow/         # Flow 공유용 문구
```

녹음 기능에 필요한 환경 변수:

```text
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENAI_STT_MODEL=whisper-1
```

`OPENAI_STT_MODEL`은 기본값이 `whisper-1`입니다. OpenAI 계정에서 다른 음성 전사 모델을 사용하고 싶다면 이 값을 바꾸면 됩니다.

## 짧은 테스트 녹음 필터링

웹 녹음 후 STT 결과가 실제 회의 내용으로 보기 어려우면 GPT 요약을 실행하지 않습니다. 이 경우 DB에도 회의록을 저장하지 않고, 화면에는 아래 메시지를 표시합니다.

```text
회의 내용이 너무 짧아 회의록을 생성하지 않았습니다.
```

현재 필터 기준:

- 공백과 문장부호를 제외한 텍스트가 30자 미만인 경우
- `아아 테스트 테스트`, `마이크 테스트`, `하나 둘 셋`, `들리나요` 같은 테스트 발화
- `테스트`, `마이크`, `아아` 등 의미 없는 단어가 짧게 반복되는 경우

녹음 파일과 전사 텍스트는 확인을 위해 `storage/audio/`, `storage/transcripts/`에 남습니다. 회의록 DB에는 저장하지 않습니다.

## 회의 시간 자동 기록

모든 회의 시간은 한국 시간인 `Asia/Seoul` 기준으로 저장하고 표시합니다.

웹 녹음은 브라우저에서 녹음 시작 시각과 종료 시각을 자동 기록해 서버로 함께 보냅니다. 브라우저가 UTC ISO 형식으로 시간을 보내더라도 서버에서 `Asia/Seoul`로 변환한 뒤 아래 값을 DB에 저장합니다.

```text
meeting_start_time
meeting_end_time
duration_seconds
```

회의 길이는 `종료 시각 - 시작 시각`으로 초 단위 계산 후 화면에서 분 단위로 표시합니다.

예시:

```text
회의 날짜: 2026-05-20
시간: 15:12 ~ 15:13 (1분)
시작 시간: 15:12
종료 시간: 15:13
회의 길이: 1분
```

TXT 기반 회의록은 파일명이나 본문에서 시간을 찾으면 그 값을 사용하고, 찾지 못하면 TXT 파일의 수정 시각을 `Asia/Seoul` 기준으로 변환해 기본 시작 시간으로 사용합니다.

## 회의록 삭제

회의록 상세 화면의 `삭제` 버튼을 누르면 확인 창이 뜹니다. 확인하면 DB 행과 아래 관련 파일을 함께 삭제합니다.

```text
storage/audio/
storage/transcripts/
storage/raw/
storage/summaries/
storage/flow/
```

삭제 후 목록, 캘린더, 등록 건수는 자동으로 새로고침됩니다.

## 이미 폴더에 들어 있는 TXT 처리하기

이미 `input/clova_txt/` 안에 TXT 파일을 넣어 둔 상태라면 서버 시작 시 자동으로 처리됩니다. 웹 서버 실행 중에도 수동으로 다시 처리할 수 있습니다.

```bash
python app.py --process-existing
```

웹 서버 없이 기존 파일만 처리하려면 아래처럼 실행합니다.

```bash
python app.py --process-existing --no-web
```

자동 감시만 켜고 웹 서버를 띄우지 않으려면 아래처럼 실행합니다.

```bash
python app.py --no-web
```

자동 감시 없이 웹 서버만 띄우고 싶다면 아래처럼 실행합니다.

```bash
python app.py --no-watch
```

## API

회의록 목록:

```text
GET /api/meetings
```

회의록 상세:

```text
GET /api/meetings/1
```

회의록 삭제:

```text
DELETE /api/meetings/1
```

기존 TXT 수동 처리:

```text
POST /api/process-existing
```

특정 파일 수동 처리:

```text
POST /api/process-file
Content-Type: application/json

{"filename":"sample.txt"}
```

웹 녹음 파일 업로드:

```text
POST /api/recordings
Content-Type: multipart/form-data

audio=<녹음 파일>
```

## 회의록 출력 포맷

OpenAI API에는 아래 Markdown 구조를 지키도록 요청합니다.

```markdown
# 회의록 제목

## 회의 정보
- 날짜
- 시간

## 핵심 요약

## 주요 논의 내용

## 결정사항

## 액션 아이템
| 담당자 | 업무 | 상태 |
|---|---|---|

## 리스크 및 이슈

## 다음 액션

## Flow 공유용 요약
```

## 주의사항

- `data/meetings.db`가 실제 DB입니다.
- 웹 화면은 하드코딩 데이터가 아니라 Flask API를 통해 DB 데이터를 불러옵니다.
- 같은 파일명과 같은 원문 내용은 같은 해시로 인식되어 DB에서 업데이트됩니다.
- API 키가 없으면 웹 녹음의 음성 전사를 만들 수 없습니다. TXT 처리의 경우 요약 실패 시에도 `pending` 상태로 DB에 저장됩니다.
- 사내 회의록에는 민감한 내용이 포함될 수 있으므로 `.env`, `data/`, `storage/`는 외부 저장소에 공개하지 않는 것을 권장합니다.
