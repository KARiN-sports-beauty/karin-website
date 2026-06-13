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
