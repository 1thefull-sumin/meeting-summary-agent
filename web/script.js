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

let mediaRecorder = null;
let recordingChunks = [];
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
        <span><b>Markdown</b>${escapeHtml(item.summary_path || "-")}</span>
        <span><b>Flow 공유문</b>${escapeHtml(item.flow_path || "-")}</span>
      </div>
      <div class="detailActions">
        <button class="deleteButton" data-delete-id="${item.id}" type="button">삭제</button>
      </div>
    </div>
    <section class="section finalMarkdown">${markdownToHtml(item.markdown || "")}</section>
    <section class="section">
      <h3>Flow 공유 문구</h3>
      <pre class="flowBox">${escapeHtml(item.flow_text || "")}</pre>
    </section>
  `;
  detail.querySelector(".deleteButton")?.addEventListener("click", () => deleteMeeting(item.id));
}

function statusLabel(status) {
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
    recordingStartedAtIso = new Date().toISOString();
    recordingEndedAtIso = "";

    mediaRecorder.addEventListener("dataavailable", event => {
      if (event.data && event.data.size > 0) recordingChunks.push(event.data);
    });
    mediaRecorder.addEventListener("stop", () => {
      stream.getTracks().forEach(track => track.stop());
      uploadRecording(mimeType || mediaRecorder.mimeType || "audio/webm");
    });

    mediaRecorder.start();
    recordingStartedAt = Date.now();
    recordingTimerId = window.setInterval(updateRecordingTimer, 500);
    updateRecordingTimer();
    startRecording.disabled = true;
    stopRecording.disabled = false;
    setRecordingState("녹음 중", "회의를 녹음하고 있습니다.");
  } catch (error) {
    setRecordingState("오류", `마이크 권한 또는 녹음 시작 실패: ${error.message}`);
  }
}

function endRecording() {
  if (!mediaRecorder || mediaRecorder.state === "inactive") return;
  recordingEndedAtIso = new Date().toISOString();
  stopRecording.disabled = true;
  setRecordingState("업로드 준비", "녹음을 종료하고 음성 파일을 준비합니다.");
  mediaRecorder.stop();
  if (recordingTimerId) {
    window.clearInterval(recordingTimerId);
    recordingTimerId = null;
  }
}

async function uploadRecording(mimeType) {
  try {
    const extension = mimeType.includes("mp4") ? "mp4" : mimeType.includes("ogg") ? "ogg" : "webm";
    const blob = new Blob(recordingChunks, { type: mimeType });
    const formData = new FormData();
    formData.append("audio", blob, `browser-recording.${extension}`);
    formData.append("started_at", recordingStartedAtIso);
    formData.append("ended_at", recordingEndedAtIso || new Date().toISOString());
    formData.append("duration_seconds", String(Math.max(0, Math.round((Date.parse(recordingEndedAtIso) - Date.parse(recordingStartedAtIso)) / 1000))));

    setRecordingState("처리 중", "음성 업로드, 텍스트 변환, 회의록 요약을 진행하고 있습니다.");
    const response = await fetch("/api/recordings", {
      method: "POST",
      body: formData
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || "녹음 처리에 실패했습니다.");
    }

    if (payload.skipped) {
      setRecordingState("생성 안 함", payload.message || "회의 내용이 너무 짧아 회의록을 생성하지 않았습니다.");
      startRecording.disabled = false;
      stopRecording.disabled = true;
      scheduleRecordingReset();
      return;
    }

    setRecordingState("완료", "전사와 요약이 완료되었습니다. 목록을 새로고침합니다.");
    startRecording.disabled = false;
    stopRecording.disabled = true;
    await loadMeetings();
    selectedId = payload.id;
    const saved = meetings.find(item => item.id === selectedId);
    selectedDate = saved?.date || selectedDate;
    render();
    scheduleRecordingReset();
  } catch (error) {
    setRecordingState("오류", error.message);
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

search.addEventListener("input", render);
refresh.addEventListener("click", loadMeetings);
startRecording.addEventListener("click", beginRecording);
stopRecording.addEventListener("click", endRecording);
resetRecording.addEventListener("click", resetRecordingState);
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
