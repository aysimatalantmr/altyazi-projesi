/* Öğrenci sayfası: altyazıları ve terim kartlarını canlı gösterir. */
document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("ogrenci");
  const code = root.dataset.roomCode;
  const statusEl = document.getElementById("baglanti-durumu");
  const sessionStatusEl = document.getElementById("oturum-durumu");

  const cards = new Altyazi.TermCards(document.getElementById("kart-listesi"), document.getElementById("kart-bos"));
  const view = new Altyazi.CaptionView(document.getElementById("altyazi"), {
    onTermClick: (id) => {
      if (document.documentElement.classList.contains("hide-cards")) {
        AltyaziAyarlar.set({ cards: true });
      }
      cards.focus(id);
    },
  });

  const STATUS_TEXT = {
    baglaniyor: "Bağlanıyor…",
    bagli: "Bağlı",
    koptu: "Bağlantı koptu, yeniden deneniyor…",
    reddedildi: "Oturum bulunamadı",
  };
  const SESSION_TEXT = { waiting: "Ders henüz başlamadı", live: "Canlı", ended: "Ders sona erdi" };

  function setSessionStatus(s) {
    sessionStatusEl.textContent = SESSION_TEXT[s] || s;
    sessionStatusEl.dataset.status = s;
  }

  function addTerms(terms, highlight) {
    (terms || []).forEach((t) => cards.add(t, { highlight }));
  }

  new Altyazi.LiveSocket("/ws/ogrenci/" + code + "/", {
    onStatus: (s) => {
      statusEl.textContent = STATUS_TEXT[s] || s;
      statusEl.dataset.status = s;
    },
    onMessage: (msg) => {
      switch (msg.type) {
        case "history":
          view.clear();
          setSessionStatus(msg.status);
          addTerms(msg.terms, false);
          (msg.segments || []).forEach((seg) => view.addFinal(seg));
          break;
        case "partial":
          view.setPartial(msg.text);
          break;
        case "final":
          view.addFinal(msg.segment);
          addTerms(msg.terms, true);
          break;
        case "status":
          setSessionStatus(msg.status);
          if (msg.status !== "live") view.setPartial("");
          break;
      }
    },
  });
});
