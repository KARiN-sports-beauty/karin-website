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
  const raw = String(s || '').trim();
  let hh;
  let mm;
  const colon = raw.match(/^(\d{1,2}):(\d{1,2})$/);
  if (colon) {
    hh = parseInt(colon[1], 10);
    mm = parseInt(colon[2], 10);
  } else {
    const digits = raw.replace(/\D/g, '');
    if (!digits) return null;
    if (digits.length <= 2) {
      hh = parseInt(digits, 10);
      mm = 0;
    } else {
      hh = parseInt(digits.slice(0, -2), 10);
      mm = parseInt(digits.slice(-2), 10);
    }
  }
  if (Number.isNaN(hh) || Number.isNaN(mm)) return null;
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

function getFieldEndTimePickers() {
  return {
    hourEl: document.getElementById('field_end_hour'),
    minEl: document.getElementById('field_end_minute'),
    hidden: document.getElementById('field_end_time'),
  };
}

function writeFieldEndTimeFromPickers() {
  const { hourEl, minEl, hidden } = getFieldEndTimePickers();
  if (!hidden) return;
  if (hourEl && minEl) {
    hidden.value = `${hourEl.value}:${minEl.value}`;
  }
}

function syncFieldEndTimePickersFromInput() {
  const { hourEl, minEl, hidden } = getFieldEndTimePickers();
  if (!hidden) return;
  let total = parseExtendedHmToMinute(hidden.value.trim());
  if (total === null) return;
  const hm = formatExtendedHm(snapTotalMinutesToStep(total));
  hidden.value = hm;
  if (hourEl && minEl) {
    const parts = hm.split(':');
    hourEl.value = parts[0];
    minEl.value = parts[1];
  }
}

function snapExtendedTimeInput(input) {
  if (!input) return;
  if (input.id === 'field_end_time') writeFieldEndTimeFromPickers();
  if (!input.value) return;
  const total = parseExtendedHmToMinute(input.value.trim());
  if (total === null) return;
  input.value = formatExtendedHm(snapTotalMinutesToStep(total));
  if (input.id === 'field_end_time') syncFieldEndTimePickersFromInput();
}

function formatReservationDateInput(raw) {
  const digits = String(raw || '').replace(/\D/g, '').slice(0, 8);
  if (digits.length <= 4) return digits;
  if (digits.length <= 6) return `${digits.slice(0, 4)}-${digits.slice(4)}`;
  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6)}`;
}

function formatReservationTimeInput(raw) {
  const digits = String(raw || '').replace(/\D/g, '').slice(0, 4);
  if (digits.length <= 2) return digits;
  return `${digits.slice(0, 2)}:${digits.slice(2)}`;
}

function snapDatetimeLocalInput(input) {
  if (!input || !input.value) return;
  const raw = input.value.replace(' ', 'T');
  const parts = raw.split('T');
  if (!parts[0] || parts[0].length < 10) return;
  const datePart = parts[0].slice(0, 10);
  const total = parseExtendedHmToMinute(parts[1] || '');
  if (total === null) return;
  input.value = `${datePart}T${formatExtendedHm(snapTotalMinutesToStep(total))}`;
  syncReservedAtPartsFromInput();
}

function getReservedAtParts() {
  return {
    dateEl: document.getElementById('reserved_at_date'),
    timeEl: document.getElementById('reserved_at_time'),
    input: document.getElementById('reserved_at'),
  };
}

function syncReservedAtPartsFromInput() {
  const { dateEl, timeEl, input } = getReservedAtParts();
  if (!dateEl || !timeEl || !input || !input.value) return;
  const raw = input.value.replace(' ', 'T');
  const parts = raw.split('T');
  if (parts[0] && parts[0].length >= 10) dateEl.value = parts[0].slice(0, 10);
  if (parts[1]) {
    const total = parseExtendedHmToMinute(parts[1]);
    if (total !== null) timeEl.value = formatExtendedHm(total);
  }
}

function syncReservedAtFromParts() {
  const { dateEl, timeEl, input } = getReservedAtParts();
  if (!dateEl || !timeEl || !input) return;
  const dateValue = formatReservationDateInput(dateEl.value);
  if (dateValue.length === 10) dateEl.value = dateValue;
  const total = parseExtendedHmToMinute(timeEl.value);
  if (dateValue.length < 10 || total === null) return;
  const clock = formatExtendedHm(snapTotalMinutesToStep(total));
  timeEl.value = clock;
  input.value = `${dateValue}T${clock}`;
}

function selectReservationFieldOnFocus(input) {
  if (!input || input.dataset.focusSelectBound) return;
  input.dataset.focusSelectBound = '1';
  input.addEventListener('focus', () => {
    try {
      input.select();
    } catch (err) {
      /* Safari などで選択できない場合は手入力を優先する */
    }
  });
}

function bindReservationDatetimeInput(input) {
  if (input && !input.dataset.timeStepBound) {
    input.dataset.timeStepBound = '1';
    input.addEventListener('change', () => snapDatetimeLocalInput(input));
    input.addEventListener('blur', () => snapDatetimeLocalInput(input));
    snapDatetimeLocalInput(input);
  }
  const dateEl = document.getElementById('reserved_at_date');
  const timeEl = document.getElementById('reserved_at_time');
  if (dateEl && timeEl && !dateEl.dataset.timePartBound) {
    dateEl.dataset.timePartBound = '1';
    selectReservationFieldOnFocus(dateEl);
    selectReservationFieldOnFocus(timeEl);
    dateEl.addEventListener('change', syncReservedAtFromParts);
    timeEl.addEventListener('change', syncReservedAtFromParts);
    dateEl.addEventListener('blur', syncReservedAtFromParts);
    timeEl.addEventListener('blur', syncReservedAtFromParts);
    if (input && input.value) syncReservedAtPartsFromInput();
    else syncReservedAtFromParts();
  }
}

function bindReservationTimeInputs() {
  bindReservationDatetimeInput(document.getElementById('reserved_at'));
  const fieldEndInput = document.getElementById('field_end_time');
  if (!fieldEndInput) return;

  const hourEl = document.getElementById('field_end_hour');
  const minEl = document.getElementById('field_end_minute');
  if (hourEl && minEl) {
    if (!fieldEndInput.dataset.timePickerBound) {
      fieldEndInput.dataset.timePickerBound = '1';
      const onPick = () => snapExtendedTimeInput(fieldEndInput);
      hourEl.addEventListener('change', onPick);
      minEl.addEventListener('change', onPick);
    }
    syncFieldEndTimePickersFromInput();
  }

  if (fieldEndInput.dataset.timeStepBound) return;
  fieldEndInput.dataset.timeStepBound = '1';
  selectReservationFieldOnFocus(fieldEndInput);
  fieldEndInput.addEventListener('change', () => snapExtendedTimeInput(fieldEndInput));
  fieldEndInput.addEventListener('blur', () => snapExtendedTimeInput(fieldEndInput));
  snapExtendedTimeInput(fieldEndInput);
}
