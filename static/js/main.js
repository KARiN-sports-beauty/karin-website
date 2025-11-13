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


// ===========================================
// KARiN. Blog Detail Interactions (2025.11)
// ===========================================

document.addEventListener("DOMContentLoaded", () => {
  const likeBtn = document.getElementById("like-btn");
  const likeCount = document.getElementById("like-count");
  const commentToggle = document.getElementById("comment-toggle");
  const commentBox = document.getElementById("comment-box");
  const nameInput = document.getElementById("comment-name");
  const textInput = document.getElementById("comment-input");
  const submitBtn = document.getElementById("comment-submit");
  const list = document.querySelector(".comment-list");
  if (!likeBtn) return;

  const postId = likeBtn.dataset.id;
  const likedKey = `liked_${postId}`;
  let liked = localStorage.getItem(likedKey) === "true";
  if (liked) likeBtn.classList.add("liked");

  // ❤️ いいねトグル
  likeBtn.addEventListener("click", async () => {
    const newLiked = !liked;
    const formData = new FormData();
    formData.append("liked", newLiked);

    const res = await fetch(`/api/like/${postId}`, { method: "POST", body: formData });
    const data = await res.json();

    if (data.success) {
      likeCount.textContent = data.like_count;
      liked = newLiked;
      localStorage.setItem(likedKey, liked);
      likeBtn.classList.toggle("liked", liked);
    }
  });

  // 💬 コメント開閉
  commentToggle.addEventListener("click", () => {
    commentBox.style.display = commentBox.style.display === "none" ? "block" : "none";
  });

  // ✏️ コメント送信
  submitBtn.addEventListener("click", async () => {
    const name = nameInput.value || "匿名";
    const text = textInput.value.trim();
    if (!text) return alert("コメントを入力してください。");

    const formData = new FormData();
    formData.append("name", name);
    formData.append("text", text);

    const res = await fetch(`/api/comment/${postId}`, { method: "POST", body: formData });
    const data = await res.json();

    if (data.success) {
      list.innerHTML = data.comments.map(c => `
        <div class="comment-item">
          <p><strong>${c.name}</strong> さん：</p>
          <p>${c.text}</p>
        </div>
      `).join("");
      textInput.value = "";
      nameInput.value = "";
    } else {
      alert("コメント送信に失敗しました。");
    }
  });
});
