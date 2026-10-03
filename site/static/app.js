// MemoFast yama sitesi: arama, filtre, sıralama, "Yeni" etiketi, resim yedeği, "Launcher'da aç" ipucu.
(function () {
  "use strict";

  // Kapak resmi yüklenmezse önce Steam başlık resmini dene, o da olmazsa oyun adını göster.
  document.querySelectorAll("img[data-fallback]").forEach(function (img) {
    function fail() {
      var fb = img.getAttribute("data-fallback");
      if (fb && img.src !== fb) { img.src = fb; img.setAttribute("data-fallback", ""); return; }
      var box = img.closest(".cover");
      if (box) box.classList.add("noimg");
      img.remove();
    }
    if (img.complete && img.naturalWidth === 0 && img.currentSrc) fail();
    else img.addEventListener("error", fail);
  });

  // Son 10 günde güncellenen yamalara "Yeni" etiketi.
  var now = Date.now();
  document.querySelectorAll(".card[data-updated]").forEach(function (c) {
    var t = Date.parse(c.getAttribute("data-updated"));
    if (c.getAttribute("data-tier") !== "soon" && t && now - t < 10 * 864e5) {
      var tag = document.createElement("span");
      tag.className = "tag tag-new";
      tag.textContent = "Yeni";
      c.querySelector(".cover").appendChild(tag);
    }
  });

  // "Launcher'da aç": launcher kurulu değilse protokol bir şey açmaz; kısa süre sonra ipucu göster.
  document.querySelectorAll("[data-open]").forEach(function (a) {
    a.addEventListener("click", function () {
      var left = false;
      function gone() { left = true; }
      window.addEventListener("blur", gone, { once: true });
      document.addEventListener("visibilitychange", gone, { once: true });
      setTimeout(function () {
        if (left) return;
        var note = a.closest(".cta") && a.closest(".cta").nextElementSibling;
        if (note && note.hasAttribute("data-open-note")) note.hidden = false;
      }, 1600);
    });
  });

  // Liste sayfası
  var grid = document.getElementById("grid");
  if (!grid) return;
  var q = document.getElementById("q");
  var sort = document.getElementById("sort");
  var empty = document.getElementById("empty");
  var chips = Array.prototype.slice.call(document.querySelectorAll(".chip"));
  var cards = Array.prototype.slice.call(grid.children);
  var filter = "all";

  function norm(s) {
    return (s || "").toLocaleLowerCase("tr")
      .replace(/ı/g, "i").replace(/ğ/g, "g").replace(/ü/g, "u").replace(/ş/g, "s").replace(/ö/g, "o").replace(/ç/g, "c")
      .replace(/[^a-z0-9]+/g, " ").trim();
  }
  cards.forEach(function (c) { c._s = norm(c.getAttribute("data-search")); });

  function apply() {
    var words = norm(q.value).split(" ").filter(Boolean);
    var shown = 0;
    cards.forEach(function (c) {
      var ok = (filter === "all" || c.getAttribute("data-tier") === filter) &&
        words.every(function (w) { return c._s.indexOf(w) !== -1; });
      c.hidden = !ok;
      if (ok) shown++;
    });
    empty.hidden = shown > 0;
  }

  function order() {
    var by = sort.value;
    cards.sort(function (a, b) {
      if (by === "az") return a.getAttribute("data-name").localeCompare(b.getAttribute("data-name"), "tr");
      var sa = a.getAttribute("data-tier") === "soon", sb = b.getAttribute("data-tier") === "soon";
      if (sa !== sb) return sa ? 1 : -1;
      return (b.getAttribute("data-updated") || "").localeCompare(a.getAttribute("data-updated") || "");
    });
    cards.forEach(function (c) { grid.appendChild(c); });
  }

  chips.forEach(function (ch) {
    ch.addEventListener("click", function () {
      filter = ch.getAttribute("data-filter");
      chips.forEach(function (x) { x.setAttribute("aria-pressed", String(x === ch)); });
      apply();
    });
  });
  q.addEventListener("input", apply);
  sort.addEventListener("change", order);

  // Adres çubuğundan ?q=elden gibi arama
  var p = new URLSearchParams(location.search).get("q");
  if (p) { q.value = p; apply(); }

  // "/" tuşu aramaya odaklar
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "/" && document.activeElement !== q && !/input|textarea|select/i.test(document.activeElement.tagName)) {
      ev.preventDefault(); q.focus();
    }
  });
})();
