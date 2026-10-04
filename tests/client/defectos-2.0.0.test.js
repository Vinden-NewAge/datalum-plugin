'use strict';
// Los cuatro defectos de cliente encontrados en la 2.0.0, reproducidos tal como se
// reportaron. Contra la 2.0.0 fallan; con la corrección pasan.

const test = require('node:test');
const assert = require('node:assert/strict');
const policy = require('../../client/policy');

const FACTS = {
  citas_humanas: { use_agent: 'user_choice_quote', delete_my_memories: 'user_request_quote', workspace_purge: 'frase' },
  sin_selection_context: ['brain_import', 'list_agents'],
};
const T0 = Date.parse('2026-10-05T10:00:00Z');
const KEYRING = {
  agents: [
    { agentId: 'ag_ventas', name: 'Ventas' },
    { agentId: 'ag_finanzas', name: 'Finanzas' },
    { agentId: 'ag_builder', name: 'Builder' },
  ],
  message: 'Pregunta a la persona con cuál trabajar.',
};
const said = (...texts) => texts.map((text, i) => ({ text, at: new Date(T0 + i * 1000).toISOString(), kind: 'message' }));

function seal(state, id, name, ctx) {
  policy.postToolUse(
    state,
    'use_agent',
    { agent: name, user_choice_quote: 'x' },
    { operating_as: `operando como ${name} v1`, selection_context: ctx || `ctx-${id}`, agent: { id, name, version: 1, herramientasRetiradas: [] }, memory: { text: '' } },
    { now: T0 }
  );
}

test('defecto 1: leer proyecto_b no da por comprobada la escritura incierta de proyecto_a', () => {
  const state = policy.newState('2.0.0');
  seal(state, 'ag_ventas', 'Ventas');
  const write = { kind: 'avance', slug: 'proyecto_a', title: 'Proyecto A · 1 de 3', body_md: '# Pasos\n- [x] Uno — @ana · 2026-10-05' };
  policy.postToolUseFailure(state, 'remember', write, 'MCP error: request timed out', { now: T0 });
  policy.postToolUse(state, 'list_memories', { memory: 'proyecto_b' }, { mode: 'detail', memory_id: 'mem-b', kind: 'avance', title: 'Proyecto B', block: 'otra cosa' }, { now: T0 + 1000 });
  const retry = policy.preToolUse(state, 'remember', write, FACTS, { now: T0 + 2000 });
  assert.notEqual(retry.decision, 'pass');
});

test('defecto 2: citar «No uses el agente Finanzas» no autoriza elegir Finanzas', () => {
  const state = policy.newState('2.0.0');
  policy.postToolUse(state, 'list_agents', {}, KEYRING, { now: T0 });
  const quote = 'No uses el agente Finanzas';
  const verdict = policy.preToolUse(state, 'use_agent', { agent: 'Finanzas', user_choice_quote: quote }, FACTS, { now: T0 + 1000, human: said(quote) });
  assert.notEqual(verdict.decision, 'pass');
});

test('defecto 2: una frase irrelevante no autoriza un borrado', () => {
  const state = policy.newState('2.0.0');
  seal(state, 'ag_ventas', 'Ventas');
  const verdict = policy.preToolUse(state, 'delete_my_memories', { confirm: true, user_request_quote: 'hola' }, FACTS, { now: T0 + 1000, human: said('hola') });
  assert.notEqual(verdict.decision, 'pass');
});

test('defecto 3: el estado no guarda las palabras de la persona', () => {
  const state = policy.newState('2.0.0');
  const quote = 'Usa Ventas, que mi jefa Marta Pérez lo pidió';
  policy.postToolUse(
    state,
    'use_agent',
    { agent: 'Ventas', user_choice_quote: quote },
    { operating_as: 'operando como Ventas v1', selection_context: 'ctx-1', agent: { id: 'ag_ventas', name: 'Ventas', version: 1 }, memory: { text: '' } },
    { now: T0 }
  );
  assert.equal(JSON.stringify(state).includes('Marta'), false);
});

test('defecto 4: los mismos argumentos con otro agente son otra operación', () => {
  const state = policy.newState('2.0.0');
  const write = { kind: 'hecho', slug: 'moneda', title: 'Moneda', body_md: 'Reporta en pesos.' };
  seal(state, 'ag_ventas', 'Ventas');
  policy.postToolUse(state, 'remember', write, { outcome: 'escrita', memory_id: 'mem-1', slug: 'moneda' }, { now: T0 });
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 1000 });
  seal(state, 'ag_finanzas', 'Finanzas');
  const verdict = policy.preToolUse(state, 'remember', write, FACTS, { now: T0 + 2000 });
  assert.equal(verdict.decision, 'pass');
});
