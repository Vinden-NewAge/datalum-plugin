'use strict';
// Estado de los controles por sesión, en el directorio de datos del plugin.
//
// Guarda qué agente selló la conversación, qué documentos del cerebro se leyeron y qué
// escrituras quedaron confirmadas o inciertas. No guarda datos del negocio, mensajes
// de la persona ni credenciales.

const fs = require('fs');
const os = require('os');
const path = require('path');
const policy = require('./policy');

const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

function dir() {
  const base = process.env.CLAUDE_PLUGIN_DATA || path.join(os.tmpdir(), 'datalum-plugin');
  return path.join(base, 'sessions');
}

function file(sessionId) {
  const safe = String(sessionId || 'sin-sesion').replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 120);
  return path.join(dir(), safe + '.json');
}

function load(sessionId, pluginVersion) {
  try {
    const state = JSON.parse(fs.readFileSync(file(sessionId), 'utf8'));
    if (state && state.v === 1) return state;
  } catch (_) {
    // Sin estado guardado o ilegible: se empieza de cero.
  }
  return policy.newState(pluginVersion);
}

function save(sessionId, state) {
  const target = file(sessionId);
  fs.mkdirSync(path.dirname(target), { recursive: true, mode: 0o700 });
  const tmp = target + '.' + process.pid + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(state), { mode: 0o600 });
  fs.renameSync(tmp, target);
}

// Las aplicaciones pueden lanzar a la vez los hooks de varias llamadas paralelas.
// Leer, cambiar y guardar el estado se hace con un candado por sesión para que un
// proceso no pise lo que guardó otro. Si el candado no se consigue en dos segundos
// (un proceso que murió con él puesto), se toma igual tras darlo por abandonado.
const LOCK_WAIT_MS = 2000;
const LOCK_STALE_MS = 10000;

function sleep(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function withLock(sessionId, fn) {
  const lock = file(sessionId) + '.lock';
  fs.mkdirSync(path.dirname(lock), { recursive: true, mode: 0o700 });
  const start = Date.now();
  let fd = null;
  while (fd === null) {
    try {
      fd = fs.openSync(lock, 'wx', 0o600);
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      let age = 0;
      try {
        age = Date.now() - fs.statSync(lock).mtimeMs;
      } catch (_) {
        continue;
      }
      if (age > LOCK_STALE_MS || Date.now() - start > LOCK_WAIT_MS) {
        try {
          fs.unlinkSync(lock);
        } catch (_) {
          // Otro proceso lo quitó antes.
        }
        continue;
      }
      sleep(15);
    }
  }
  try {
    return fn();
  } finally {
    fs.closeSync(fd);
    try {
      fs.unlinkSync(lock);
    } catch (_) {
      // Ya no estaba.
    }
  }
}

function prune(now) {
  let names;
  try {
    names = fs.readdirSync(dir());
  } catch (_) {
    return;
  }
  for (const name of names) {
    const full = path.join(dir(), name);
    try {
      if (now - fs.statSync(full).mtimeMs > MAX_AGE_MS && !name.endsWith('.lock')) fs.unlinkSync(full);
    } catch (_) {
      // Otro proceso lo borró antes.
    }
  }
}

module.exports = { load, save, prune, withLock, file, dir };
