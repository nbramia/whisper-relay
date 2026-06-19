const STORAGE_KEY = "whisper_relay_conversation_id";
const AUTO_CONTINUE_KEY = "whisper_relay_auto_continue";
const MIN_RECORD_MS = 300;

const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4;codecs=mp4a.40.2",
  "audio/mp4",
  "audio/ogg;codecs=opus",
];

const SpeechRecognitionCtor =
  window.SpeechRecognition || window.webkitSpeechRecognition || null;

const els = {
  thread: document.getElementById("thread"),
  threadEmpty: document.getElementById("thread-empty"),
  btnTalk: document.getElementById("btn-talk"),
  btnStop: document.getElementById("btn-stop"),
  btnNewChat: document.getElementById("btn-new-chat"),
  btnChats: document.getElementById("btn-chats"),
  btnCloseSidebar: document.getElementById("btn-close-sidebar"),
  convSidebar: document.getElementById("conv-sidebar"),
  convOverlay: document.getElementById("conv-overlay"),
  convList: document.getElementById("conv-list"),
  autoContinue: document.getElementById("auto-continue"),
  statusBanner: document.getElementById("status-banner"),
  statusText: document.getElementById("status-text"),
  timer: document.getElementById("timer"),
  pulseRing: document.getElementById("pulse-ring"),
  error: document.getElementById("error"),
  hint: document.getElementById("hint"),
};

let mediaRecorder = null;
let micStream = null;
let recognition = null;
let speechParts = [];
let sendAfterSpeechEnd = false;
let chunks = [];
let recordStartedAt = 0;
let timerInterval = null;
let activeAudios = [];
let lastPlayback = { urls: [], texts: null };
let isRecording = false;
let isStarting = false;
let isPlaying = false;
let selectedMime = "";
let audioCtx = null;
let audioSource = null;
let audioProcessor = null;
let pcmChunks = [];
let micAcquireFailed = false;
let thinkingEl = null;
let cachedConversations = [];
let playbackChain = Promise.resolve();
let activeTurnId = null;
let activeTurnAbort = null;

function formatConversationDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function openConversationSidebar() {
  els.convSidebar.classList.remove("hidden");
  els.convOverlay.classList.remove("hidden");
  loadConversationList().catch(() => showError("Could not load conversations."));
}

function closeConversationSidebar() {
  els.convSidebar.classList.add("hidden");
  els.convOverlay.classList.add("hidden");
}

function renderConversationList(conversations) {
  const currentId = getConversationId();
  if (!conversations.length) {
    els.convList.innerHTML = '<li class="conv-empty">No conversations yet</li>';
    return;
  }
  els.convList.innerHTML = conversations
    .map(
      (conv) => `
      <li>
        <button type="button" class="conv-item ${conv.id === currentId ? "active" : ""}" data-id="${conv.id}">
          <div class="conv-item-title">${escapeHtml(conv.title || "New conversation")}</div>
          <div class="conv-item-date">${escapeHtml(formatConversationDate(conv.updated_at))}</div>
        </button>
      </li>`
    )
    .join("");
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function loadConversationList() {
  const res = await fetch("/api/voice/conversations");
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  cachedConversations = data.conversations || [];
  renderConversationList(cachedConversations);
}

function renderConversationMessages(messages) {
  for (const child of [...els.thread.children]) {
    if (child.id !== "thread-empty") child.remove();
  }
  thinkingEl = null;
  if (!messages?.length) {
    els.threadEmpty.classList.remove("hidden");
    return;
  }
  for (const msg of messages) {
    const role = msg.role === "user" ? "user" : "assistant";
    if (msg.content) appendMessage(msg.content, role);
  }
}

async function loadConversation(conversationId) {
  const res = await fetch(`/api/voice/conversations/${conversationId}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  setConversationId(data.id);
  renderConversationMessages(data.messages || []);
  closeConversationSidebar();
  renderConversationList(cachedConversations);
  showError("");
  setUiPhase("idle");
}

function classifyPlatform() {
  const ua = navigator.userAgent;
  const isIOS =
    /iPhone|iPod|iPad/i.test(ua) ||
    (/Macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
  return { isIOS };
}

const platform = classifyPlatform();

function canRecordAudio() {
  return (
    window.isSecureContext &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== "undefined" &&
    pickMimeType() !== ""
  );
}

function chooseCaptureMode() {
  if (canRecordAudio()) return "record";
  if (SpeechRecognitionCtor) return "speech";
  return "blocked";
}

const captureMode = chooseCaptureMode();
const useWebAudioRecorder = platform.isIOS;

function pickMimeType() {
  if (typeof MediaRecorder === "undefined") return "";
  for (const mime of MIME_CANDIDATES) {
    if (MediaRecorder.isTypeSupported(mime)) return mime;
  }
  return "";
}

function blobFilename(mime) {
  if (!mime) return "recording.webm";
  if (mime.includes("wav")) return "recording.wav";
  if (mime.includes("mp4") || mime.includes("aac")) return "recording.m4a";
  if (mime.includes("ogg")) return "recording.ogg";
  return "recording.webm";
}

function getAutoContinue() {
  return localStorage.getItem(AUTO_CONTINUE_KEY) === "1";
}

function setAutoContinue(enabled) {
  localStorage.setItem(AUTO_CONTINUE_KEY, enabled ? "1" : "0");
}

function setUiPhase(phase) {
  document.body.dataset.phase = phase;
  els.pulseRing.classList.toggle("hidden", phase !== "recording");
  els.btnTalk.disabled = phase === "processing" || phase === "playing";
  els.timer.classList.toggle("hidden", phase !== "recording");
  els.statusBanner.classList.toggle("hidden", phase !== "recording" && phase !== "processing");
  const showStop = phase === "processing" || phase === "playing";
  els.btnStop.classList.toggle("hidden", !showStop);
  updateTalkHint();
}

function updateTalkHint() {
  const phase = document.body.dataset.phase;
  if (phase === "recording") {
    els.hint.textContent = "Tap when you're done speaking";
    return;
  }
  if (phase === "processing") {
    els.hint.textContent = "Waiting for LifeOS…";
    return;
  }
  if (phase === "playing") {
    els.hint.textContent = getAutoContinue()
      ? "Playing reply — will listen again when done"
      : "Playing reply — tap to talk when done";
    return;
  }
  if (captureMode === "speech") {
    els.hint.textContent = "Tap to talk · speech recognition";
    return;
  }
  els.hint.textContent = "Tap to talk";
}

function showError(msg) {
  els.error.textContent = msg || "";
  els.error.classList.toggle("hidden", !msg);
}

function showBlockedNotice() {
  let msg = "Microphone access is unavailable in this browser.";
  if (platform.isIOS) msg += " Try Safari on iPhone.";
  showError(msg);
  els.btnTalk.disabled = true;
  els.hint.textContent = "";
}

function formatMicError(err) {
  const name = err?.name || "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    let msg = "Microphone permission denied. Allow mic access for this site, then reload.";
    if (platform.isIOS) {
      msg += " On iPhone: Settings → your browser → Microphone → Allow, or try Safari.";
    }
    return msg;
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") {
    return "No microphone was found on this device.";
  }
  return err?.message || String(err);
}

function getConversationId() {
  return sessionStorage.getItem(STORAGE_KEY) || "";
}

function setConversationId(id) {
  if (id) sessionStorage.setItem(STORAGE_KEY, id);
}

function clearConversation() {
  sessionStorage.removeItem(STORAGE_KEY);
  for (const child of [...els.thread.children]) {
    if (child.id !== "thread-empty") child.remove();
  }
  thinkingEl = null;
  els.threadEmpty.classList.remove("hidden");
  stopAllAudio();
  showError("");
  setUiPhase("idle");
  renderConversationList(cachedConversations);
}

function hideThreadEmpty() {
  if (els.threadEmpty) els.threadEmpty.classList.add("hidden");
}

function appendMessage(text, role, audioUrls = null) {
  hideThreadEmpty();
  const el = document.createElement("div");
  el.className = `msg msg-${role}`;
  el.textContent = text;
  if (role === "assistant" && audioUrls?.length) {
    el.classList.add("msg-replayable");
    el.dataset.audioUrls = JSON.stringify(audioUrls);
    el.setAttribute("role", "button");
    el.setAttribute("tabindex", "0");
    el.setAttribute("aria-label", "Tap to replay response");
  }
  els.thread.appendChild(el);
  els.thread.scrollTop = els.thread.scrollHeight;
  return el;
}

function parseAudioUrls(el) {
  try {
    return JSON.parse(el.dataset.audioUrls || "[]");
  } catch {
    return [];
  }
}

function setReplayingMessage(el) {
  for (const node of els.thread.querySelectorAll(".msg-replaying")) {
    node.classList.remove("msg-replaying");
  }
  if (el) el.classList.add("msg-replaying");
}

function showThinking() {
  hideThreadEmpty();
  if (thinkingEl) thinkingEl.remove();
  thinkingEl = document.createElement("div");
  thinkingEl.className = "msg msg-assistant msg-thinking";
  thinkingEl.textContent = "Thinking…";
  els.thread.appendChild(thinkingEl);
  els.thread.scrollTop = els.thread.scrollHeight;
}

function clearThinking() {
  if (thinkingEl) {
    thinkingEl.remove();
    thinkingEl = null;
  }
}

function stopAllAudio() {
  for (const a of activeAudios) {
    a.pause();
    a.currentTime = 0;
  }
  activeAudios = [];
  isPlaying = false;
}

async function playUrls(urls, { autoContinueAfter = false, replayEl = null } = {}) {
  stopAllAudio();
  if (!urls.length) return;
  isPlaying = true;
  setUiPhase("playing");
  setReplayingMessage(replayEl);
  try {
    for (const url of urls) {
      await new Promise((resolve, reject) => {
        const audio = new Audio(url);
        activeAudios.push(audio);
        audio.onended = () => resolve();
        audio.onerror = () => reject(new Error("playback failed"));
        audio.play().catch(reject);
      });
    }
  } finally {
    isPlaying = false;
    setReplayingMessage(null);
  }
  if (autoContinueAfter) {
    await maybeAutoContinue();
  } else {
    setUiPhase("idle");
  }
}

async function replayMessage(el) {
  if (document.body.dataset.phase === "processing") return;
  const urls = parseAudioUrls(el);
  if (!urls.length) return;
  showError("");
  try {
    await playUrls(urls, { autoContinueAfter: false, replayEl: el });
  } catch (err) {
    showError(err.message || String(err));
    setUiPhase("idle");
  }
}

function startTimer() {
  els.timer.textContent = "0:00";
  timerInterval = setInterval(() => {
    const s = Math.floor((Date.now() - recordStartedAt) / 1000);
    const m = Math.floor(s / 60);
    const r = s % 60;
    els.timer.textContent = `${m}:${String(r).padStart(2, "0")}`;
  }, 200);
}

function stopTimer() {
  if (timerInterval) clearInterval(timerInterval);
  timerInterval = null;
}

async function maybeAutoContinue() {
  if (!getAutoContinue()) {
    setUiPhase("idle");
    return;
  }

  els.hint.textContent = "Starting next turn…";
  try {
    await beginRecordingFromAuto();
  } catch (err) {
    setUiPhase("idle");
    if (err?.name === "NotAllowedError") {
      showError("Tap the button to continue — Auto needs a tap on this device.");
    } else {
      showError(err?.message || String(err));
    }
  }
}

async function playSingleUrl(url) {
  return new Promise((resolve, reject) => {
    const audio = new Audio(url);
    activeAudios.push(audio);
    audio.onended = () => resolve();
    audio.onerror = () => reject(new Error("playback failed"));
    audio.play().catch(reject);
  });
}

function enqueueClip(url) {
  playbackChain = playbackChain
    .then(() => playSingleUrl(url))
    .catch((err) => {
      showError(err.message || String(err));
    });
  return playbackChain;
}

function parseSseChunk(buffer, onEvent) {
  const lines = buffer.split("\n");
  const remainder = lines.pop() || "";
  for (const line of lines) {
    if (!line.startsWith("data: ")) continue;
    try {
      onEvent(JSON.parse(line.slice(6)));
    } catch {
      /* ignore malformed chunks */
    }
  }
  return remainder;
}

async function consumeTurnStream(response) {
  playbackChain = Promise.resolve();
  let doneData = null;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handleEvent = (event) => {
    if (event.type === "started") {
      activeTurnId = event.turn_id;
    }
    if (event.type === "cancelled") {
      throw new DOMException("Turn cancelled", "AbortError");
    }
    if (event.type === "error") {
      throw new Error(event.message || "Turn failed");
    }
    if (event.type === "status_audio") {
      if (event.message) els.statusText.textContent = event.message;
      if (!isPlaying) {
        isPlaying = true;
        setUiPhase("playing");
      }
      enqueueClip(event.url);
    }
    if (event.type === "main_audio") {
      if (!isPlaying) {
        isPlaying = true;
        setUiPhase("playing");
      }
      enqueueClip(event.url);
    }
    if (event.type === "done") {
      doneData = event.data;
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = parseSseChunk(buffer, handleEvent);
  }
  buffer += decoder.decode();
  parseSseChunk(`${buffer}\n`, handleEvent);
  return doneData;
}

async function submitTurn({ blob, mime, transcript }) {
  setUiPhase("processing");
  els.statusText.textContent = "Thinking…";
  showThinking();
  activeTurnId = null;
  activeTurnAbort = new AbortController();

  const form = new FormData();
  if (blob) form.append("audio", blob, blobFilename(mime));
  if (transcript) form.append("transcript", transcript);
  const convId = getConversationId();
  if (convId) form.append("conversation_id", convId);

  try {
    const res = await fetch("/api/voice/turn/stream", {
      method: "POST",
      body: form,
      signal: activeTurnAbort.signal,
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      clearThinking();
      throw new Error(data.detail || `Request failed (${res.status})`);
    }

    const data = await consumeTurnStream(res);
    if (!data) {
      clearThinking();
      throw new Error("Turn ended without a response");
    }

    if (data.conversation_id) setConversationId(data.conversation_id);

    clearThinking();
    if (data.transcript) appendMessage(data.transcript, "user");
    const playbackUrls = [...(data.status_audio_urls || []), data.audio_url].filter(Boolean);
    lastPlayback = { urls: playbackUrls, texts: data };
    if (data.response_text) appendMessage(data.response_text, "assistant", playbackUrls);

    await playbackChain;
    isPlaying = false;
    await maybeAutoContinue();
  } catch (err) {
    if (err?.name === "AbortError") {
      return;
    }
    clearThinking();
    throw err;
  } finally {
    activeTurnId = null;
    activeTurnAbort = null;
  }
}

function cancelActiveTurn() {
  activeTurnAbort?.abort();
  if (activeTurnId) {
    fetch(`/api/voice/turn/${activeTurnId}/cancel`, { method: "POST" }).catch(() => {});
  }
  playbackChain = Promise.resolve();
  stopAllAudio();
  clearThinking();
  isPlaying = false;
  activeTurnId = null;
  activeTurnAbort = null;
  setUiPhase("idle");
}

function formatSpeechError(event) {
  if (event.error === "not-allowed") {
    return (
      "Microphone blocked for speech recognition. " +
      "Settings → Safari → Microphone → Allow, then reload."
    );
  }
  if (event.error === "no-speech") {
    return "No speech heard — tap to talk and speak clearly.";
  }
  return `Speech recognition failed: ${event.error}`;
}

function startSpeechRecognition() {
  if (!SpeechRecognitionCtor) {
    showError("Speech recognition is not available in this browser.");
    return;
  }

  showError("");
  speechParts = [];
  sendAfterSpeechEnd = false;
  recognition = new SpeechRecognitionCtor();
  recognition.continuous = true;
  recognition.interimResults = false;
  recognition.lang = "en-GB";

  recognition.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      if (event.results[i].isFinal) {
        speechParts.push(event.results[i][0].transcript);
      }
    }
  };

  recognition.onerror = (event) => {
    if (event.error === "aborted") return;
    showError(formatSpeechError(event));
    isRecording = false;
    sendAfterSpeechEnd = false;
    stopTimer();
    setUiPhase("idle");
  };

  recognition.onend = async () => {
    if (!sendAfterSpeechEnd) {
      if (isRecording) {
        isRecording = false;
        stopTimer();
        setUiPhase("idle");
      }
      return;
    }

    sendAfterSpeechEnd = false;
    isRecording = false;
    stopTimer();

    const text = speechParts.join(" ").trim();
    speechParts = [];
    if (!text) {
      showError("No speech heard — tap to talk and speak clearly.");
      setUiPhase("idle");
      return;
    }

    try {
      await submitTurn({ transcript: text });
    } catch (err) {
      showError(err.message || String(err));
      setUiPhase("idle");
    }
  };

  try {
    recognition.start();
    recordStartedAt = Date.now();
    isRecording = true;
    els.statusText.textContent = "Recording…";
    setUiPhase("recording");
    startTimer();
  } catch (err) {
    showError(err.message || String(err));
  }
}

function stopSpeechRecognition() {
  if (!recognition || !isRecording) return;
  sendAfterSpeechEnd = true;
  try {
    recognition.stop();
  } catch (err) {
    sendAfterSpeechEnd = false;
    showError(err.message || String(err));
    isRecording = false;
    stopTimer();
    setUiPhase("idle");
  }
}

function setupMediaRecorder(stream) {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    try {
      mediaRecorder.stop();
    } catch (_) {
      /* ignore */
    }
  }

  selectedMime = pickMimeType();
  try {
    mediaRecorder = selectedMime
      ? new MediaRecorder(stream, { mimeType: selectedMime })
      : new MediaRecorder(stream);
  } catch (_) {
    mediaRecorder = new MediaRecorder(stream);
    selectedMime = "";
  }

  mediaRecorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };
}

async function acquireMicStream() {
  const backoffMs = [0, 200, 400, 800];
  let lastErr;
  for (const delay of backoffMs) {
    if (delay) await new Promise((r) => setTimeout(r, delay));
    try {
      return await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      lastErr = err;
      if (err?.name !== "NotAllowedError") throw err;
    }
  }
  throw lastErr;
}

function requestMicInGesture() {
  if (!window.isSecureContext) {
    return Promise.reject(new Error("Microphone requires HTTPS."));
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return Promise.reject(new Error("Microphone not available."));
  }
  if (micStream?.getAudioTracks().some((t) => t.readyState === "live")) {
    return Promise.resolve(micStream);
  }
  return acquireMicStream().then((stream) => {
    micStream = stream;
    return stream;
  });
}

async function beginRecording(stream) {
  chunks = [];
  if (typeof MediaRecorder === "undefined") {
    throw new Error("Recording is not supported in this browser.");
  }
  setupMediaRecorder(stream);
  mediaRecorder.start(250);
  recordStartedAt = Date.now();
  isRecording = true;
  els.statusText.textContent = "Recording…";
  setUiPhase("recording");
  startTimer();
}

function stopMediaRecorder() {
  return new Promise((resolve, reject) => {
    if (!mediaRecorder || mediaRecorder.state === "inactive") {
      reject(new Error("Recorder not active"));
      return;
    }

    const mime = mediaRecorder.mimeType || selectedMime || "audio/webm";
    mediaRecorder.onstop = () => {
      const blob = new Blob(chunks, { type: mime });
      chunks = [];
      if (blob.size === 0) {
        reject(new Error("No audio captured — speak longer, then tap to send."));
        return;
      }
      resolve({ blob, mime });
    };

    if (mediaRecorder.state === "recording") {
      if (typeof mediaRecorder.requestData === "function") {
        mediaRecorder.requestData();
      }
      mediaRecorder.stop();
    }
  });
}

function encodeWav(samples, sampleRate) {
  const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const writeStr = (off, s) => {
    for (let i = 0; i < s.length; i += 1) view.setUint8(off + i, s.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let off = 44;
  for (let i = 0; i < samples.length; i += 1) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    off += 2;
  }
  return new Blob([view], { type: "audio/wav" });
}

function ensureAudioContext() {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return;
  if (!audioCtx || audioCtx.state === "closed") audioCtx = new Ctx();
  if (audioCtx.state === "suspended") audioCtx.resume();
}

function beginWebAudioRecording(stream) {
  ensureAudioContext();
  if (!audioCtx) throw new Error("Recording is not supported in this browser.");
  pcmChunks = [];
  audioSource = audioCtx.createMediaStreamSource(stream);
  audioProcessor = audioCtx.createScriptProcessor(4096, 1, 1);
  audioProcessor.onaudioprocess = (e) => {
    pcmChunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  };
  audioSource.connect(audioProcessor);
  audioProcessor.connect(audioCtx.destination);
  recordStartedAt = Date.now();
  isRecording = true;
  els.statusText.textContent = "Recording…";
  setUiPhase("recording");
  startTimer();
}

function releaseCapture() {
  try {
    if (audioProcessor) {
      audioProcessor.onaudioprocess = null;
      audioProcessor.disconnect();
    }
    if (audioSource) audioSource.disconnect();
  } catch (_) {
    /* ignore */
  }
  audioProcessor = null;
  audioSource = null;
  if (audioCtx) {
    audioCtx.close().catch(() => {});
    audioCtx = null;
  }
  if (micStream) {
    micStream.getTracks().forEach((t) => t.stop());
    micStream = null;
  }
}

function stopWebAudioRecording() {
  return new Promise((resolve, reject) => {
    const sampleRate = audioCtx ? audioCtx.sampleRate : 44100;

    let total = 0;
    for (const c of pcmChunks) total += c.length;
    const flat = new Float32Array(total);
    let off = 0;
    for (const c of pcmChunks) {
      flat.set(c, off);
      off += c.length;
    }
    pcmChunks = [];
    releaseCapture();

    if (flat.length === 0) {
      reject(new Error("No audio captured — speak longer, then tap to send."));
      return;
    }
    resolve({ blob: encodeWav(flat, sampleRate), mime: "audio/wav" });
  });
}

function stopRecorder() {
  return useWebAudioRecorder ? stopWebAudioRecording() : stopMediaRecorder();
}

async function stopRecordingAndSend() {
  if (isStarting || !isRecording) return;

  const elapsed = Date.now() - recordStartedAt;
  if (elapsed < MIN_RECORD_MS) {
    await new Promise((r) => setTimeout(r, MIN_RECORD_MS - elapsed));
  }

  isRecording = false;
  stopTimer();

  try {
    const { blob, mime } = await stopRecorder();
    await submitTurn({ blob, mime });
  } catch (err) {
    showError(err.message || String(err));
    setUiPhase("idle");
  }
}

async function beginRecordingFromAuto() {
  if (captureMode === "speech") {
    startSpeechRecognition();
    return;
  }

  if (useWebAudioRecorder) ensureAudioContext();
  const stream = await requestMicInGesture();
  if (useWebAudioRecorder) beginWebAudioRecording(stream);
  else beginRecording(stream);
  micAcquireFailed = false;
}

async function beginRecordingFromTap() {
  showError("");
  isStarting = true;
  try {
    await beginRecordingFromAuto();
  } catch (err) {
    if (err?.name === "NotAllowedError" && !micAcquireFailed) {
      micAcquireFailed = true;
      showError("Microphone wasn't ready — tap to talk again.");
    } else {
      showError(formatMicError(err));
    }
  } finally {
    isStarting = false;
  }
}

function onTalkClick(event) {
  event.preventDefault();
  if (captureMode === "blocked") return;
  if (document.body.dataset.phase === "processing") return;
  if (isStarting) return;

  if (isPlaying) {
    stopAllAudio();
    setUiPhase("idle");
    return;
  }

  if (captureMode === "speech") {
    if (isRecording) stopSpeechRecognition();
    else startSpeechRecognition();
    return;
  }

  if (isRecording) {
    stopRecordingAndSend().catch((err) => showError(err.message || String(err)));
    return;
  }

  beginRecordingFromTap();
}

els.btnTalk.addEventListener("click", onTalkClick, false);
els.btnTalk.addEventListener("contextmenu", (e) => e.preventDefault());

els.btnStop.addEventListener("click", () => {
  if (document.body.dataset.phase === "processing" || document.body.dataset.phase === "playing") {
    cancelActiveTurn();
    return;
  }
  stopAllAudio();
  setUiPhase("idle");
});

els.thread.addEventListener("click", (event) => {
  const msg = event.target.closest(".msg-assistant.msg-replayable");
  if (msg) replayMessage(msg);
});

els.thread.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const msg = event.target.closest(".msg-assistant.msg-replayable");
  if (!msg) return;
  event.preventDefault();
  replayMessage(msg);
});

els.btnNewChat.addEventListener("click", () => {
  if (document.body.dataset.phase === "processing") return;
  clearConversation();
  closeConversationSidebar();
});

els.btnChats.addEventListener("click", () => openConversationSidebar());
els.btnCloseSidebar.addEventListener("click", () => closeConversationSidebar());
els.convOverlay.addEventListener("click", () => closeConversationSidebar());

els.convList.addEventListener("click", (event) => {
  const btn = event.target.closest(".conv-item");
  if (!btn) return;
  const id = btn.dataset.id;
  if (!id) return;
  loadConversation(id).catch((err) => showError(err.message || String(err)));
});

els.autoContinue.checked = getAutoContinue();
els.autoContinue.addEventListener("change", () => {
  setAutoContinue(els.autoContinue.checked);
  updateTalkHint();
});

window.addEventListener("pagehide", () => {
  micStream?.getTracks().forEach((t) => t.stop());
  micStream = null;
  recognition?.abort();
  audioCtx?.close().catch(() => {});
  audioCtx = null;
});

setUiPhase("idle");

if (captureMode === "blocked") {
  showBlockedNotice();
} else if (!window.isSecureContext) {
  showError("Microphone requires HTTPS. Open the https:// Tailscale URL on your phone.");
}
