// ============================================================
// SkillSync AI — Persistent State Manager
// ============================================================
// One place for "the user already did this, don't make them do it again".
//
//   • local   — instant, per-user namespaced localStorage (survives refresh)
//   • remote  — /api/state/ui/ (survives logout, new session, other devices)
//   • cache   — payload snapshots validated against a CV fingerprint
//
// Writes paint locally first and are flushed to the server on a debounce, so
// the UI never waits on the network and an offline write is not lost: it is
// queued and replayed on the next successful flush.
// ============================================================

(function (global) {
  "use strict";

  var NS = "ss";
  var VERSION = "v1";
  var QUEUE_KEY = "__queue";
  var OWNER_KEY = "ss:__owner";
  var FLUSH_DELAY = 900;

  /* ────────────────────────────────────────────────────────────
     Identity & key namespacing
     ──────────────────────────────────────────────────────────── */
  function owner() {
    try {
      return localStorage.getItem("email") || localStorage.getItem("username") || "anon";
    } catch (_) {
      return "anon";
    }
  }

  function storageKey(key) {
    return NS + ":" + VERSION + ":" + owner() + ":" + key;
  }

  // On a shared machine the previous account's cached state must not be
  // readable by the next one. Keys are per-user already; this drops the rest.
  function purgeForeign() {
    var current = owner();
    try {
      if (localStorage.getItem(OWNER_KEY) === current) return;
      var prefix = NS + ":" + VERSION + ":";
      var mine = prefix + current + ":";
      var doomed = [];
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (k && k.indexOf(prefix) === 0 && k.indexOf(mine) !== 0) doomed.push(k);
      }
      doomed.forEach(function (k) { localStorage.removeItem(k); });
      localStorage.setItem(OWNER_KEY, current);
    } catch (_) { /* storage disabled — remote state still works */ }
  }

  /* ────────────────────────────────────────────────────────────
     Local layer
     ──────────────────────────────────────────────────────────── */
  var local = {
    get: function (key, fallback) {
      try {
        var raw = localStorage.getItem(storageKey(key));
        if (raw === null) return fallback === undefined ? null : fallback;
        var parsed = JSON.parse(raw);
        if (parsed && parsed.__exp && Date.now() > parsed.__exp) {
          localStorage.removeItem(storageKey(key));
          return fallback === undefined ? null : fallback;
        }
        return parsed && "__v" in parsed ? parsed.__v : parsed;
      } catch (_) {
        return fallback === undefined ? null : fallback;
      }
    },

    set: function (key, value, options) {
      try {
        var envelope = { __v: value, __t: Date.now() };
        if (options && options.ttl) envelope.__exp = Date.now() + options.ttl * 1000;
        localStorage.setItem(storageKey(key), JSON.stringify(envelope));
        return true;
      } catch (_) {
        // Quota exceeded: drop this app's caches and retry once.
        try {
          local.dropCaches();
          localStorage.setItem(storageKey(key), JSON.stringify({ __v: value, __t: Date.now() }));
          return true;
        } catch (__) {
          return false;
        }
      }
    },

    remove: function (key) {
      try { localStorage.removeItem(storageKey(key)); } catch (_) {}
    },

    stampOf: function (key) {
      try {
        var raw = localStorage.getItem(storageKey(key));
        if (!raw) return 0;
        var parsed = JSON.parse(raw);
        return (parsed && parsed.__t) || 0;
      } catch (_) {
        return 0;
      }
    },

    dropCaches: function () {
      try {
        var prefix = NS + ":" + VERSION + ":" + owner() + ":cache.";
        var doomed = [];
        for (var i = 0; i < localStorage.length; i++) {
          var k = localStorage.key(i);
          if (k && k.indexOf(prefix) === 0) doomed.push(k);
        }
        doomed.forEach(function (k) { localStorage.removeItem(k); });
      } catch (_) {}
    },

    clear: function () {
      try {
        var prefix = NS + ":" + VERSION + ":" + owner() + ":";
        var doomed = [];
        for (var i = 0; i < localStorage.length; i++) {
          var k = localStorage.key(i);
          if (k && k.indexOf(prefix) === 0) doomed.push(k);
        }
        doomed.forEach(function (k) { localStorage.removeItem(k); });
      } catch (_) {}
    }
  };

  /* ────────────────────────────────────────────────────────────
     Remote layer
     ──────────────────────────────────────────────────────────── */
  function request(url, options) {
    if (typeof global.api === "function") return global.api(url, options);
    return Promise.reject(new Error("api() unavailable"));
  }

  function authenticated() {
    try { return Boolean(localStorage.getItem("access")); } catch (_) { return false; }
  }

  function readQueue() {
    var queued = local.get(QUEUE_KEY, {});
    return queued && typeof queued === "object" ? queued : {};
  }

  function writeQueue(queue) {
    if (Object.keys(queue).length) local.set(QUEUE_KEY, queue);
    else local.remove(QUEUE_KEY);
  }

  var flushTimer = null;
  var flushing = false;

  function scheduleFlush(delay) {
    if (flushTimer) clearTimeout(flushTimer);
    flushTimer = setTimeout(flush, delay === undefined ? FLUSH_DELAY : delay);
  }

  function flush() {
    if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
    if (flushing || !authenticated()) return Promise.resolve(false);

    var pending = readQueue();
    var keys = Object.keys(pending);
    if (!keys.length) return Promise.resolve(true);

    flushing = true;
    // The queue is cleared optimistically and restored on failure, so writes
    // made while this request is in flight are not dropped.
    writeQueue({});

    return request("/api/state/ui/", {
      method: "POST",
      body: JSON.stringify({ items: pending })
    }).then(function () {
      flushing = false;
      return true;
    }).catch(function () {
      flushing = false;
      var current = readQueue();
      keys.forEach(function (k) {
        if (!(k in current)) current[k] = pending[k];
      });
      writeQueue(current);
      return false;
    });
  }

  var remote = {
    all: function () {
      return request("/api/state/ui/").then(function (data) {
        return (data && data.items) || {};
      }).catch(function () {
        return {};
      });
    },

    get: function (key) {
      return request("/api/state/ui/" + encodeURIComponent(key) + "/")
        .then(function (data) { return data && data.found ? data : null; })
        .catch(function () { return null; });
    },

    set: function (key, value) {
      return request("/api/state/ui/" + encodeURIComponent(key) + "/", {
        method: "PUT",
        body: JSON.stringify({ value: value })
      }).catch(function () { return null; });
    },

    remove: function (key) {
      return request("/api/state/ui/" + encodeURIComponent(key) + "/", { method: "DELETE" })
        .catch(function () { return null; });
    }
  };

  /* ────────────────────────────────────────────────────────────
     Combined read/write
     ──────────────────────────────────────────────────────────── */
  function save(key, value, options) {
    local.set(key, value, options);
    if (!options || options.remote !== false) {
      var queue = readQueue();
      queue[key] = value;
      writeQueue(queue);
      scheduleFlush(options && options.immediate ? 0 : FLUSH_DELAY);
    }
    return value;
  }

  function get(key, fallback) {
    return local.get(key, fallback);
  }

  function remove(key, options) {
    local.remove(key);
    var queue = readQueue();
    delete queue[key];
    writeQueue(queue);
    if (!options || options.remote !== false) remote.remove(key);
  }

  /**
   * Restore a key: paint from local storage immediately, then reconcile with
   * the server copy. `handler` may be called twice — once with the local value
   * (or null) and again if the server holds something different.
   */
  function restore(key, handler, options) {
    var localValue = local.get(key, null);
    var applied = JSON.stringify(localValue);
    var result;
    try { result = handler(localValue, { source: "local" }); } catch (_) {}

    if (!authenticated() || (options && options.remote === false)) {
      return Promise.resolve(result);
    }

    return remote.get(key).then(function (row) {
      if (!row || row.value === undefined || row.value === null) return result;
      if (JSON.stringify(row.value) === applied) return result;
      local.set(key, row.value);
      try { return handler(row.value, { source: "remote", revision: row.revision }); }
      catch (_) { return result; }
    });
  }

  /* ────────────────────────────────────────────────────────────
     Fingerprinted payload cache
     ──────────────────────────────────────────────────────────── */
  // Used for expensive AI payloads: a snapshot is only reusable while it still
  // describes the CV on file, so every entry carries the fingerprint it was
  // produced from.
  var payloadCache = {
    read: function (name, fingerprint) {
      var entry = local.get("cache." + name, null);
      if (!entry || !entry.data) return null;
      if (fingerprint && entry.fingerprint && entry.fingerprint !== fingerprint) return null;
      return entry.data;
    },

    write: function (name, data, fingerprint, ttlSeconds) {
      local.set("cache." + name, {
        data: data,
        fingerprint: fingerprint || "",
        at: Date.now()
      }, { ttl: ttlSeconds || 86400 });
      return data;
    },

    stamp: function (name) {
      var entry = local.get("cache." + name, null);
      return entry && entry.at ? entry.at : 0;
    },

    drop: function (name) {
      local.remove("cache." + name);
    }
  };

  /* ────────────────────────────────────────────────────────────
     Bootstrap (one call restores a whole page)
     ──────────────────────────────────────────────────────────── */
  var bootstrapPromise = null;

  function bootstrap(force) {
    if (bootstrapPromise && !force) return bootstrapPromise;
    if (!authenticated()) return Promise.resolve(null);
    bootstrapPromise = request("/api/state/bootstrap/").catch(function () { return null; });
    return bootstrapPromise;
  }

  /* ────────────────────────────────────────────────────────────
     DOM binding helpers
     ──────────────────────────────────────────────────────────── */
  // CSRF tokens and Django formset management fields describe the rendered
  // page, not the user's input — restoring them would corrupt the next POST.
  var NEVER_PERSIST = /^(csrfmiddlewaretoken|.*-(TOTAL_FORMS|INITIAL_FORMS|MIN_NUM_FORMS|MAX_NUM_FORMS))$/;

  function fieldsOf(form, exclude) {
    var skip = exclude || [];
    return Array.prototype.slice.call(
      form.querySelectorAll("input, select, textarea")
    ).filter(function (el) {
      if (!el.name) return false;
      if (el.type === "file" || el.type === "password" || el.type === "hidden") return false;
      if (NEVER_PERSIST.test(el.name)) return false;
      if (el.dataset && el.dataset.noPersist !== undefined) return false;
      return skip.indexOf(el.name) === -1;
    });
  }

  function readForm(form, exclude) {
    var values = {};
    fieldsOf(form, exclude).forEach(function (el) {
      if (el.type === "checkbox") values[el.name] = el.checked;
      else if (el.type === "radio") { if (el.checked) values[el.name] = el.value; }
      else values[el.name] = el.value;
    });
    return values;
  }

  function writeForm(form, values, exclude) {
    if (!values) return false;
    var touched = false;
    fieldsOf(form, exclude).forEach(function (el) {
      if (!(el.name in values)) return;
      var value = values[el.name];
      if (el.type === "checkbox") { el.checked = Boolean(value); touched = true; }
      else if (el.type === "radio") { el.checked = el.value === value; if (el.checked) touched = true; }
      else if (value !== null && value !== undefined && String(value) !== "") { el.value = value; touched = true; }
    });
    return touched;
  }

  /**
   * Persist a form's contents (filters, drafts) and restore them on load.
   * `onRestore(values, meta)` runs after the fields are repopulated — that is
   * where a page re-runs its search with the restored filters.
   */
  function bindForm(form, key, options) {
    if (!form) return Promise.resolve(null);
    var config = options || {};
    var exclude = config.exclude || [];

    function persist() {
      save(key, readForm(form, exclude), { immediate: config.immediate });
    }

    form.addEventListener("input", persist);
    form.addEventListener("change", persist);
    if (config.clearOnSubmit) {
      form.addEventListener("submit", function () { remove(key); });
    }

    return restore(key, function (values, meta) {
      var touched = writeForm(form, values, exclude);
      if (config.onRestore) config.onRestore(values, Object.assign({ applied: touched }, meta));
      return touched;
    });
  }

  /** Remember and restore a scroll position for a container (or the window). */
  function bindScroll(key, element) {
    var target = element || global;
    var node = element || document.scrollingElement || document.documentElement;

    var stored = local.get(key, null);
    if (stored && typeof stored.top === "number") {
      requestAnimationFrame(function () {
        requestAnimationFrame(function () { node.scrollTop = stored.top; });
      });
    }

    var ticking = false;
    target.addEventListener("scroll", function () {
      if (ticking) return;
      ticking = true;
      setTimeout(function () {
        ticking = false;
        local.set(key, { top: node.scrollTop }, { ttl: 3600 });
      }, 250);
    }, { passive: true });
  }

  /* ────────────────────────────────────────────────────────────
     Lifecycle
     ──────────────────────────────────────────────────────────── */
  function flushNow() {
    // `sendBeacon` cannot carry the Authorization header, so a synchronous
    // best-effort flush is used instead; anything left over is replayed on the
    // next page load from the queue in localStorage.
    flush();
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") flushNow();
  });
  global.addEventListener("pagehide", flushNow);
  global.addEventListener("online", function () { scheduleFlush(0); });

  purgeForeign();

  document.addEventListener("DOMContentLoaded", function () {
    // Replay writes that never reached the server (offline, closed tab, 401).
    if (Object.keys(readQueue()).length) scheduleFlush(1500);
  });

  var SkillSyncState = {
    local: local,
    remote: remote,
    cache: payloadCache,
    get: get,
    save: save,
    remove: remove,
    restore: restore,
    flush: flush,
    bootstrap: bootstrap,
    bindForm: bindForm,
    bindScroll: bindScroll,
    readForm: readForm,
    writeForm: writeForm,
    clearLocal: local.clear,
    owner: owner
  };

  global.SkillSyncState = SkillSyncState;
  global.State = global.State || SkillSyncState;
})(window);
