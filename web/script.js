let meetings = [];
let activeFilter = "all";
let selectedDate = null;
let selectedId = null;
let calendarYear = new Date().getFullYear();
let calendarMonth = new Date().getMonth();

const search = document.querySelector("#search");
const filters = Array.from(document.querySelectorAll(".filter[data-filter]"));
const refresh = document.querySelector("#refresh");
const list = document.querySelector("#meetingList");
const detail = document.querySelector("#detail");
const totalCount = document.querySelector("#totalCount");
const visibleCount = document.querySelector("#visibleCount");
const selectedDateTitle = document.querySelector("#selectedDateTitle");
const calendarTitle = document.querySelector("#calendarTitle");
const calendarSubtitle = document.querySelector("#calendarSubtitle");
const calendarGrid = document.querySelector("#calendarGrid");
const recordingBadge = document.querySelector("#recordingBadge");
const recordingStatus = document.querySelector("#recordingStatus");
const recordingTimer = document.querySelector("#recordingTimer");
const startRecording = document.querySelector("#startRecording");
const stopRecording = document.querySelector("#stopRecording");
const resetRecording = document.querySelector("#resetRecording");
const recoveryStatus = document.querySelector("#recoveryStatus");
const recoveryActions = Array.from(document.querySelectorAll(".recoveryAction"));

let mediaRecorder = null;
let recordingChunks = [];
let pendingChunkUploads = [];
let recordingSessionId = "";
let recordingChunkSequence = 0;
let recordingStartedAt = 0;
let recordingStartedAtIso = "";
let recordingEndedAtIso = "";
let recordingTimerId = null;
let recordingResetTimerId = null;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;"
  }[char]));
}

async function loadMeetings() {
  const response = await fetch("/api/meetings");
  meetings = await response.json();
  totalCount.textContent = meetings.length;
  if (meetings[0]) {
    calendarYear = Number(meetings[0].date.slice(0, 4));
    calendarMonth = Number(meetings[0].date.slice(5, 7)) - 1;
  }
  render();
}

function filteredMeetings() {
  const query = search.value.trim().toLowerCase();
  return meetings.filter(item => {
    const matchesSearch = !query || String(item.search_text || "").toLowerCase().includes(query);
    const matchesFilter = activeFilter === "all"
      || (activeFilter === "done" && item.status === "done")
      || (activeFilter === "pending" && item.status === "pending")
      || (activeFilter === "actions" && item.has_action_items);
    return matchesSearch && matchesFilter;
  });
}

function groupByDate(items) {
  return items.reduce((acc, item) => {
    (acc[item.date] ||= []).push(item);
    return acc;
  }, {});
}

function monthLabel(year, month) {
  return `${year}년 ${String(month + 1).padStart(2, "0")}월`;
}

function dateKey(year, month, day) {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function currentMonthMeetings(items) {
  const prefix = `${calendarYear}-${String(calendarMonth + 1).padStart(2, "0")}`;
  return items.filter(item => item.date.startsWith(prefix));
}

function renderCalendar() {
  const items = filteredMeetings();
  const byDate = groupByDate(items);
  const firstDay = new Date(calendarYear, calendarMonth, 1).getDay();
  const daysInMonth = new Date(calendarYear, calendarMonth + 1, 0).getDate();
  const monthItems = currentMonthMeetings(items);

  calendarTitle.textContent = monthLabel(calendarYear, calendarMonth);
  calendarSubtitle.textContent = `${monthItems.length}건 표시 중`;

  const cells = [];
  for (let i = 0; i < firstDay; i += 1) {
    cells.push('<div class="calendarCell emptyCell"></div>');
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    const key = dateKey(calendarYear, calendarMonth, day);
    const count = (byDate[key] || []).length;
    const classes = ["calendarCell", "calendarDay", count ? "hasMeeting" : "noMeeting", selectedDate === key ? "selectedDate" : ""];
    cells.push(`
      <button class="${classes.join(" ")}" data-date="${key}" type="button">
        <span class="dayNumber">${day}</span>
        ${count ? `<span class="meetingCount">${count}건</span>` : ""}
      </button>
    `);
  }
  calendarGrid.innerHTML = cells.join("");
  calendarGrid.querySelectorAll(".calendarDay").forEach(button => {
    button.addEventListener("click", () => {
      selectedDate = button.dataset.date;
      const dateItems = filteredMeetings().filter(item => item.date === selectedDate);
      selectedId = dateItems[0]?.id || null;
      render();
    });
  });
}

function renderList() {
  const items = filteredMeetings();
  const shownItems = selectedDate ? items.filter(item => item.date === selectedDate) : currentMonthMeetings(items);
  visibleCount.textContent = `${shownItems.length}건`;
  selectedDateTitle.textContent = selectedDate ? `${selectedDate} 회의록` : `${monthLabel(calendarYear, calendarMonth)} 회의록`;
  list.innerHTML = shownItems.map(item => `
    <button class="meetingCard ${item.id === selectedId ? "selected" : ""}" data-id="${item.id}" type="button">
      <span class="cardTitle">${escapeHtml(item.title)}</span>
      <span class="cardMeta">${escapeHtml(item.date)} ${meetingTimeLabel(item) ? "· " + escapeHtml(meetingTimeLabel(item)) : ""} · ${escapeHtml(statusLabel(item.status))}</span>
      <span class="cardSummary">${escapeHtml(summaryPreview(item))}</span>
      <span class="tagRow">
        <em>${escapeHtml(item.source_filename)}</em>
        ${item.has_action_items ? "<em>액션 포함</em>" : ""}
      </span>
    </button>
  `).join("") || '<div class="empty">표시할 회의록이 없습니다.</div>';

  list.querySelectorAll(".meetingCard").forEach(button => {
    button.addEventListener("click", () => {
      selectedId = Number(button.dataset.id);
      selectedDate = meetings.find(item => item.id === selectedId)?.date || selectedDate;
      render();
    });
  });
}

function summaryPreview(item) {
  return (item.key_summary || item.decisions || item.next_actions || "요약 내용을 확인하세요.")
    .replace(/[#>*|`-]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 120);
}

async function renderDetail() {
  if (!selectedId) {
    detail.innerHTML = '<div class="empty">달력에서 날짜를 선택하거나 회의록을 선택하세요.</div>';
    return;
  }
  const response = await fetch(`/api/meetings/${selectedId}`);
  if (!response.ok) {
    detail.innerHTML = '<div class="empty">회의록을 불러오지 못했습니다.</div>';
    return;
  }
  const item = await response.json();
  detail.innerHTML = `
    <div class="detailTop">
      <span class="badge">${escapeHtml(statusLabel(item.status))}</span>
      <h2>${escapeHtml(item.title)}</h2>
      <div class="metaGrid">
        <span><b>회의 날짜</b>${escapeHtml(item.date)}</span>
        <span><b>시간</b>${escapeHtml(meetingTimeLabel(item) || "-")}</span>
        <span><b>시작 시간</b>${escapeHtml(item.meeting_start_time || "-")}</span>
        <span><b>종료 시간</b>${escapeHtml(item.meeting_end_time || "-")}</span>
        <span><b>회의 길이</b>${escapeHtml(item.duration_label || "-")}</span>
        <span><b>원본</b>${escapeHtml(item.source_filename)}</span>
        <span><b>상태</b>${escapeHtml(statusLabel(item.status))}</span>
        <span><b>업로드</b>${escapeHtml(item.upload_status || "-")}</span>
        <span><b>STT</b>${escapeHtml(item.stt_status || "-")}</span>
        <span><b>요약</b>${escapeHtml(item.summary_status || "-")}</span>
        <span><b>재시도</b>${escapeHtml(item.retry_count || 0)}</span>
        <span><b>Markdown</b>${escapeHtml(item.summary_path || "-")}</span>
        <span><b>Flow 공유문</b>${escapeHtml(item.flow_path || "-")}</span>
      </div>
      ${item.last_error ? `<p class="errorText">${escapeHtml(item.last_error)}</p>` : ""}
      <div class="detailActions">
        <button class="deleteButton" data-delete-id="${item.id}" type="button">삭제</button>
      </div>
    </div>
    ${item.audio_path ? `
      <section class="section">
        <h3>원본 audio</h3>
        <audio class="audioPlayer" controls src="${mediaUrl(item.audio_path)}"></audio>
      </section>
    ` : ""}
    <section class="section">
      <h3>transcript</h3>
      <details class="transcriptBox">
        <summary>원문 보기</summary>
        <pre>${escapeHtml(item.raw_text || "저장된 transcript가 없습니다.")}</pre>
      </details>
    </section>
    <section class="section finalMarkdown">${markdownToHtml(item.markdown || "")}</section>
    <section class="section">
      <h3>Flow 공유 문구</h3>
      <pre class="flowBox">${escapeHtml(item.flow_text || "")}</pre>
    </section>
  `;
  detail.querySelector(".deleteButton")?.addEventListener("click", () => deleteMeeting(item.id));
}

function mediaUrl(path) {
  return `/media/${String(path || "").split("/").map(encodeURIComponent).join("/")}`;
}

function statusLabel(status) {
  if (status === "uploaded") return "업로드 완료";
  if (status === "done") return "요약 완료";
  if (status === "pending") return "요약 대기";
  if (status === "error") return "오류";
  if (status === "skipped") return "생성 안 함";
  return status || "-";
}

function meetingTimeLabel(item) {
  if (item.meeting_start_time && item.meeting_end_time && item.duration_label) {
    return `${item.meeting_start_time} ~ ${item.meeting_end_time} (${item.duration_label})`;
  }
  if (item.meeting_start_time && item.meeting_end_time) {
    return `${item.meeting_start_time} ~ ${item.meeting_end_time}`;
  }
  if (item.meeting_time && item.duration_label) {
    return `${item.meeting_time} (${item.duration_label})`;
  }
  return item.meeting_time || "";
}

async function deleteMeeting(id) {
  const ok = window.confirm("이 회의록과 관련 파일을 모두 삭제할까요?");
  if (!ok) return;

  const response = await fetch(`/api/meetings/${id}`, { method: "DELETE" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    window.alert(payload.error || "삭제에 실패했습니다.");
    return;
  }
  selectedId = null;
  selectedDate = null;
  await loadMeetings();
}

function markdownToHtml(markdown) {
  const lines = markdown.split(/\r?\n/);
  const html = [];
  let inList = false;
  let inTable = false;
  let currentSectionOpen = false;

  function closeList() {
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
  }

  function closeTable() {
    if (inTable) {
      html.push("</tbody></table></div>");
      inTable = false;
    }
  }

  function closeSection() {
    closeList();
    closeTable();
    if (currentSectionOpen) {
      html.push("</section>");
      currentSectionOpen = false;
    }
  }

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      closeList();
      continue;
    }
    if (trimmed.startsWith("# ")) {
      closeSection();
      html.push(`<h2 class="mdTitle">${escapeHtml(trimmed.slice(2))}</h2>`);
      continue;
    }
    if (trimmed.startsWith("## ")) {
      closeSection();
      const title = trimmed.slice(3);
      const classes = ["mdSection"];
      if (/핵심|결정|액션|다음|Flow/.test(title)) classes.push("highlightSection");
      if (/리스크|이슈/.test(title)) classes.push("riskSection");
      if (/액션/.test(title)) classes.push("taskSection");
      html.push(`<section class="${classes.join(" ")}"><h3>${escapeHtml(title)}</h3>`);
      currentSectionOpen = true;
      continue;
    }
    if (trimmed.startsWith("|")) {
      closeList();
      const cells = trimmed.split("|").slice(1, -1).map(cell => escapeHtml(cell.trim()));
      if (cells.every(cell => /^-+$/.test(cell.replace(/\s/g, "")))) continue;
      if (!inTable) {
        html.push('<div class="tableWrap"><table><tbody>');
        inTable = true;
      }
      const tag = html.join("").includes("<tr><th>") ? "td" : "th";
      html.push(`<tr>${cells.map(cell => `<${tag}>${cell}</${tag}>`).join("")}</tr>`);
      continue;
    }
    closeTable();
    if (trimmed.startsWith("- ")) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${escapeHtml(trimmed.slice(2))}</li>`);
      continue;
    }
    closeList();
    html.push(`<p>${escapeHtml(trimmed)}</p>`);
  }
  closeSection();
  return html.join("");
}

function render() {
  renderCalendar();
  renderList();
  renderDetail();
}

async function beginRecording() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    setRecordingState("오류", "이 브라우저는 웹 녹음을 지원하지 않습니다.");
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = chooseMimeType();
    mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recordingChunks = [];
    pendingChunkUploads = [];
    recordingChunkSequence = 0;
    recordingStartedAtIso = new Date().toISOString();
    recordingEndedAtIso = "";
    const session = await startRecordingSession(recordingStartedAtIso);
    recordingSessionId = session.recording_id;

    mediaRecorder.addEventListener("dataavailable", event => {
      if (!event.data || event.data.size <= 0) return;
      recordingChunks.push(event.data);
      pendingChunkUploads.push(uploadRecordingChunk(event.data, recordingChunkSequence));
      recordingChunkSequence += 1;
    });
    mediaRecorder.addEventListener("stop", () => {
      stream.getTracks().forEach(track => track.stop());
      finishRecording();
    });

    mediaRecorder.start(5000);
    recordingStartedAt = Date.now();
    recordingTimerId = window.setInterval(updateRecordingTimer, 500);
    updateRecordingTimer();
    startRecording.disabled = true;
    stopRecording.disabled = false;
    setRecordingState("● 녹음 중", "녹음 원본을 임시 저장소에 계속 보존하고 있습니다.");
  } catch (error) {
    setRecordingState("오류", `마이크 권한 또는 녹음 시작 실패: ${error.message}`);
  }
}

function endRecording() {
  if (!mediaRecorder || mediaRecorder.state === "inactive") return;
  recordingEndedAtIso = new Date().toISOString();
  stopRecording.disabled = true;
  setRecordingState("● 업로드 완료 준비", "마지막 녹음 조각을 저장하고 원본 audio를 확정합니다.");
  mediaRecorder.requestData();
  mediaRecorder.stop();
  if (recordingTimerId) {
    window.clearInterval(recordingTimerId);
    recordingTimerId = null;
  }
}

async function startRecordingSession(startedAt) {
  const response = await fetch("/api/recordings/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ started_at: startedAt })
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "녹음 세션 생성에 실패했습니다.");
  return payload;
}

async function uploadRecordingChunk(blob, sequence) {
  if (!recordingSessionId) return;
  const formData = new FormData();
  formData.append("recording_id", recordingSessionId);
  formData.append("sequence", String(sequence));
  formData.append("chunk", blob, `chunk-${sequence}.webm`);
  const response = await fetch("/api/recordings/chunk", {
    method: "POST",
    body: formData
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || "녹음 chunk 임시 저장에 실패했습니다.");
  }
}

async function finishRecording() {
  try {
    await Promise.all(pendingChunkUploads);
    setRecordingState("● 업로드 완료", "원본 audio 저장을 확정하고 DB uploaded row를 생성합니다.");
    const response = await fetch("/api/recordings/finish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        recording_id: recordingSessionId,
        started_at: recordingStartedAtIso,
        ended_at: recordingEndedAtIso || new Date().toISOString(),
        duration_seconds: Math.max(0, Math.round((Date.parse(recordingEndedAtIso) - Date.parse(recordingStartedAtIso)) / 1000))
      })
    });
    setRecordingState("● STT 처리 중", "음성을 텍스트로 변환하고 GPT 요약을 이어서 진행합니다.");
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || "녹음 처리에 실패했습니다.");
    }

    if (payload.skipped) {
      setRecordingState("● 오류 발생", payload.message || "회의 내용이 너무 짧아 회의록을 생성하지 않았습니다.");
      startRecording.disabled = false;
      stopRecording.disabled = true;
      scheduleRecordingReset();
      return;
    }

    setRecordingState("● DB 저장 완료", "회의록 저장이 완료되었습니다. 목록을 새로고침합니다.");
    startRecording.disabled = false;
    stopRecording.disabled = true;
    await loadMeetings();
    selectedId = payload.id;
    const saved = meetings.find(item => item.id === selectedId);
    selectedDate = saved?.date || selectedDate;
    render();
    scheduleRecordingReset();
  } catch (error) {
    setRecordingState("● 오류 발생", `${error.message} 원본 audio 또는 temp_audio를 확인해 복구할 수 있습니다.`);
    startRecording.disabled = false;
    stopRecording.disabled = true;
  }
}

function chooseMimeType() {
  const types = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus"
  ];
  return types.find(type => MediaRecorder.isTypeSupported(type)) || "";
}

function updateRecordingTimer() {
  const seconds = Math.floor((Date.now() - recordingStartedAt) / 1000);
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  recordingTimer.textContent = `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

function setRecordingState(label, message) {
  if (recordingResetTimerId) {
    window.clearTimeout(recordingResetTimerId);
    recordingResetTimerId = null;
  }
  recordingBadge.textContent = label;
  recordingStatus.textContent = message;
}

function resetRecordingState() {
  if (recordingResetTimerId) {
    window.clearTimeout(recordingResetTimerId);
    recordingResetTimerId = null;
  }
  if (recordingTimerId) {
    window.clearInterval(recordingTimerId);
    recordingTimerId = null;
  }
  recordingChunks = [];
  pendingChunkUploads = [];
  recordingSessionId = "";
  recordingChunkSequence = 0;
  recordingStartedAt = 0;
  recordingStartedAtIso = "";
  recordingEndedAtIso = "";
  recordingTimer.textContent = "00:00";
  startRecording.disabled = false;
  stopRecording.disabled = true;
  recordingBadge.textContent = "녹음 대기";
  recordingStatus.textContent = "브라우저 마이크로 회의를 녹음하고 바로 회의록을 생성합니다.";
}

function scheduleRecordingReset() {
  if (recordingResetTimerId) window.clearTimeout(recordingResetTimerId);
  recordingResetTimerId = window.setTimeout(resetRecordingState, 3000);
}

async function runRecovery(action) {
  recoveryActions.forEach(button => { button.disabled = true; });
  recoveryStatus.textContent = `${actionLabel(action)} 작업을 시작했습니다. 서버 로그에서 세부 단계를 확인할 수 있습니다.`;
  try {
    const response = await fetch("/api/recover-recordings", { method: "POST" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "복구 작업에 실패했습니다.");
    recoveryStatus.textContent = `복구 완료: 확인 ${payload.checked || 0}개, 저장 ${payload.saved || 0}개, STT 재시도 ${payload.stt_retried || 0}개, 실패 ${payload.failed || 0}개`;
    await loadMeetings();
  } catch (error) {
    recoveryStatus.textContent = `복구 실패: ${error.message}`;
  } finally {
    recoveryActions.forEach(button => { button.disabled = false; });
  }
}

function actionLabel(action) {
  if (action === "stt") return "다시 STT";
  if (action === "summary") return "다시 요약";
  return "DB 다시 저장";
}

search.addEventListener("input", render);
refresh.addEventListener("click", loadMeetings);
startRecording.addEventListener("click", beginRecording);
stopRecording.addEventListener("click", endRecording);
resetRecording.addEventListener("click", resetRecordingState);
recoveryActions.forEach(button => {
  button.addEventListener("click", () => runRecovery(button.dataset.action));
});
filters.forEach(button => {
  button.addEventListener("click", () => {
    filters.forEach(item => item.classList.remove("active"));
    button.classList.add("active");
    activeFilter = button.dataset.filter;
    render();
  });
});
document.querySelector("#prevMonth").addEventListener("click", () => {
  calendarMonth -= 1;
  if (calendarMonth < 0) {
    calendarMonth = 11;
    calendarYear -= 1;
  }
  selectedDate = null;
  selectedId = null;
  render();
});
document.querySelector("#nextMonth").addEventListener("click", () => {
  calendarMonth += 1;
  if (calendarMonth > 11) {
    calendarMonth = 0;
    calendarYear += 1;
  }
  selectedDate = null;
  selectedId = null;
  render();
});

loadMeetings().catch(error => {
  detail.innerHTML = `<div class="empty">API 연결 실패: ${escapeHtml(error.message)}</div>`;
});
