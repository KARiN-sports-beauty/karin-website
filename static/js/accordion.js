document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".accordion-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      let content = btn.nextElementSibling;
      if (!content || !content.classList.contains("accordion-content")) {
        const selector = btn.getAttribute("data-target");
        if (selector) content = document.querySelector(selector);
      }
      if (!content) return;

      const isOpen = content.classList.contains("open");

      if (isOpen) {
        // 閉じる
        content.classList.remove("open");
        content.style.maxHeight = null;
        btn.style.display = "block";
        btn.setAttribute("aria-expanded", "false");
      } else {
        // 開く
        content.classList.add("open");
        content.style.maxHeight = content.scrollHeight + "px";
        btn.style.display = "none"; // ✅ 続きを読むを非表示に
        btn.setAttribute("aria-expanded", "true");
      }
    });
  });

  // 「閉じる」ボタン
  document.addEventListener("click", (e) => {
    if (!e.target.classList.contains("close-btn")) return;

    const content = e.target.closest(".accordion-content");
    if (!content) return;

    content.classList.remove("open");
    content.style.maxHeight = null;

    const opener = content.previousElementSibling;
    if (opener && opener.classList.contains("accordion-btn")) {
      opener.style.display = "block"; // ✅ 閉じたら再表示
      opener.setAttribute("aria-expanded", "false");
    }
  });
});
