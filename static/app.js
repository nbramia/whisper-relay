const STORAGE_KEY = "whisper_relay_conversation_id";
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
let selectedMime = "";
let audioCtx = null;
let audioSource = null;
let audioProcessor = null;
let pcmChunks = [];
let micAcquireFailed = false;

// Microphone availability on iOS depends on the browser and OS version rather
// than being uniform, so capture support is feature-detected (below) instead of
// gated by browser. `isIOS` only tailors the fallback message when a mic call
// fails at runtime.
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

// "record": getUserMedia + MediaRecorder upload → full linux-whisper polish
// (desktop + any iOS browser that supports it). "speech": webkitSpeechRecognition
// fallback (transcript only, no polish). "blocked": neither API available.
function chooseCaptureMode() {
  if (canRecordAudio()) return "record";
  if (SpeechRecognitionCtor) return "speech";
  return "blocked";
}

const captureMode = chooseCaptureMode();

// iOS MediaRecorder frequently hands back empty/0-byte blobs even when
// getUserMedia succeeds, so on iOS we capture raw PCM via Web Audio and encode
// WAV ourselves instead of relying on MediaRecorder.
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

function showState(name) {
  for (const key of ["recording", "processing", "result"]) {
    els[key].classList.toggle("hidden", key !== name);
  }
  const showMic = name === "idle" || name === "recording";
  els.btnTalk.classList.toggle("hidden", !showMic);
  els.hint.classList.toggle("hidden", !showMic);
  updateTalkButtonUi();
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

function updateTalkButtonUi() {
  if (captureMode === "blocked") return;
  if (isRecording) {
    els.btnTalk.textContent = "Tap to send";
    els.btnTalk.setAttribute("aria-label", "Tap to send");
    els.hint.textContent = "Tap again when you're done speaking";
    return;
  }
  els.btnTalk.textContent = "Tap to talk";
  els.btnTalk.setAttribute("aria-label", "Tap to talk");
  els.hint.textContent =
    captureMode === "speech"
      ? "Tap to start · speech recognition"
      : "Tap to start recording";
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

function startTimer() {
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

async function submitTurn({ blob, mime, transcript }) {
  showState("processing");
  els.statusText.textContent = "";

  const form = new FormData();
  if (blob) {
    form.append("audio", blob, blobFilename(mime));
  }
  if (transcript) {
    form.append("transcript", transcript);
  }
  const convId = getConversationId();
  if (convId) form.append("conversation_id", convId);

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
    showState("idle");
  };

  recognition.onend = async () => {
    if (!sendAfterSpeechEnd) {
      if (isRecording) {
        isRecording = false;
        stopTimer();
        showState("idle");
      }
      return;
    }

    sendAfterSpeechEnd = false;
    isRecording = false;
    els.btnTalk.classList.remove("pressed");
    stopTimer();

    const text = speechParts.join(" ").trim();
    speechParts = [];
    if (!text) {
      showError("No speech heard — tap to talk and speak clearly.");
      showState("idle");
      return;
    }

    try {
      await submitTurn({ transcript: text });
    } catch (err) {
      showError(err.message || String(err));
      showState("idle");
    }
  };

  try {
    recognition.start();
    recordStartedAt = Date.now();
    isRecording = true;
    els.btnTalk.classList.add("pressed");
    showState("recording");
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
    showState("idle");
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

// iOS can transiently reject getUserMedia when re-acquiring the mic right after
// the previous stream was released (a race with audio-session teardown), not a
// real denial. Permission is already granted for the session, so a short delayed
// retry succeeds without another user gesture — this recovers invisibly instead
// of asking the user to tap again. Non-permission errors are not retried.
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
  els.btnTalk.classList.add("pressed");
  showState("recording");
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
  view.setUint32(16, 16, true); // PCM fmt chunk size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
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

// iOS requires the AudioContext to be created/resumed inside a user gesture, so
// the tap handler calls this synchronously before the async mic request.
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
  // ScriptProcessor only fires onaudioprocess while connected to a destination;
  // we never fill the output buffer, so playback stays silent (no echo).
  audioProcessor.connect(audioCtx.destination);
  recordStartedAt = Date.now();
  isRecording = true;
  els.btnTalk.classList.add("pressed");
  showState("recording");
  startTimer();
}

// Fully release the capture chain when a recording ends. On iOS a live mic
// track keeps the audio session in play-and-record mode, which degrades the
// <audio> playback of the TTS reply (scratchy/thin). Stopping the tracks and
// closing the context reverts iOS to a clean playback session; both are
// re-acquired in the next recording gesture (getUserMedia does not re-prompt
// within the same session).
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
  els.btnTalk.classList.remove("pressed");
  stopTimer();

  try {
    const { blob, mime } = await stopRecorder();
    await submitTurn({ blob, mime });
  } catch (err) {
    showError(err.message || String(err));
    showState("idle");
  }
}

function onTalkClick(event) {
  event.preventDefault();
  if (captureMode === "blocked") return;
  if (!els.processing.classList.contains("hidden")) return;
  if (isStarting) return;

  if (captureMode === "speech") {
    if (isRecording) {
      stopSpeechRecognition();
    } else {
      startSpeechRecognition();
    }
    return;
  }

  if (isRecording) {
    stopRecordingAndSend().catch((err) => showError(err.message || String(err)));
    return;
  }

  showError("");
  isStarting = true;
  if (useWebAudioRecorder) ensureAudioContext();
  requestMicInGesture()
    .then((stream) => {
      if (useWebAudioRecorder) beginWebAudioRecording(stream);
      else beginRecording(stream);
      micAcquireFailed = false;
    })
    .catch((err) => {
      // iOS can transiently reject the first getUserMedia after the mic was
      // released between turns; a second tap succeeds. Only surface the full
      // permission guidance if acquisition fails twice in a row.
      if (err?.name === "NotAllowedError" && !micAcquireFailed) {
        micAcquireFailed = true;
        showError("Microphone wasn't ready — tap to talk again.");
      } else {
        showError(formatMicError(err));
      }
    })
    .finally(() => {
      isStarting = false;
    });
}

els.btnTalk.addEventListener("click", onTalkClick, false);
els.btnTalk.addEventListener("contextmenu", (e) => e.preventDefault());

els.btnReplay.addEventListener("click", () => {
  if (lastPlayback.urls.length) playUrls(lastPlayback.urls).catch((e) => showError(e.message));
});

els.btnStop.addEventListener("click", stopAllAudio);

window.addEventListener("pagehide", () => {
  micStream?.getTracks().forEach((t) => t.stop());
  micStream = null;
  recognition?.abort();
  audioCtx?.close().catch(() => {});
  audioCtx = null;
});

showState("idle");

if (captureMode === "blocked") {
  showBlockedNotice();
} else if (!window.isSecureContext) {
  showError("Microphone requires HTTPS. Open the https:// Tailscale URL on your phone.");
}
