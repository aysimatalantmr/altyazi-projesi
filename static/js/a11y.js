/* Erişilebilirlik ayarları: yazı boyutu, tema, satır aralığı, görünüm seçenekleri.
 * Tercihler yalnızca bu tarayıcıda (localStorage) saklanır. */
(function () {
  const KEY = "altyazi-ayarlar";
  const DEFAULTS = { size: 40, theme: "koyu", spacing: 1.4, partials: true, cards: true, font: "sistem" };
  const THEMES = ["koyu", "sari", "acik"];
  const root = document.documentElement;

  function load() {
    try {
      const raw = localStorage.getItem(KEY);
      return Object.assign({}, DEFAULTS, raw ? JSON.parse(raw) : {});
    } catch (e) {
      return Object.assign({}, DEFAULTS);
    }
  }

  function save(s) {
    try {
      localStorage.setItem(KEY, JSON.stringify(s));
    } catch (e) {
      /* gizli pencere vb. — sorun değil */
    }
  }

  let state = load();

  function apply() {
    if (!THEMES.includes(state.theme)) state.theme = DEFAULTS.theme;
    state.size = Math.min(96, Math.max(20, Number(state.size) || DEFAULTS.size));
    root.dataset.theme = state.theme;
    root.dataset.font = state.font;
    root.style.setProperty("--caption-size", state.size + "px");
    root.style.setProperty("--caption-spacing", state.spacing);
    root.classList.toggle("hide-partials", !state.partials);
    root.classList.toggle("hide-cards", !state.cards);

    const sizeOut = document.getElementById("ayar-boyut-deger");
    if (sizeOut) sizeOut.textContent = state.size + " px";
    document.querySelectorAll("[data-ayar-tema]").forEach((btn) => {
      btn.setAttribute("aria-pressed", String(btn.dataset.ayarTema === state.theme));
    });
    const sp = document.getElementById("ayar-aralik");
    if (sp) sp.value = state.spacing;
    const pa = document.getElementById("ayar-kismi");
    if (pa) pa.checked = state.partials;
    const ca = document.getElementById("ayar-kartlar");
    if (ca) ca.checked = state.cards;
    const fo = document.getElementById("ayar-font");
    if (fo) fo.value = state.font;
  }

  function set(patch) {
    state = Object.assign(state, patch);
    apply();
    save(state);
  }

  // Sayfa çizilmeden önce uygula (yanıp sönmeyi önler)
  apply();

  document.addEventListener("DOMContentLoaded", () => {
    apply();
    const on = (id, ev, fn) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener(ev, fn);
    };
    on("ayar-kucult", "click", () => set({ size: state.size - 4 }));
    on("ayar-buyut", "click", () => set({ size: state.size + 4 }));
    on("ayar-aralik", "input", (e) => set({ spacing: Number(e.target.value) }));
    on("ayar-kismi", "change", (e) => set({ partials: e.target.checked }));
    on("ayar-kartlar", "change", (e) => set({ cards: e.target.checked }));
    on("ayar-font", "change", (e) => set({ font: e.target.value }));
    on("ayar-sifirla", "click", () => set(Object.assign({}, DEFAULTS)));
    document.querySelectorAll("[data-ayar-tema]").forEach((btn) =>
      btn.addEventListener("click", () => set({ theme: btn.dataset.ayarTema }))
    );

    // Klavye kısayolları: Ctrl/Alt değil, yalnızca + ve - (form alanı dışında)
    document.addEventListener("keydown", (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const tag = (e.target.tagName || "").toLowerCase();
      if (["input", "textarea", "select"].includes(tag)) return;
      if (e.key === "+") set({ size: state.size + 4 });
      else if (e.key === "-") set({ size: state.size - 4 });
    });
  });

  window.AltyaziAyarlar = { get: () => Object.assign({}, state), set };
})();
