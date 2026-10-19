'use strict';
// La 4.0.0 y Datalum v2.256.0: toda escritura lleva la orden de la persona en
// `user_request_quote`, también la memoria y soltar el agente, y las gráficas y los
// tableros salen de la pausa. Se prueba con los hechos que el plugin deriva del contrato
// de producción (client/contract-facts.json). Datos inventados.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const policy = require('../../client/policy');

const FACTS = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'client', 'contract-facts.json'), 'utf8'));
const T0 = Date.parse('2026-10-19T10:00:00Z');
const iso = (ms) => new Date(ms).toISOString();
const answer = (text, ms) => ({ text, at: iso(ms), kind: 'answer' });

function sealed() {
  const state = policy.newState('4.0.0');
  policy.postToolUse(state, 'list_agents', {}, { agents: [{ agentId: 'ag_1', name: 'Ventas' }, { agentId: 'ag_2', name: 'Compras' }], message: '' }, { now: T0, at: iso(T0) }, FACTS);
  const input = { agent: 'Ventas', user_choice_quote: 'Ventas' };
  const verdict = policy.preToolUse(state, 'use_agent', input, FACTS, { now: T0 + 1000, human: [answer('Ventas', T0 + 500)] });
  assert.equal(verdict.decision, 'pass');
  const seal = {
    operating_as: 'operando como Ventas v2',
    selection_context: 'ctx-1',
    agent: { id: 'ag_1', name: 'Ventas', version: 2, herramientasRetiradas: [] },
    memory: { text: '' },
  };
  policy.postToolUse(state, 'use_agent', input, seal, { now: T0 + 2000 }, FACTS);
  return state;
}

const pre = (state, tool, input, ms) => policy.preToolUse(state, tool, input, FACTS, { now: T0 + (ms || 10000) });
const AVANCE = { kind: 'avance', slug: 'cierre_de_mes', title: 'Cierre de mes', body_md: 'Falta conciliar dos cuentas.' };
const RECIBO = { outcome: 'escrita', memory_id: 'mem-1', slug: 'cierre_de_mes' };

// El rechazo con la forma que sirve Datalum v2.256.0: el mensaje, el sobre como texto y el
// sobre como dato.
function sinLaOrden(tool) {
  const sobre = {
    code: 'user_request_quote_required',
    category: 'invalid_input',
    message: `${tool} escribe en Datalum y la llamada no trae la orden de la persona · pregúntale, y vuelve a llamar con sus palabras textuales en user_request_quote.`,
    retryable: false,
  };
  return { isError: true, content: [{ type: 'text', text: sobre.message }, { type: 'text', text: JSON.stringify(sobre) }], structuredContent: sobre };
}

test('los hechos del contrato vigente tratan la orden de la persona como cita', () => {
  for (const tool of ['remember', 'forget', 'release_agent', 'workspace_purge', 'delete_my_memories']) {
    assert.equal(FACTS.citas_humanas[tool], 'user_request_quote', tool);
  }
  assert.equal(Object.values(FACTS.destinos).includes('user_request_quote'), false);
});

test('la orden de la persona no forma parte de una escritura: la misma con otras palabras no se repite y otra sí pasa', () => {
  const state = sealed();
  const first = Object.assign({ user_request_quote: 'guarda el avance' }, AVANCE);
  assert.equal(pre(state, 'remember', first).decision, 'pass');
  policy.postToolUse(state, 'remember', first, RECIBO, { now: T0 + 11000 }, FACTS);
  const again = Object.assign({}, first, { user_request_quote: 'sí, guárdalo otra vez' });
  assert.equal(pre(state, 'remember', again, 12000).decision, 'deny', 'la misma escritura con otras palabras');
  const other = Object.assign({}, again, { body_md: 'Ya se conciliaron las dos cuentas.' });
  assert.equal(pre(state, 'remember', other, 13000).decision, 'pass', 'otro contenido es otra escritura');
});

test('un rechazo por falta de la orden no deja la escritura incierta: la misma con la orden pasa', () => {
  const state = sealed();
  assert.equal(pre(state, 'remember', AVANCE).decision, 'pass');
  policy.postToolUse(state, 'remember', AVANCE, sinLaOrden('remember'), { now: T0 + 11000 }, FACTS);
  const withQuote = Object.assign({ user_request_quote: 'guarda el avance' }, AVANCE);
  assert.equal(pre(state, 'remember', withQuote, 12000).decision, 'pass');
  policy.postToolUse(state, 'forget', { memory: 'cierre_de_mes' }, sinLaOrden('forget'), { now: T0 + 13000 }, FACTS);
  assert.equal(pre(state, 'forget', { memory: 'cierre_de_mes', user_request_quote: 'olvida el cierre' }, 14000).decision, 'pass');
});

test('soltar el agente con la orden de la persona lo suelta y retira la elección', () => {
  const state = sealed();
  const input = { user_request_quote: 'cambia de agente' };
  const verdict = pre(state, 'release_agent', input);
  assert.notEqual(verdict.decision, 'deny');
  assert.equal(verdict.input.selection_context, 'ctx-1', 'sale con el contexto de esta conversación');
  assert.equal(verdict.input.user_request_quote, 'cambia de agente', 'y con la orden tal cual');
  policy.postToolUse(state, 'release_agent', verdict.input, { released: true }, { now: T0 + 11000 }, FACTS);
  assert.equal(state.seal, null);
  assert.deepEqual(state.authorized, {});
});

test('el estado no guarda la orden de la persona', () => {
  const state = sealed();
  const quote = 'Guárdalo, lo pidió la directora de Contraloría';
  const write = Object.assign({ user_request_quote: quote }, AVANCE);
  pre(state, 'remember', write);
  policy.postToolUse(state, 'remember', write, RECIBO, { now: T0 + 11000 }, FACTS);
  pre(state, 'release_agent', { user_request_quote: quote }, 12000);
  const saved = JSON.stringify(state).toLowerCase();
  for (const fragment of ['directora', 'contraloría', 'contraloria', 'guárdalo']) {
    assert.equal(saved.includes(fragment), false, fragment);
  }
});

test('las gráficas y los tableros ya no se niegan: pasan por las mismas reglas que lo demás', () => {
  const state = sealed();
  const chart = { connector: 'principal', chart: 'ventas_por_mes' };
  assert.equal(pre(state, 'render_chart', chart).decision, 'pass');
  const dashboard = { connector: 'principal', name: 'tablero_comercial', spec: { tiles: [] }, user_request_quote: 'arma el tablero' };
  const apply = Object.assign({ confirm: true }, dashboard);
  const denied = pre(state, 'upsert_dashboard', apply);
  assert.equal(denied.decision, 'deny', 'aplicar sin vista previa se niega como en cualquier herramienta');
  assert.match(denied.reason, /preview first/);
  policy.postToolUse(state, 'upsert_dashboard', dashboard, { preview: true }, { now: T0 + 11000 }, FACTS);
  assert.equal(pre(state, 'upsert_dashboard', apply, 12000).decision, 'pass');
});
