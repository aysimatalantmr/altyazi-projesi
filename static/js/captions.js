/* Ortak altyazı ve terim kartı görünümü + yeniden bağlanan WebSocket. */
(function () {
  function wsUrl(path) {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + location.host + path;
  }

  /** Kopunca artan bekleme ile yeniden bağlanan WebSocket. */
  class LiveSocket {
    constructor(path, { onMessage, onStatus, binaryType } = {}) {
      this.url = wsUrl(path);
      this.onMessage = onMessage || (() => {});
      this.onStatus = onStatus || (() => {});
      this.binaryType = binaryType || "arraybuffer";
      this.retry = 0;
      this.closedByUser = false;
      this.connect();
    }
    connect() {
      this.onStatus("baglaniyor");
      const ws = new WebSocket(this.url);
      ws.binaryType = this.binaryType;
      ws.onopen = () => {
        this.retry = 0;
        this.onStatus("bagli");
      };
      ws.onmessage = (e) => {
        if (typeof e.data !== "string") return;
        try {
          this.onMessage(JSON.parse(e.data));
        } catch (err) {
          console.error("Geçersiz mesaj", err);
        }
      };
      ws.onclose = (e) => {
        if (this.closedByUser) return;
        if (e.code === 4403 || e.code === 4404) {
          this.onStatus("reddedildi", e.code);
          return;
        }
        this.onStatus("koptu");
        const delay = Math.min(10000, 500 * 2 ** this.retry++);
        setTimeout(() => this.connect(), delay);
      };
      this.ws = ws;
    }
    get open() {
      return this.ws && this.ws.readyState === WebSocket.OPEN;
    }
    send(data) {
      if (this.open) this.ws.send(data);
    }
    sendJson(obj) {
      this.send(JSON.stringify(obj));
    }
    close() {
      this.closedByUser = true;
      if (this.ws) this.ws.close();
    }
  }

  function fmtTime(ms) {
    const s = Math.floor(ms / 1000);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const pad = (x) => String(x).padStart(2, "0");
    return (h ? pad(h) + ":" : "") + pad(m) + ":" + pad(s % 60);
  }

  /** Altyazı alanı: kesinleşen satırlar + tek bir kısmi (gri) satır. */
  class CaptionView {
    constructor(container, { onTermClick } = {}) {
      this.container = container;
      this.list = container.querySelector(".caption-final");
      this.partialEl = container.querySelector(".caption-partial");
      this.onTermClick = onTermClick || (() => {});
      this.autoScroll = true;
      this.seen = new Set();
      this.scroller = container.querySelector(".caption-scroll") || container;
      this.scroller.addEventListener("scroll", () => {
        const el = this.scroller;
        this.autoScroll = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      });
    }

    clear() {
      this.list.textContent = "";
      this.partialEl.textContent = "";
      this.seen.clear();
    }

    setPartial(text) {
      this.partialEl.textContent = text || "";
      this.scroll();
    }

    addFinal(seg) {
      if (seg.id != null && this.seen.has(seg.id)) return;
      if (seg.id != null) this.seen.add(seg.id);
      const p = document.createElement("p");
      p.className = "caption-line";
      const time = document.createElement("span");
      time.className = "caption-time";
      time.textContent = fmtTime(seg.start_ms || 0);
      p.appendChild(time);
      this.renderText(p, seg.text, seg.spans || []);
      this.list.appendChild(p);
      this.partialEl.textContent = "";
      this.scroll();
    }

    /** Terimleri vurgulayarak metni güvenli biçimde (textContent) yazar. */
    renderText(parent, text, spans) {
      const sorted = spans.slice().sort((a, b) => a[0] - b[0]);
      let pos = 0;
      for (const [start, end, termId] of sorted) {
        if (start < pos) continue;
        if (start > pos) parent.appendChild(document.createTextNode(text.slice(pos, start)));
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "term-mark";
        btn.textContent = text.slice(start, end);
        btn.dataset.termId = termId;
        btn.title = "Terim kartını göster";
        btn.addEventListener("click", () => this.onTermClick(termId));
        parent.appendChild(btn);
        pos = end;
      }
      if (pos < text.length) parent.appendChild(document.createTextNode(text.slice(pos)));
    }

    scroll() {
      if (this.autoScroll) this.scroller.scrollTop = this.scroller.scrollHeight;
    }
  }

  /** Tespit edilen terimlerin kartları (en yeni üstte). */
  class TermCards {
    constructor(list, emptyEl) {
      this.list = list;
      this.cards = new Map();
      this.empty = emptyEl;
    }

    add(term, { highlight = true } = {}) {
      let card = this.cards.get(term.id);
      if (!card) {
        card = this.build(term);
        this.cards.set(term.id, card);
        if (this.empty) this.empty.hidden = true;
      }
      this.list.prepend(card);
      if (highlight) {
        card.classList.remove("card-new");
        void card.offsetWidth; // animasyonu yeniden başlat
        card.classList.add("card-new");
      }
      return card;
    }

    focus(termId) {
      const card = this.cards.get(Number(termId));
      if (!card) return;
      card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      card.focus({ preventScroll: true });
    }

    build(term) {
      const card = document.createElement("article");
      card.className = "term-card";
      card.tabIndex = -1;
      card.id = "terim-" + term.id;

      const h = document.createElement("h3");
      h.textContent = term.term;
      card.appendChild(h);

      const p = document.createElement("p");
      p.className = "term-def";
      p.textContent = term.definition;
      card.appendChild(p);

      if (term.image) {
        const img = document.createElement("img");
        img.src = term.image;
        img.alt = term.term + " için açıklayıcı görsel";
        img.loading = "lazy";
        card.appendChild(img);
      }

      if (term.video) {
        const details = document.createElement("details");
        details.className = "term-video";
        const summary = document.createElement("summary");
        summary.textContent = "TİD videosunu göster";
        details.appendChild(summary);
        details.addEventListener(
          "toggle",
          () => {
            if (!details.open || details.dataset.loaded) return;
            details.dataset.loaded = "1";
            let media;
            if (term.video.kind === "youtube") {
              media = document.createElement("iframe");
              media.src = term.video.src;
              media.title = term.term + " — Türk İşaret Dili";
              media.allow = "encrypted-media; picture-in-picture";
              media.allowFullscreen = true;
            } else {
              media = document.createElement("video");
              media.src = term.video.src;
              media.controls = true;
              media.loop = true;
              media.muted = true;
              media.playsInline = true;
              media.autoplay = true;
            }
            details.appendChild(media);
          },
          false
        );
        card.appendChild(details);
      }
      return card;
    }
  }

  window.Altyazi = { LiveSocket, CaptionView, TermCards, fmtTime };
})();
