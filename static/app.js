const STORAGE_KEY = "whisper_relay_conversation_id";

const els = {
  idle: document.getElementById("state-idle"),
  recording: document.getElementById("state-recording"),
  processing: document.getElementById("state-processing"),
  result: document.getElementById("state-result"),
  btnTalk: document.getElementById("btn-talk"),
  btnReplay: document.getElementById("btn-replay"),
  btnStop: document.getElementById("btn-stop"),
  transcript: document.getElementById("transcript"),
  response: document.getElementById("response"),
  statusText: document.getElementById("status-text"),
  timer: document.getElementById("timer"),
  error: document.getElementById("error"),
};

let mediaRecorder = null;
let chunks = [];
let recordStart = 0;
let timerInterval = null;
let activeAudios = [];
let lastPlayback = { urls: [], texts: null };

function showState(name) {
  for (const key of ["idle", "recording", "processing", "result"]) {
    els[key].classList.toggle("hidden", key !== name);
  }
}

function showError(msg) {
  els.error.textContent = msg || "";
  els.error.classList.toggle("hidden", !msg);
}

function getConversationId() {
  return sessionStorage.getItem(STORAGE_KEY) || "";
}

function setConversationId(id) {
  if (id) sessionStorage.setItem(STORAGE_KEY, id);
}

function stopAllAudio() {
  for (const a of activeAudios) {
    a.pause();
    a.currentTime = 0;
  }
  activeAudios = [];
}

async function playUrls(urls) {
  stopAllAudio();
  for (const url of urls) {
    await new Promise((resolve, reject) => {
      const audio = new Audio(url);
      activeAudios.push(audio);
      audio.onended = () => resolve();
      audio.onerror = () => reject(new Error("playback failed"));
      audio.play().catch(reject);
    });
  }
}

async function ensureMic() {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("Microphone not available in this browser");
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
    ? "audio/webm;codecs=opus"
    : "audio/webm";
  mediaRecorder = new MediaRecorder(stream, { mimeType: mime });
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) chunks.push(e.data);
  };
  return mime;
}

function startTimer() {
  recordStart = Date.now();
  timerInterval = setInterval(() => {
    const s = Math.floor((Date.now() - recordStart) / 1000);
    const m = Math.floor(s / 60);
    const r = s % 60;
    els.timer.textContent = `${m}:${String(r).padStart(2, "0")}`;
  }, 200);
}

function stopTimer() {
  if (timerInterval) clearInterval(timerInterval);
  timerInterval = null;
}

async function startRecording() {
  showError("");
  chunks = [];
  const mime = await ensureMic();
  mediaRecorder.start();
  showState("recording");
  startTimer();
  els.btnTalk.classList.add("pressed");
}

async function stopRecordingAndSend() {
  if (!mediaRecorder || mediaRecorder.state === "inactive") return;
  els.btnTalk.classList.remove("pressed");
  stopTimer();

  const blob = await new Promise((resolve) => {
    mediaRecorder.onstop = () => {
      resolve(new Blob(chunks, { type: mediaRecorder.mimeType }));
    };
    mediaRecorder.stop();
    mediaRecorder.stream.getTracks().forEach((t) => t.stop());
  });

  showState("processing");
  els.statusText.textContent = "";

  const form = new FormData();
  form.append("audio", blob, "recording.webm");
  const convId = getConversationId();
  if (convId) form.append("conversation_id", convId);

  try {
    const res = await fetch("/api/voice/turn", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || `Request failed (${res.status})`);
    }

    if (data.conversation_id) setConversationId(data.conversation_id);

    els.transcript.textContent = data.transcript || "";
    els.response.textContent = data.response_text || "";
    showState("result");

    const urls = [...(data.status_audio_urls || []), data.audio_url].filter(Boolean);
    lastPlayback = { urls, texts: data };
    await playUrls(urls);
  } catch (err) {
    showError(err.message || String(err));
    showState("idle");
  }
}

els.btnTalk.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  if (els.processing.classList.contains("hidden") === false) return;
  startRecording().catch((err) => showError(err.message));
});

els.btnTalk.addEventListener("pointerup", stopRecordingAndSend);
els.btnTalk.addEventListener("pointerleave", (e) => {
  if (els.btnTalk.classList.contains("pressed")) stopRecordingAndSend();
});
els.btnTalk.addEventListener("pointercancel", stopRecordingAndSend);
els.btnTalk.addEventListener("contextmenu", (e) => e.preventDefault());

els.btnReplay.addEventListener("click", () => {
  if (lastPlayback.urls.length) playUrls(lastPlayback.urls).catch((e) => showError(e.message));
});

els.btnStop.addEventListener("click", stopAllAudio);

showState("idle");
