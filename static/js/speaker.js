/* Konuşmacı sayfası: mikrofonu yakalar, 16 kHz PCM parçalarını sunucuya gönderir. */
document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("konusmaci");
  const code = root.dataset.roomCode;
  const workletUrl = root.dataset.workletUrl;
  const chunkMs = Number(root.dataset.chunkMs || 320);

  const btnStart = document.getElementById("btn-baslat");
  const btnStop = document.getElementById("btn-durdur");
  const meter = document.getElementById("ses-seviyesi");
  const statusEl = document.getElementById("baglanti-durumu");
  const sessionStatusEl = document.getElementById("oturum-durumu");
  const errorEl = document.getElementById("hata");
  const micSelect = document.getElementById("mikrofon");
  const infoEl = document.getElementById("bilgi");

  const view = new Altyazi.CaptionView(document.getElementById("altyazi"));
  const SESSION_TEXT = { waiting: "Bekliyor", live: "Canlı yayında", ended: "Durduruldu" };

  let audio = null; // { ctx, stream, node, source }
  let sentChunks = 0;

  function showError(msg) {
    errorEl.textContent = msg || "";
    errorEl.hidden = !msg;
  }

  function setSessionStatus(s) {
    sessionStatusEl.textContent = SESSION_TEXT[s] || s;
    sessionStatusEl.dataset.status = s;
  }

  function setRecordingUi(recording) {
    btnStart.disabled = recording;
    btnStop.disabled = !recording;
    root.classList.toggle("kayitta", recording);
    if (!recording) meter.value = 0;
  }

  const socket = new Altyazi.LiveSocket("/ws/konusmaci/" + code + "/", {
    onStatus: (s, closeCode) => {
      const text = {
        baglaniyor: "Sunucuya bağlanıyor…",
        bagli: "Sunucuya bağlı",
        koptu: "Bağlantı koptu, yeniden deneniyor…",
        reddedildi: "Bu oturum için yetkiniz yok",
      };
      statusEl.textContent = text[s] || s;
      statusEl.dataset.status = s;
      // Bağlantı yeniden kurulduğunda mikrofon hâlâ açıksa yayını sürdür
      if (s === "bagli" && audio) socket.sendJson({ action: "start" });
    },
    onMessage: (msg) => {
      switch (msg.type) {
        case "history":
          view.clear();
          setSessionStatus(msg.status);
          (msg.segments || []).forEach((seg) => view.addFinal(seg));
          break;
        case "partial":
          view.setPartial(msg.text);
          break;
        case "final":
          view.addFinal(msg.segment);
          break;
        case "status":
          setSessionStatus(msg.status);
          break;
        case "info":
          infoEl.textContent = msg.message;
          break;
        case "error":
          showError(msg.message);
          break;
      }
    },
  });

  async function listMicrophones() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
    const devices = await navigator.mediaDevices.enumerateDevices();
    const mics = devices.filter((d) => d.kind === "audioinput");
    const current = micSelect.value;
    micSelect.textContent = "";
    mics.forEach((d, i) => {
      const opt = document.createElement("option");
      opt.value = d.deviceId;
      opt.textContent = d.label || "Mikrofon " + (i + 1);
      micSelect.appendChild(opt);
    });
    if (current) micSelect.value = current;
  }

  async function start() {
    showError("");
    if (!window.isSecureContext || !navigator.mediaDevices) {
      showError("Mikrofon yalnızca HTTPS veya localhost üzerinden kullanılabilir.");
      return;
    }
    if (!socket.open) {
      showError("Sunucu bağlantısı yok. Lütfen birkaç saniye sonra tekrar deneyin.");
      return;
    }
    try {
      const constraints = {
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      };
      if (micSelect.value) constraints.audio.deviceId = { exact: micSelect.value };
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      const ctx = new AudioContext({ latencyHint: "interactive" });
      await ctx.audioWorklet.addModule(workletUrl);
      const source = ctx.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(ctx, "pcm-downsampler", {
        numberOfInputs: 1,
        numberOfOutputs: 0,
        channelCount: 1,
        channelCountMode: "explicit",
        processorOptions: { targetRate: 16000, chunkMs },
      });
      node.port.onmessage = (e) => {
        meter.value = Math.min(1, e.data.level * 4);
        socket.send(e.data.pcm);
        sentChunks++;
      };
      source.connect(node);
      audio = { ctx, stream, node, source };
      socket.sendJson({ action: "start" });
      setRecordingUi(true);
      listMicrophones();
    } catch (err) {
      console.error(err);
      stopAudio();
      if (err.name === "NotAllowedError") showError("Mikrofon izni verilmedi. Tarayıcı ayarlarından izin verin.");
      else if (err.name === "NotFoundError") showError("Mikrofon bulunamadı.");
      else showError("Ses başlatılamadı: " + err.message);
    }
  }

  function stopAudio() {
    if (!audio) return;
    try {
      audio.node.port.postMessage("stop");
      audio.source.disconnect();
      audio.stream.getTracks().forEach((t) => t.stop());
      audio.ctx.close();
    } catch (e) {
      /* zaten kapalı */
    }
    audio = null;
    setRecordingUi(false);
  }

  function stop() {
    stopAudio();
    socket.sendJson({ action: "stop" });
  }

  btnStart.addEventListener("click", start);
  btnStop.addEventListener("click", stop);
  window.addEventListener("beforeunload", (e) => {
    if (audio) {
      e.preventDefault();
      e.returnValue = "";
    }
  });

  document.getElementById("btn-kopyala")?.addEventListener("click", async (e) => {
    try {
      await navigator.clipboard.writeText(e.currentTarget.dataset.copy);
      e.currentTarget.textContent = "Kopyalandı ✓";
    } catch (err) {
      /* pano erişimi yok */
    }
  });

  listMicrophones();
  setRecordingUi(false);
});
