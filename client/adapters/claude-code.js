#!/usr/bin/env node
'use strict';
// Adaptador de los controles del cliente al formato de hooks de Claude Code.
//
// Recibe el evento que leyó hook.js, se lo pasa a la política común y devuelve la
// decisión en el formato que espera la aplicación. No decide nada por su cuenta. Si
// algo falla aquí, la llamada sigue su curso: los controles nunca dejan a la persona sin
// su herramienta, y lo que de verdad no se puede hacer lo rechaza Datalum.

const fs = require('fs');
const path = require('path');
const policy = require('../policy');
const store = require('../state');
const human = require('../human');

const ROOT = path.resolve(__dirname, '..', '..');

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (_) {
    return fallback;
  }
}

function pluginVersion() {
  return readJson(path.join(ROOT, '.claude-plugin', 'plugin.json'), {}).version || null;
}

function contractFacts() {
  return readJson(path.join(ROOT, 'client', 'contract-facts.json'), { citas_humanas: {}, sin_selection_context: [] });
}

// Una conversación no mezcla instrucciones de dos versiones del plugin: si el plugin
// cambió a mitad de la sesión, el modelo vuelve a cargar la Skill antes de seguir.
function versionNote(state, current) {
  if (!current || state.plugin_version === current) return null;
  const previous = state.plugin_version;
  state.plugin_version = current;
  if (!previous) return null;
  return (
    `The Datalum plugin was updated during this conversation (${previous} to ${current}). The skill text you read earlier ` +
    'belongs to the old version: load the Datalum skill again before the next Datalum step. The selected agent and its ' +
    'version do not change because of this.'
  );
}

// `host.dialogs` dice si la aplicación sabe preguntarle a la persona cuando un hook lo
// pide. Claude Code sí; donde no, lo que habría sido una pregunta se niega con el motivo.
const CLAUDE_CODE = { dialogs: true };

function handle(event, host) {
  if (!event || !event.session_id) return null;
  // Las llamadas que no son de Datalum se descartan antes de tocar el disco.
  if (event.hook_event_name !== 'SessionStart' && !policy.isDatalum(store.load(event.session_id, null), event.tool_name)) {
    return null;
  }
  return store.withLock(event.session_id, () => handleLocked(event, host || CLAUDE_CODE));
}

function handleLocked(event, host) {
  const name = event.hook_event_name;
  const sessionId = event.session_id;
  const current = pluginVersion();
  const now = Date.now();

  if (name === 'SessionStart') {
    store.prune(now);
    if (event.source === 'startup' || event.source === 'clear') {
      store.save(sessionId, policy.newState(current));
      return null;
    }
    const state = store.load(sessionId, current);
    const note = versionNote(state, current);
    const context = [policy.resumeContext(state), note].filter(Boolean).join('\n');
    store.save(sessionId, state);
    return context ? { hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: context } } : null;
  }

  const state = store.load(sessionId, current);
  const parsed = policy.isDatalum(state, event.tool_name);
  if (!parsed) return null;
  const input = event.tool_input || {};
  const note = versionNote(state, current);

  const facts = contractFacts();
  const base = { now, at: new Date(now).toISOString(), toolUseId: event.tool_use_id || null, mode: event.permission_mode || null, dialogs: host.dialogs !== false };

  if (name === 'PreToolUse') {
    // Para elegir agente hace falta saber qué eligió la persona en la aplicación.
    const verdict = policy.preToolUse(state, parsed.tool, input, facts, Object.assign({}, base, {
      human: parsed.tool === 'use_agent' ? human.read(event.transcript_path) : undefined,
    }));
    store.save(sessionId, state);
    const output = { hookEventName: 'PreToolUse' };
    if (verdict.decision === 'deny' || verdict.decision === 'ask') {
      output.permissionDecision = verdict.decision;
      output.permissionDecisionReason = verdict.reason;
    }
    if (verdict.input && verdict.decision !== 'deny') output.updatedInput = verdict.input;
    const context = [verdict.context, note].filter(Boolean).join('\n');
    if (context) output.additionalContext = context;
    return Object.keys(output).length > 1 ? { hookSpecificOutput: output } : null;
  }

  let result = null;
  const ctx = Object.assign({}, base, { server: parsed.server });
  if (name === 'PostToolUse') {
    result = policy.postToolUse(state, parsed.tool, input, event.tool_response, ctx, facts);
  } else if (name === 'PostToolUseFailure') {
    if (event.is_interrupt) return null;
    result = policy.postToolUseFailure(state, parsed.tool, input, event.error, ctx, facts);
  } else if (name === 'PermissionDenied') {
    result = policy.permissionDenied(state, parsed.tool, input, ctx);
  } else {
    return null;
  }
  store.save(sessionId, state);
  const context = [result && result.context, note].filter(Boolean).join('\n');
  return context ? { hookSpecificOutput: { hookEventName: name, additionalContext: context } } : null;
}

module.exports = { handle };

if (require.main === module) require('./hook').run(module.exports);
