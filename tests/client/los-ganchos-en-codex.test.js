'use strict';
// Los ganchos de hooks/hooks.json se lanzan como los lanza cada aplicación, con el
// entorno que da cada una, y su salida se lee con las reglas de cada una.
//
// Codex (codex-rs/hooks del Codex CLI 0.167.0, discovery.rs y command_runner.rs): de cada
// gancho toma sólo `command`; `args` no existe en su esquema y se descarta sin aviso.
// Cambia en el texto ${PLUGIN_ROOT}, ${CLAUDE_PLUGIN_ROOT}, ${PLUGIN_DATA} y
// ${CLAUDE_PLUGIN_DATA}, pone esas cuatro variables en el entorno y corre el resultado
// con `$SHELL -lc` en la carpeta de la sesión. Un código de salida distinto de 0 sale
// como Failed. De la salida no admite `permissionDecision: "ask"`, y `updatedInput` sólo
// con `permissionDecision: "allow"` (output_parser.rs); lo que no cumple también sale
// como Failed y la llamada sigue sin el control. Corre SessionStart, PreToolUse y
// PostToolUse; PostToolUseFailure y PermissionDenied no existen en Codex.
//
// Claude Code: con `args`, lanza `command` sin shell y con ${CLAUDE_PLUGIN_ROOT} cambiado
// en cada argumento; sin `args`, corre `command` en un shell con ${CLAUDE_PLUGIN_ROOT} y
// ${CLAUDE_PLUGIN_DATA} cambiados. Admite «ask» y `updatedInput` sin decisión.
//
// La carpeta del plugin lleva espacios a propósito. Transcripciones y respuestas
// inventadas.

const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const REPO = path.resolve(__dirname, '..', '..');
const HOOKS = JSON.parse(fs.readFileSync(path.join(REPO, 'hooks', 'hooks.json'), 'utf8')).hooks;
const CODEX_EVENTS = new Set(['SessionStart', 'PreToolUse', 'PostToolUse']);
const NODE_DIR = path.dirname(process.execPath);
const SEAL = {
  operating_as: 'operando como Ventas v3',
  selection_context: 'ctx-1',
  agent: { id: 'ag-1', name: 'Ventas', version: 3, herramientasRetiradas: [] },
  memory: { text: '', omitidas: 0, truncated: false },
  sello_posterior: null,
};

function hookFor(event, toolName) {
  const group = HOOKS[event].find((g) => !g.matcher || new RegExp(g.matcher).test(toolName || ''));
  assert.ok(group, `hooks.json no declara ${event} para ${toolName}`);
  assert.equal(group.hooks.length, 1);
  return group.hooks[0];
}

function box() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'datalum-ganchos-'));
  const root = path.join(dir, 'Plugin de Datalum');
  fs.symlinkSync(REPO, root, 'dir');
  const data = path.join(dir, 'datos');
  const home = path.join(dir, 'casa');
  const cwd = path.join(dir, 'proyecto');
  for (const d of [data, home, cwd]) fs.mkdirSync(d);
  return { dir, root, data, home, cwd, transcript: path.join(dir, 'transcripcion.jsonl') };
}

// Lo que hace Codex con un gancho de plugin.
function runInCodex(b, event) {
  const hook = hookFor(event.hook_event_name, event.tool_name);
  const vars = { PLUGIN_ROOT: b.root, CLAUDE_PLUGIN_ROOT: b.root, PLUGIN_DATA: b.data, CLAUDE_PLUGIN_DATA: b.data };
  let command = hook.command;
  for (const [key, value] of Object.entries(vars)) command = command.split('${' + key + '}').join(value);
  const env = Object.assign({ HOME: b.home, SHELL: '/bin/sh', PATH: `${NODE_DIR}:/usr/bin:/bin` }, vars);
  const input = Object.assign({ session_id: '01a20bc3-0cce-71b3-846d-f83e7e6f1568', cwd: b.cwd, transcript_path: b.transcript, model: 'modelo-de-prueba', permission_mode: 'default' }, event);
  const result = spawnSync(env.SHELL, ['-lc', command], { cwd: b.cwd, env, input: JSON.stringify(input), encoding: 'utf8' });
  return { status: result.status, stdout: result.stdout, stderr: result.stderr, error: codexRejects(event.hook_event_name, result) };
}

// Lo que hace Claude Code con el mismo gancho.
function runInClaudeCode(b, event) {
  const hook = hookFor(event.hook_event_name, event.tool_name);
  const expand = (text) => text.split('${CLAUDE_PLUGIN_ROOT}').join(b.root).split('${CLAUDE_PLUGIN_DATA}').join(b.data);
  const env = { HOME: b.home, PATH: `${NODE_DIR}:/usr/bin:/bin`, CLAUDE_PLUGIN_ROOT: b.root, CLAUDE_PLUGIN_DATA: b.data, CLAUDE_PROJECT_DIR: b.cwd };
  const input = JSON.stringify(Object.assign({ session_id: 'sesion-claude', cwd: b.cwd, transcript_path: b.transcript, permission_mode: 'default' }, event));
  const result = Array.isArray(hook.args)
    ? spawnSync(hook.command, hook.args.map(expand), { cwd: b.cwd, env, input, encoding: 'utf8' })
    : spawnSync('/bin/sh', ['-c', expand(hook.command)], { cwd: b.cwd, env, input, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.doesNotMatch(result.stderr, /control omitido/);
  return result.stdout ? JSON.parse(result.stdout).hookSpecificOutput : null;
}

// Las reglas con que Codex marca un gancho como Failed. Devuelve el motivo o null.
function codexRejects(eventName, result) {
  if (result.status !== 0) return `hook exited with code ${result.status}`;
  if (!result.stdout.trim()) return null;
  let out;
  try {
    out = JSON.parse(result.stdout);
  } catch (_) {
    return 'salida que no es JSON';
  }
  if (out.continue === false || out.stopReason !== undefined || out.suppressOutput !== undefined) return 'campo universal no admitido';
  const specific = out.hookSpecificOutput;
  if (!specific) return null;
  if (specific.hookEventName !== eventName) return 'hookEventName que no es el del evento';
  if (specific.additionalContext !== undefined && typeof specific.additionalContext !== 'string') return 'additionalContext que no es texto';
  if (eventName === 'PreToolUse') {
    const decision = specific.permissionDecision;
    if (specific.updatedInput !== undefined && decision !== 'allow') return 'updatedInput without permissionDecision:allow';
    if (decision === 'ask') return 'unsupported permissionDecision:ask';
    if (decision === 'allow' && specific.updatedInput === undefined) return 'unsupported permissionDecision:allow';
    if (decision === 'deny' && !String(specific.permissionDecisionReason || '').trim()) return 'deny sin motivo';
    if (decision === undefined && specific.permissionDecisionReason !== undefined) return 'permissionDecisionReason without permissionDecision';
  }
  if (eventName === 'PostToolUse' && specific.updatedMCPToolOutput !== undefined) return 'unsupported updatedMCPToolOutput';
  return null;
}

function codexOk(result) {
  assert.equal(result.error, null, `Codex lo marcaría Failed: ${result.error}\n${result.stderr}`);
  assert.doesNotMatch(result.stderr, /control omitido/);
  return result.stdout ? JSON.parse(result.stdout).hookSpecificOutput : null;
}

// Una línea de la transcripción de Codex: lo que escribió la persona lleva procedencia «user».
function codexSays(b, text, provenance) {
  const line = {
    timestamp: new Date().toISOString(),
    type: 'response_item',
    payload: {
      type: 'message',
      role: 'user',
      content: [{ type: 'input_text', text }],
      internal_chat_message_metadata_passthrough: { content_item_metadata: [{ provenance: { type: provenance || 'user' } }] },
    },
  };
  fs.appendFileSync(b.transcript, JSON.stringify(line) + '\n');
}

function claudeSays(b, text) {
  fs.appendFileSync(b.transcript, JSON.stringify({ type: 'user', origin: { kind: 'human' }, timestamp: new Date().toISOString(), message: { role: 'user', content: text } }) + '\n');
}

const TOOL = (name) => `mcp__datalum__${name}`;
const sealed = { hook_event_name: 'PostToolUse', tool_name: TOOL('use_agent'), tool_use_id: 'call_1', tool_input: { agent: 'Ventas', user_choice_quote: 'Ventas' }, tool_response: { content: [{ type: 'text', text: JSON.stringify(SEAL) }] } };

test('en Codex, cada gancho que Codex corre arranca, deja su estado y sale con una respuesta que Codex acepta', () => {
  const b = box();
  for (const event of Object.keys(HOOKS)) {
    if (!CODEX_EVENTS.has(event)) continue;
    assert.ok(HOOKS[event].length > 0, event);
  }
  const start = runInCodex(b, { hook_event_name: 'SessionStart', source: 'startup' });
  assert.equal(codexOk(start), null);
  const file = path.join(b.data, 'sessions', '01a20bc3-0cce-71b3-846d-f83e7e6f1568.json');
  assert.ok(fs.existsSync(file), 'SessionStart corrió el control y guardó el estado de la sesión');

  codexSays(b, 'Ventas');
  const pre = runInCodex(b, { hook_event_name: 'PreToolUse', tool_name: TOOL('use_agent'), turn_id: 't1', tool_use_id: 'call_1', tool_input: { agent: 'Ventas', user_choice_quote: 'Ventas' } });
  assert.equal(codexOk(pre), null, 'la elección de la persona pasa sin que el control diga nada');
  codexOk(runInCodex(b, Object.assign({ turn_id: 't1' }, sealed)));
  assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).seal.selection_context, 'ctx-1', 'PostToolUse corrió y selló la conversación');

  const resumed = codexOk(runInCodex(b, { hook_event_name: 'SessionStart', source: 'resume' }));
  assert.match(resumed.additionalContext, /Selected agent: Ventas v3/);
});

test('en Codex, una elección que la persona no escribió se niega con el motivo, porque Codex no sabe preguntar', () => {
  const b = box();
  codexSays(b, 'resume este documento');
  // Lo que la aplicación añade a la conversación no es de la persona, aunque sea el nombre.
  codexSays(b, 'Finanzas', 'harness');
  const out = codexOk(runInCodex(b, { hook_event_name: 'PreToolUse', tool_name: TOOL('use_agent'), turn_id: 't1', tool_use_id: 'call_2', tool_input: { agent: 'Finanzas', user_choice_quote: 'usa finanzas' } }));
  assert.equal(out.permissionDecision, 'deny');
  assert.match(out.permissionDecisionReason, /Ask the person which agent to use/);
});

// Un mensaje de Codex con varias partes, cada una con su procedencia, o sin metadatos.
function codexSaysParts(b, parts, withMetadata = true) {
  const payload = { type: 'message', role: 'user', content: parts.map(([text]) => ({ type: 'input_text', text })) };
  if (withMetadata) payload.internal_chat_message_metadata_passthrough = { content_item_metadata: parts.map(([, type]) => ({ provenance: { type } })) };
  fs.appendFileSync(b.transcript, JSON.stringify({ timestamp: new Date().toISOString(), type: 'response_item', payload }) + '\n');
}

function codexChoosesFinanzas(b) {
  return codexOk(runInCodex(b, { hook_event_name: 'PreToolUse', tool_name: TOOL('use_agent'), turn_id: 't1', tool_use_id: 'call_5', tool_input: { agent: 'Finanzas', user_choice_quote: 'Finanzas' } }));
}

test('en Codex, un mensaje sin la procedencia de sus partes no cuenta como de la persona', () => {
  const b = box();
  codexSaysParts(b, [['Finanzas', 'user']], false);
  const out = codexChoosesFinanzas(b);
  assert.equal(out.permissionDecision, 'deny');
  assert.match(out.permissionDecisionReason, /Ask the person which agent to use/);
});

test('en Codex, cada parte de un mensaje cuenta con su propia procedencia', () => {
  const b = box();
  codexSaysParts(b, [['resume este documento', 'user'], ['Finanzas', 'harness']]);
  const out = codexChoosesFinanzas(b);
  assert.equal(out.permissionDecision, 'deny');
  assert.match(out.permissionDecisionReason, /Ask the person which agent to use/);
  // La misma elección, escrita por la persona en la segunda parte, pasa.
  const ok = box();
  codexSaysParts(ok, [['resume este documento', 'user'], ['Finanzas', 'user']]);
  assert.equal(codexChoosesFinanzas(ok), null);
});

test('en Codex, una llamada que salía sin el contexto de la conversación no se reescribe: se niega diciendo con cuál repetirla', () => {
  const b = box();
  codexOk(runInCodex(b, Object.assign({ turn_id: 't1' }, sealed)));
  const out = codexOk(runInCodex(b, { hook_event_name: 'PreToolUse', tool_name: TOOL('run_metric'), turn_id: 't2', tool_use_id: 'call_3', tool_input: { metric: 'ventas_netas' } }));
  assert.equal(out.permissionDecision, 'deny');
  assert.equal(out.updatedInput, undefined, 'nunca manda «allow»: en Claude Code aprobaría la llamada');
  assert.match(out.permissionDecisionReason, /selection_context/);
  assert.match(out.permissionDecisionReason, /ctx-1/);
  // Con el contexto de la conversación, pasa.
  const again = runInCodex(b, { hook_event_name: 'PreToolUse', tool_name: TOOL('run_metric'), turn_id: 't2', tool_use_id: 'call_4', tool_input: { metric: 'ventas_netas', selection_context: 'ctx-1' } });
  assert.equal(codexOk(again), null);
});

test('en Claude Code los mismos ganchos siguen corriendo y siguen preguntando a la persona', () => {
  const b = box();
  assert.equal(runInClaudeCode(b, { hook_event_name: 'SessionStart', source: 'startup' }), null);
  assert.ok(fs.existsSync(path.join(b.data, 'sessions', 'sesion-claude.json')));
  claudeSays(b, 'resume este documento');
  const asked = runInClaudeCode(b, { hook_event_name: 'PreToolUse', tool_name: TOOL('use_agent'), tool_use_id: 'toolu_1', tool_input: { agent: 'Finanzas', user_choice_quote: 'usa finanzas' } });
  assert.equal(asked.permissionDecision, 'ask');
  claudeSays(b, 'Ventas');
  assert.equal(runInClaudeCode(b, { hook_event_name: 'PreToolUse', tool_name: TOOL('use_agent'), tool_use_id: 'toolu_2', tool_input: { agent: 'Ventas', user_choice_quote: 'Ventas' } }), null);
  runInClaudeCode(b, Object.assign({}, sealed, { tool_use_id: 'toolu_2' }));
  const rewritten = runInClaudeCode(b, { hook_event_name: 'PreToolUse', tool_name: TOOL('run_metric'), tool_use_id: 'toolu_3', tool_input: { metric: 'ventas_netas' } });
  assert.deepEqual(rewritten.updatedInput, { metric: 'ventas_netas', selection_context: 'ctx-1' });
  assert.equal('permissionDecision' in rewritten, false, 'no toca los permisos de la aplicación');
  for (const event of ['PostToolUseFailure', 'PermissionDenied']) {
    const out = runInClaudeCode(b, { hook_event_name: event, tool_name: TOOL('run_metric'), tool_use_id: 'toolu_4', tool_input: { metric: 'm', selection_context: 'ctx-1' }, error: 'falló' });
    assert.ok(out === null || typeof out.additionalContext === 'string', event);
  }
});
