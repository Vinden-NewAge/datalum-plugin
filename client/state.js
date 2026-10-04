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
      if (now - fs.statSync(full).mtimeMs > MAX_AGE_MS) fs.unlinkSync(full);
    } catch (_) {
      // Otro proceso lo borró antes.
    }
  }
}

module.exports = { load, save, prune, file, dir };
