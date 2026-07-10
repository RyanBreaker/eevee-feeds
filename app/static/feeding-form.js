function initFeedingForm(form) {
  const timestampInput = form.querySelector('input[name="timestamp"]');
  const totalInput = form.querySelector('input[name="per_feed_total"]');
  const ngInput = form.querySelector('input[name="ng_amount"]');
  const poInput = form.querySelector('input[name="po_amount"]');
  if (!timestampInput || !totalInput || !ngInput || !poInput) return;

  async function updateTotalFromDate() {
    const ts = timestampInput.value;
    if (!ts) return;
    const dateStr = ts.slice(0, 10);
    try {
      const resp = await fetch('/api/feed-target?date=' + encodeURIComponent(dateStr));
      if (!resp.ok) return;
      const data = await resp.json();
      totalInput.value = data.per_feed;
    } catch (err) {
      console.error('Failed to fetch feed target:', err);
    }
  }

  function updatePO() {
    const total = parseInt(totalInput.value, 10) || 0;
    const ng = parseInt(ngInput.value, 10) || 0;
    if (ng > total) {
      poInput.value = 0;
      ngInput.classList.add('invalid');
    } else {
      poInput.value = Math.ceil(total - ng);
      ngInput.classList.remove('invalid');
    }
  }

  timestampInput.addEventListener('change', updateTotalFromDate);
  ngInput.addEventListener('input', updatePO);
  poInput.addEventListener('input', function () {
    ngInput.classList.remove('invalid');
  });

  updateTotalFromDate();
}

function initAllFeedingForms(root) {
  root = root || document;
  root.querySelectorAll('form.feeding-form').forEach(initFeedingForm);
}

document.addEventListener('DOMContentLoaded', function () {
  initAllFeedingForms();
});

document.addEventListener('htmx:afterSwap', function (event) {
  initAllFeedingForms(event.detail.elt);
});
