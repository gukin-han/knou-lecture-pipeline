'use strict';

// ── Constants ───────────────────────────────────────────────────────────────

const AUDIO_EXTENSIONS = new Set(['.mp3', '.wav', '.m4a', '.flac', '.ogg', '.opus']);

const STAGE_LABELS = {
  queued:       '대기 중',
  transcribing: '음성 변환 중',
  cleaning:     '텍스트 정제 중',
  structuring:  '구조화 중',
  done:         '완료',
  failed:       '오류',
};

// ── DOM ─────────────────────────────────────────────────────────────────────

const dropZone  = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const jobList   = document.getElementById('jobList');

// ── Drag-and-Drop ────────────────────────────────────────────────────────────

dropZone.addEventListener('dragenter', (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragover',  (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', (e) => {
  if (!dropZone.contains(e.relatedTarget)) dropZone.classList.remove('drag-over');
});
dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const files = [...e.dataTransfer.files].filter(f => isAudio(f.name));
  if (files.length === 0) return showFormatWarning();
  files.forEach(uploadFile);
});

// Click / keyboard activation
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') fileInput.click(); });
fileInput.addEventListener('change', (e) => {
  [...e.target.files].forEach(uploadFile);
  fileInput.value = '';
});

// ── Helpers ──────────────────────────────────────────────────────────────────

function isAudio(name) {
  const ext = name.slice(name.lastIndexOf('.')).toLowerCase();
  return AUDIO_EXTENSIONS.has(ext);
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function showFormatWarning() {
  alert('지원 형식: MP3, WAV, M4A, FLAC, OGG');
}

// ── Upload & Job Management ──────────────────────────────────────────────────

async function uploadFile(file) {
  const cardEl = createJobCard(file.name, file.size);
  jobList.prepend(cardEl);

  const formData = new FormData();
  formData.append('file', file);

  let jobId;
  try {
    const res = await fetch('/upload', { method: 'POST', body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    jobId = data.job_id;
    cardEl.dataset.jobId = jobId;
  } catch (err) {
    setCardStatus(cardEl, 'failed', '업로드 실패', 0, '', err.message);
    return;
  }

  // Open SSE stream for live progress
  listenToProgress(jobId, cardEl);
}

// ── SSE Progress ─────────────────────────────────────────────────────────────

function listenToProgress(jobId, cardEl) {
  const sse = new EventSource(`/status/${jobId}`);

  sse.onmessage = (e) => {
    let event;
    try { event = JSON.parse(e.data); } catch { return; }

    setCardStatus(
      cardEl,
      event.status,
      event.message,
      event.percent,
      event.output_path || '',
      event.error || '',
    );

    if (event.status === 'done' || event.status === 'failed') {
      sse.close();
    }
  };

  sse.onerror = () => {
    // SSE disconnected — don't overwrite a terminal state
    const current = cardEl.dataset.status;
    if (current !== 'done' && current !== 'failed') {
      setCardStatus(cardEl, current || 'queued', '연결이 끊겼습니다. 페이지를 새로고침하세요.', 0);
    }
    sse.close();
  };
}

// ── Card Rendering ────────────────────────────────────────────────────────────

function createJobCard(filename, fileSize) {
  const card = document.createElement('div');
  card.className = 'job-card';
  card.dataset.status = 'queued';

  card.innerHTML = `
    <div class="job-header">
      <span class="job-filename">${escHtml(filename)}</span>
      <div style="display:flex;align-items:center;gap:.6rem;flex-shrink:0">
        <span class="job-size">${formatBytes(fileSize)}</span>
        <span class="badge badge-queued">
          <span class="dot"></span>
          <span class="badge-text">${STAGE_LABELS.queued}</span>
        </span>
      </div>
    </div>
    <div class="progress-wrap">
      <div class="progress-bar"><div class="progress-fill"></div></div>
      <div class="job-message">업로드 완료, 처리 대기 중...</div>
    </div>
  `;
  return card;
}

function setCardStatus(card, status, message, percent, outputPath = '', error = '') {
  card.dataset.status = status;

  // Badge
  const badge = card.querySelector('.badge');
  badge.className = `badge badge-${status}`;
  badge.querySelector('.badge-text').textContent = STAGE_LABELS[status] ?? status;

  // Progress bar
  const fill = card.querySelector('.progress-fill');
  fill.style.width = `${Math.min(percent, 100)}%`;

  // Message
  const msgEl = card.querySelector('.job-message');
  msgEl.textContent = message;

  // Error detail
  let errEl = card.querySelector('.job-error');
  if (error) {
    if (!errEl) {
      errEl = document.createElement('div');
      errEl.className = 'job-error';
      card.querySelector('.progress-wrap').after(errEl);
    }
    errEl.textContent = error;
  } else if (errEl) {
    errEl.remove();
  }

  // Download button
  let dlBtn = card.querySelector('.btn-download');
  if (status === 'done') {
    if (!dlBtn) {
      dlBtn = document.createElement('a');
      dlBtn.className = 'btn-download';
      dlBtn.innerHTML = '⬇ 다운로드';
      const jobId = card.dataset.jobId;
      dlBtn.href = `/download/${jobId}`;
      dlBtn.download = '';
      card.querySelector('.progress-wrap').after(dlBtn);
    }
  } else if (dlBtn) {
    dlBtn.remove();
  }
}

// ── Security ──────────────────────────────────────────────────────────────────

function escHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
