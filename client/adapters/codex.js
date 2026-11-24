#!/usr/bin/env node
'use strict';
// Adaptador de los controles del cliente al formato de hooks de Codex (CLI y escritorio).
//
// La política es la misma que en Claude Code. Cambia lo que Codex admite en la respuesta
// de un PreToolUse (codex-rs/hooks, output_parser.rs):
// - No hay «preguntar»: Codex marca el hook como fallido y la llamada sigue sin el
//   control. Por eso aquí la aplicación no tiene diálogos y la política niega con el
//   motivo para el modelo, como en un modo sin permisos.
// - `updatedInput` sólo vale junto a `permissionDecision: "allow"`. En Codex eso sólo
//   reescribe la llamada; en Claude Code la aprobaría sin preguntar. Este adaptador
//   nunca manda «allow»: si la llamada tiene que salir con otros argumentos, la niega y
//   le dice al modelo con cuáles repetirla. Así, aunque una aplicación se confunda con
//   otra, ninguna respuesta de este archivo aprueba una llamada.
// PostToolUseFailure y PermissionDenied no existen en Codex.

const claudeCode = require('./claude-code');

const CODEX = { dialogs: false };

function handle(event) {
  const output = claudeCode.handle(event, CODEX);
  if (!output || !output.hookSpecificOutput || output.hookSpecificOutput.hookEventName !== 'PreToolUse') return output;
  const specific = Object.assign({}, output.hookSpecificOutput);
  if (specific.permissionDecision === 'ask') {
    // La política no pregunta sin diálogos; si alguna vez lo hiciera, nadie lo vería.
    specific.permissionDecision = 'deny';
    specific.permissionDecisionReason =
      'This step needs the confirmation of the person, and this app cannot ask for it from here. Do not run it. ' +
      'Tell the person, in plain words, that it needs their confirmation in an app that asks for it.';
  }
  if (specific.updatedInput !== undefined) {
    const changes = describeChanges((event && event.tool_input) || {}, specific.updatedInput);
    delete specific.updatedInput;
    if (specific.permissionDecision !== 'deny') {
      specific.permissionDecision = 'deny';
      specific.permissionDecisionReason =
        'This call has to go out with the context of this conversation, and this app cannot change its arguments from ' +
        `here. Make the same call again with the same arguments, ${changes}.`;
    }
  }
  return { hookSpecificOutput: specific };
}

// Sólo los argumentos que cambian, para que el modelo no repita textos largos.
function describeChanges(before, after) {
  const parts = [];
  for (const key of Object.keys(after)) {
    if (JSON.stringify(before[key]) !== JSON.stringify(after[key])) parts.push(`with \`${key}\` set to ${JSON.stringify(after[key])}`);
  }
  for (const key of Object.keys(before)) {
    if (!(key in after)) parts.push(`without \`${key}\``);
  }
  return parts.join(' and ') || 'unchanged';
}

module.exports = { handle };

if (require.main === module) require('./hook').run(module.exports);
