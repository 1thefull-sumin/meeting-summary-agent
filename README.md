# meeting-summary-agent

네이버 클로바노트 TXT 파일을 자동 감지하거나, 웹에서 직접 회의를 녹음해 OpenAI API로 회의록을 생성하는 에이전트입니다. 결과는 Markdown 파일과 MySQL DB에 저장되고, 웹 화면에서 검색, 캘린더, 상세 회의록, 액션 아이템, Flow 공유 문구를 확인할 수 있습니다.

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

  schema.sql

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
6. 회의록 메타데이터와 본문은 MySQL `MEETING_AGENT_DEV` DB에 저장됩니다.
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
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=MEETING_AGENT_DEV
```

## MySQL 설정

Sequel Ace에서 로컬 MySQL에 접속한 뒤 [schema.sql](/Users/1thefull/Desktop/에이전트/meeting-summary-agent/schema.sql)의 전체 SQL을 실행합니다.

실행되는 주요 작업:

```sql
CREATE DATABASE IF NOT EXISTS MEETING_AGENT_DEV
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE MEETING_AGENT_DEV;

CREATE TABLE meetings (...);
CREATE TABLE meeting_action_items (...);
CREATE TABLE meeting_files (...);
```

테이블 관계:

- `meeting_action_items.meeting_id`는 `meetings.id`를 참조합니다.
- `meeting_files.meeting_id`는 `meetings.id`를 참조합니다.
- 회의록 삭제 시 action item과 file row는 `ON DELETE CASCADE`로 같이 삭제됩니다.
- 실제 파일은 Flask 삭제 API에서 `storage/` 아래 파일을 같이 지웁니다.

MySQL 문자셋은 `utf8mb4`, 시간 기준은 애플리케이션에서 `Asia/Seoul`로 처리합니다. DB 연결마다 `SET time_zone = '+09:00'`을 실행합니다.

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

누락된 녹음 회의록 복구:

```text
POST /api/recover-recordings
```

CLI로도 복구할 수 있습니다.

```bash
python app.py --recover-recordings --no-web
```

복구 기능은 `storage/temp_audio/`, `storage/audio/`, `storage/transcripts/`, `storage/summaries/`, MySQL 상태를 비교합니다. 브라우저가 강제 종료되어 `temp_audio`에 chunk만 남은 경우 먼저 `storage/audio/`의 원본 파일로 조립한 뒤 STT와 요약을 다시 시도합니다. 전사 TXT 내용은 `raw_text`로 MySQL에 저장하고, 가능한 경우 GPT 요약을 다시 실행합니다. 요약이 실패하면 `pending` 상태로 row를 남깁니다. 테스트 발화처럼 너무 짧은 전사는 `skipped` 상태로 저장합니다.

## 녹음 유실 방지 구조

- 녹음 시작 즉시 서버가 `storage/temp_audio/<recording_id>/` 세션을 만들고 브라우저가 약 5초 단위 chunk를 업로드합니다.
- 녹음 종료 시 서버는 chunk를 합쳐 `storage/audio/YYYYMMDD_HHMMSS_meeting_uuid.webm` 원본 파일을 먼저 저장합니다.
- 원본 audio 저장 직후 MySQL `meetings`에 `status='uploaded'` row를 먼저 생성합니다.
- 이후 STT, GPT 요약, Markdown/Flow 저장을 진행합니다.
- STT 실패 시에도 `storage/audio/` 원본은 삭제하지 않고 `stt_status='error'`, `summary_status='pending'`, `last_error`를 남깁니다.
- GPT 실패 시에도 audio/transcript는 유지하고 `summary_status='error'` 또는 `pending` 상태로 복구 가능하게 둡니다.
- DB 저장 실패는 `storage/error_logs/failed_meetings.jsonl`에 실패 시간, 파일명, 오류 내용을 JSONL로 기록합니다.
- 삭제 버튼은 DB row를 `status='deleted'`로 바꾸는 soft delete입니다. 원본 audio는 자동 삭제하지 않으며 `deleted_at`, `trash_until`로 휴지통 보관 기간을 기록합니다.

새로 추가된 `meetings` 상태 컬럼:

```text
upload_status
stt_status
summary_status
db_status
last_error
retry_count
deleted_at
trash_until
```

기존 DB를 쓰고 있다면 서버 시작 시 자동 migration이 실행됩니다. Sequel Ace에서 직접 반영하려면 최신 `schema.sql`의 `meetings` 컬럼 정의를 확인해 적용하세요.

## 클로바노트 TXT + audio 자동 등록

클로바노트에서 받은 TXT와 녹음 파일을 아래 폴더에 넣으면 watcher가 자동으로 회의록을 생성합니다.

```text
input/clova_txt/
input/clova_audio/
```

같은 파일명 stem을 자동 매칭합니다.

```text
input/clova_txt/회의1.txt
input/clova_audio/회의1.m4a
```

지원 audio 포맷:

```text
mp3, m4a, wav, webm
```

처리 방식:

```text
TXT + audio: TXT를 transcript로 사용하고 audio_path도 함께 저장
TXT만 있음: TXT만으로 요약/DB 저장
audio만 있음: Whisper STT로 transcript 생성 후 요약/DB 저장
```

중복 방지는 TXT/audio 파일 내용을 기준으로 만든 `sha256` hash를 사용합니다. 같은 파일을 다시 넣으면 새 row를 계속 늘리지 않고 같은 hash 기준으로 업데이트됩니다.

처리 후 원본 입력 파일은 자동 이동됩니다.

```text
input/clova_txt/processed/
input/clova_audio/processed/

input/clova_txt/failed/
input/clova_audio/failed/
```

서버 실행:

```bash
cd /Users/1thefull/Desktop/에이전트/meeting-summary-agent
.venv/bin/python app.py
```

서버 시작 시 `input/clova_txt/`, `input/clova_audio/` 안에 이미 들어 있는 파일도 한 번 확인합니다. 새 파일을 넣으면 터미널에 `[WATCHER]`, `[CLOVA]`, `[STT]`, `[SUMMARY]`, `[DB]` 로그가 순서대로 표시됩니다.

웹 상세 화면에서는 저장된 회의록마다 다음을 확인할 수 있습니다.

```text
원본 audio 재생
transcript 원문 보기
Markdown 회의록 보기
Flow 공유 문구 보기
```

원본 오디오는 파일 경로를 직접 노출하지 않고 아래 API를 통해 안전하게 재생합니다.

```text
GET /api/meetings/<id>/audio
```

지원 형식은 `webm`, `m4a`, `mp3`, `wav`입니다. 회의록에 `audio_path`가 없으면 상세 화면에 “연결된 원본 오디오가 없습니다.”라고 표시됩니다. `status=deleted`로 soft delete된 회의록은 상세 조회와 오디오 재생이 모두 차단됩니다.

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

- `MEETING_AGENT_DEV` MySQL DB가 실제 DB입니다. SQLite `data/meetings.db`는 더 이상 사용하지 않습니다.
- 웹 화면은 하드코딩 데이터가 아니라 Flask API를 통해 DB 데이터를 불러옵니다.
- 같은 파일명과 같은 원문 내용은 같은 해시로 인식되어 DB에서 업데이트됩니다.
- API 키가 없으면 웹 녹음의 음성 전사를 만들 수 없습니다. TXT 처리의 경우 요약 실패 시에도 `error` 상태와 `error_message`를 MySQL에 저장합니다.
- 사내 회의록에는 민감한 내용이 포함될 수 있으므로 `.env`, `data/`, `storage/`는 외부 저장소에 공개하지 않는 것을 권장합니다.
