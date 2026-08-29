/** 予定作成・編集：コースメニュー（トータルコンディショニング / 鍼灸のみ） */
const ADMIN_MENU_CATALOG = {
  total_conditioning: {
    label: 'トータルコンディショニングコース',
    durations: [120, 90, 60],
    prices: {
      tokyo: { 120: 20000, 90: 15000, 60: 10000 },
      fukuoka: { 120: 16000, 90: 12000, 60: 8000 },
    },
  },
  shinkyu_only: {
    label: '鍼灸のみ',
    inHouseOnly: true,
    durations: [90, 60, 30],
    prices: {
      tokyo: { 90: 12000, 60: 8000, 30: 4000 },
      fukuoka: { 90: 9000, 60: 6000, 30: 3000 },
    },
  },
};

function refreshAdminReservationMenus(selectedValue) {
  const areaEl = document.getElementById('area');
  const menuSelect = document.getElementById('menu');
  const placeTypeEl = document.getElementById('place_type');
  if (!menuSelect) return;

  const area = areaEl ? areaEl.value : '';
  const placeType = placeTypeEl ? placeTypeEl.value : '';
  const keep = selectedValue !== undefined ? selectedValue : menuSelect.value;

  menuSelect.innerHTML = '<option value="">コースを選択してください</option>';

  if (placeType === 'field') {
    const otherOption = document.createElement('option');
    otherOption.value = 'other';
    otherOption.textContent = 'その他（帯同）';
    otherOption.dataset.price = '';
    menuSelect.appendChild(otherOption);
  }

  if (!area || placeType === 'field' || placeType === 'break') {
    if (keep) {
      menuSelect.value = keep;
      if (!menuSelect.value && /^\d+$/.test(String(keep))) {
        menuSelect.value = `total_conditioning:${keep}`;
      }
    }
    if (typeof updatePrice === 'function') updatePrice();
    return;
  }

  ['total_conditioning', 'shinkyu_only'].forEach((key) => {
    const cat = ADMIN_MENU_CATALOG[key];
    if (!cat) return;
    if (cat.inHouseOnly && placeType !== 'in_house') return;

    const optgroup = document.createElement('optgroup');
    optgroup.label = cat.label;
    const prices = (cat.prices || {})[area] || {};

    cat.durations.forEach((minutes) => {
      const priceExTax = prices[minutes];
      if (priceExTax === undefined) return;
      const option = document.createElement('option');
      option.value = `${key}:${minutes}`;
      const priceWithTax = Math.floor(priceExTax * 1.1);
      option.textContent = `${minutes}分（¥${priceWithTax.toLocaleString()}税込）`;
      option.dataset.price = String(priceExTax);
      optgroup.appendChild(option);
    });

    if (optgroup.children.length) {
      menuSelect.appendChild(optgroup);
    }
  });

  if (keep) {
    menuSelect.value = keep;
    if (!menuSelect.value && /^\d+$/.test(String(keep))) {
      menuSelect.value = `total_conditioning:${keep}`;
    }
  }

  if (typeof updatePrice === 'function') updatePrice();
}

function bindAdminReservationMenuListeners() {
  const areaEl = document.getElementById('area');
  const placeTypeEl = document.getElementById('place_type');
  if (areaEl && !areaEl.dataset.menuBound) {
    areaEl.dataset.menuBound = '1';
    areaEl.addEventListener('change', () => refreshAdminReservationMenus());
  }
  if (placeTypeEl && !placeTypeEl.dataset.menuBound) {
    placeTypeEl.dataset.menuBound = '1';
    placeTypeEl.addEventListener('change', () => refreshAdminReservationMenus());
  }
}

const RESERVATION_TIMELINE_END_HOUR = 26;
const RESERVATION_TIME_STEP_MINUTES = 15;

function parseExtendedHmToMinute(s) {
  const m = String(s || '').trim().match(/^(\d{1,2}):(\d{2})$/);
  if (!m) return null;
  const hh = parseInt(m[1], 10);
  const mm = parseInt(m[2], 10);
  if (hh < 0 || hh > RESERVATION_TIMELINE_END_HOUR || mm < 0 || mm > 59) return null;
  return hh * 60 + mm;
}

function formatExtendedHm(totalMinutes) {
  const maxMin = RESERVATION_TIMELINE_END_HOUR * 60;
  const v = Math.max(0, Math.min(maxMin, Number(totalMinutes) || 0));
  const hh = String(Math.floor(v / 60)).padStart(2, '0');
  const mm = String(v % 60).padStart(2, '0');
  return `${hh}:${mm}`;
}

function snapTotalMinutesToStep(totalMinutes) {
  return Math.round(totalMinutes / RESERVATION_TIME_STEP_MINUTES) * RESERVATION_TIME_STEP_MINUTES;
}

function snapExtendedTimeInput(input) {
  if (!input || !input.value) return;
  const total = parseExtendedHmToMinute(input.value.trim());
  if (total === null) return;
  input.value = formatExtendedHm(snapTotalMinutesToStep(total));
}

function snapDatetimeLocalInput(input) {
  if (!input || !input.value || input.value.length < 16) return;
  const [datePart, timePart] = input.value.split('T');
  const [h, m] = timePart.split(':').map((v) => parseInt(v, 10));
  if (Number.isNaN(h) || Number.isNaN(m)) return;
  const snapped = snapTotalMinutesToStep(h * 60 + m);
  input.value = `${datePart}T${String(Math.floor(snapped / 60)).padStart(2, '0')}:${String(snapped % 60).padStart(2, '0')}`;
}

function bindReservationDatetimeInput(input) {
  if (!input || input.dataset.timeStepBound) return;
  input.dataset.timeStepBound = '1';
  input.addEventListener('change', () => snapDatetimeLocalInput(input));
  input.addEventListener('blur', () => snapDatetimeLocalInput(input));
  snapDatetimeLocalInput(input);
}

function bindReservationTimeInputs() {
  bindReservationDatetimeInput(document.getElementById('reserved_at'));
  const fieldEndInput = document.getElementById('field_end_time');
  if (!fieldEndInput || fieldEndInput.dataset.timeStepBound) return;
  fieldEndInput.dataset.timeStepBound = '1';
  fieldEndInput.addEventListener('change', () => snapExtendedTimeInput(fieldEndInput));
  fieldEndInput.addEventListener('blur', () => snapExtendedTimeInput(fieldEndInput));
  snapExtendedTimeInput(fieldEndInput);
}
