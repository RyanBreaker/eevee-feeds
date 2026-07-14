function formatDurationMinutes(totalMinutes) {
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours > 0) {
    return hours + 'h ' + minutes + 'm';
  }
  return minutes + 'm';
}

function formatDateTimeLocal(date) {
  const pad = function (n) {
    return String(n).padStart(2, '0');
  };
  return (
    date.getFullYear() +
    '-' +
    pad(date.getMonth() + 1) +
    '-' +
    pad(date.getDate()) +
    'T' +
    pad(date.getHours()) +
    ':' +
    pad(date.getMinutes())
  );
}

function initFeedingStartForm(form) {
  const timestampInput = form.querySelector('input[name="timestamp"]');
  const nowButton = form.querySelector('.timestamp-now-button');
  if (!timestampInput || !nowButton) return;

  nowButton.addEventListener('click', function () {
    timestampInput.value = formatDateTimeLocal(new Date());
    timestampInput.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

function initFeedingForm(form) {
  const timestampInput = form.querySelector('input[name="timestamp"]');
  const totalInput = form.querySelector('input[name="per_feed_total"]');
  const ngInput = form.querySelector('input[name="ng_amount"]');
  const poInput = form.querySelector('input[name="po_amount"]');
  const feedingIdInput = form.querySelector('input[name="feeding_id"]');
  const noteSpan = form.querySelector('.feed-interval-note');
  if (!timestampInput || !totalInput || !ngInput || !poInput) return;

  function updateIntervalNote(actualIntervalMinutes, intervalMinutes) {
    if (!noteSpan) return;
    if (actualIntervalMinutes != null && intervalMinutes != null) {
      noteSpan.textContent =
        formatDurationMinutes(actualIntervalMinutes) +
        ' since last feed (using ' +
        formatDurationMinutes(intervalMinutes) +
        ')';
    } else {
      noteSpan.textContent = '';
    }
  }

  async function updateTotalFromDate() {
    const ts = timestampInput.value;
    if (!ts) return;
    const params = new URLSearchParams();
    params.append('timestamp', ts);
    if (feedingIdInput && feedingIdInput.value) {
      params.append('feeding_id', feedingIdInput.value);
    }
    try {
      const resp = await fetch('/api/feed-target?' + params.toString());
      if (!resp.ok) return;
      const data = await resp.json();
      const isEdit = feedingIdInput && feedingIdInput.value;
      if (!isEdit) {
        totalInput.value = data.per_feed;
      }
      updateIntervalNote(data.actual_interval_minutes, data.interval_minutes);
    } catch (err) {
      console.error('Failed to fetch feed target:', err);
    }
  }

  form.addEventListener('reset', function () {
    updateIntervalNote(null, null);
  });

  function updateOtherAmount(source, target) {
    const total = parseInt(totalInput.value, 10) || 0;
    const sourceValue = parseInt(source.value, 10) || 0;
    if (sourceValue > total) {
      target.value = 0;
      source.classList.add('invalid');
    } else {
      target.value = Math.ceil(total - sourceValue);
      source.classList.remove('invalid');
    }
    target.classList.remove('invalid');
  }

  timestampInput.addEventListener('change', updateTotalFromDate);
  ngInput.addEventListener('input', function () {
    updateOtherAmount(ngInput, poInput);
  });
  poInput.addEventListener('input', function () {
    updateOtherAmount(poInput, ngInput);
  });
  totalInput.addEventListener('input', function () {
    updateOtherAmount(ngInput, poInput);
  });

  updateTotalFromDate();
}

function initAllFeedingForms(root) {
  root = root || document;
  root.querySelectorAll('form.feeding-form').forEach(initFeedingForm);
  root.querySelectorAll('form.feeding-start-form').forEach(initFeedingStartForm);
}

document.addEventListener('DOMContentLoaded', function () {
  initAllFeedingForms();
});

document.addEventListener('htmx:afterSwap', function (event) {
  initAllFeedingForms(event.detail.elt);
});
