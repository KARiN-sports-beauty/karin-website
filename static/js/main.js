/* ===============================
   ✅ スライダー再発火対応版
=============================== */
document.addEventListener("DOMContentLoaded", () => {
  const slides = document.querySelectorAll(".slide");
  let index = 0;
  let interval;

  function showSlide() {
    slides.forEach((slide) => slide.classList.remove("active"));
    slides[index].classList.add("active");

    if (index === slides.length - 1) {
      clearInterval(interval);
      return;
    }
    index++;
  }

  showSlide();
  interval = setInterval(showSlide, 4000);
});




/* -------------------------------
   ✅ ハンバーガーメニュー制御
-------------------------------- */
document.addEventListener("DOMContentLoaded", () => {
  const hamburger = document.querySelector(".hamburger");
  const nav = document.querySelector(".nav");

  if (!hamburger || !nav) return; // ← 要素がない場合スキップ

  hamburger.addEventListener("click", () => {
    hamburger.classList.toggle("active");
    nav.classList.toggle("active");
  });

  // ナビ内リンククリックでメニュー閉じる
  nav.querySelectorAll("a").forEach(link => {
    link.addEventListener("click", () => {
      hamburger.classList.remove("active");
      nav.classList.remove("active");
    });
  });
});


/* -------------------------------
   ✅ フェードイン（IntersectionObserver使用）
-------------------------------- */
document.addEventListener("DOMContentLoaded", () => {
  const fadeTargets = document.querySelectorAll("[data-aos='fade-up']");
  if (fadeTargets.length === 0) return;

  const observer = new IntersectionObserver((entries, obs) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("aos-animate");
        obs.unobserve(entry.target);
      }
    });
  }, {
    threshold: 0.2,
    rootMargin: "0px 0px -40px 0px" // ← 画面下より少し早めに発火
  });

  fadeTargets.forEach((el) => observer.observe(el));
});


// スケジュールヘッダーとボディの横スクロール同期
document.addEventListener("DOMContentLoaded", () => {
  const header = document.querySelector(".schedule-row-header");
  const body = document.querySelector(".schedule-row-body");
  if (header && body) {
    header.addEventListener("scroll", () => (body.scrollLeft = header.scrollLeft));
    body.addEventListener("scroll", () => (header.scrollLeft = body.scrollLeft));
  }
});


/* -------------------------------
   ✅ FAQアコーディオン（Contactページ用）
-------------------------------- */
document.addEventListener("DOMContentLoaded", () => {
  const faqQuestions = document.querySelectorAll(".faq-question");
  if (faqQuestions.length === 0) return;

  faqQuestions.forEach((question) => {
    question.addEventListener("click", (event) => {
      event.preventDefault(); // ← ボタン動作のズレ防止

      const answer = question.nextElementSibling;
      const isOpen = question.classList.contains("open");

      // 一旦全て閉じる（単一開閉モード）
      faqQuestions.forEach((q) => {
        q.classList.remove("open");
        q.nextElementSibling.style.maxHeight = null;
      });

      // クリックした項目だけ開閉
      if (!isOpen) {
        question.classList.add("open");
        answer.style.maxHeight = answer.scrollHeight + "px";
      }
    });
  });
});


window.addEventListener("scroll", () => {
  const header = document.querySelector(".header");
  if (header && window.scrollY > 50) {
    header.classList.add("shrink");
  } else if (header) {
    header.classList.remove("shrink");
  }
});

// ------------------------------
// 地図タブ切り替え
// ------------------------------

document.addEventListener("DOMContentLoaded", () => {
  const mapFrame = document.getElementById("mapFrame");
  const tabs = document.querySelectorAll(".map-tab");

  const MAP_URL = {
    tokyo:
      "https://www.google.com/maps/embed?pb=!1m18!1m12!1m3!1d3241.323374196838!2d139.679!3d35.6696!2m3!1f0!2f0!3f0!3m2!1i1024!2i768!4f13.1!3m3!1m2!1s0x6018f3d13f4e3a91%3A0xa1d949af0bcae153!2z44CSMTUxLTAwNjQg5p2x5Lqs6YO95p2x5Lqs5Yy65a-M5bGx5Yy65bCP6YeO77yT5LiB55uu77yR77yW4oiS77yR77yS!5e0!3m2!1sja!2sjp!4v1735669000001",

    fukuoka:
      "https://www.google.com/maps/embed?pb=!1m18!1m12!1m3!1d3240.880906977994!2d130.402!3d33.582456!2m3!1f0!2f0!3f0!3m2!1i1024!2i768!4f13.1!3m3!1m2!1s0x354191a8796c6b7d%3A0xf9c473e0cf7d6aef!2z6YeO5Yy65bGx5Y2X6Zmi5bGx5Y2X!5e0!3m2!1sja!2sjp!4v1735669000002",
  };

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      // タブの見た目切り替え
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");

      // 地図URL切り替え
      const map = tab.dataset.map;
      mapFrame.src = MAP_URL[map];
    });
  });
});
