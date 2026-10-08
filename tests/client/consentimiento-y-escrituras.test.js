'use strict';
// Regresiones de la 2.0.1: consentimiento de la persona, resultado de escrituras
// inciertas, identidad de las operaciones por agente y migración del estado.
// Datos inventados con la forma de las respuestas de Datalum.

const test = require('node:test');
const assert = require('node:assert/strict');
const policy = require('../../client/policy');

const FACTS = {
  citas_humanas: { use_agent: 'user_choice_quote', delete_my_memories: 'user_request_quote', workspace_purge: 'frase' },
  sin_selection_context: ['brain_import', 'list_agents'],
};
const T0 = Date.parse('2026-10-05T10:00:00Z');
const iso = (ms) => new Date(ms).toISOString();
const KEYRING = {
  agents: [
    { agentId: 'ag_ventas', name: 'Ventas' },
    { agentId: 'ag_finanzas', name: 'Finanzas' },
  ],
  message: '',
};
const msg = (text, ms) => ({ text, at: iso(ms), kind: 'message' });
const answer = (text, ms) => ({ text, at: iso(ms), kind: 'answer' });

function sealResponse(id, name, ctx, version) {
  return {
    operating_as: `operando como ${name} v${version || 1}`,
    selection_context: ctx || `ctx-${id}`,
    agent: { id, name, version: version || 1, herramientasRetiradas: [] },
    memory: { text: '' },
  };
}

function listed() {
  const state = policy.newState('2.0.1');
  policy.postToolUse(state, 'list_agents', {}, KEYRING, { now: T0, at: iso(T0) });
  return state;
}

// Elegir un agente de punta a punta: lo que decide el cliente antes, y la respuesta de
// Datalum después, con el mismo id de llamada.
function select(state, name, id, ctx) {
  const input = { agent: name, user_choice_quote: name };
  const verdict = policy.preToolUse(state, 'use_agent', input, FACTS, Object.assign({ now: T0 + 1000 }, ctx));
  if (verdict.decision !== 'deny') {
    policy.postToolUse(state, 'use_agent', input, sealResponse(id, name, ctx && ctx.selection), Object.assign({ now: T0 + 2000 }, ctx));
  }
  return verdict;
}

const pre = (state, tool, input, ctx) => policy.preToolUse(state, tool, input, FACTS, Object.assign({ now: T0 + 10000 }, ctx));

// ── Consentimiento para elegir agente ───────────────────────────────────────────
test('elección expresa: lo que la persona eligió en la pregunta de la aplicación', () => {
  const state = listed();
  const verdict = select(state, 'Finanzas', 'ag_finanzas', { human: [answer('Finanzas', T0 + 500)] });
  assert.equal(verdict.decision, 'pass');
  assert.equal(state.authorized.ag_finanzas.via, 'pregunta');
});

test('elección expresa: aprobada por la persona en el diálogo de la aplicación', () => {
  const state = listed();
  const ctx = { human: [msg('trabajemos con finanzas, el de márgenes', T0 + 500)], toolUseId: 'toolu_1', mode: 'default' };
  const verdict = select(state, 'Finanzas', 'ag_finanzas', ctx);
  assert.equal(verdict.decision, 'ask');
  assert.equal(state.authorized.ag_finanzas.via, 'anfitrion');
});

test('la aprobación en modo automático también la ve la persona: el diálogo es forzado', () => {
  const state = listed();
  select(state, 'Finanzas', 'ag_finanzas', { human: [], toolUseId: 'toolu_1', mode: 'auto' });
  assert.ok(state.authorized.ag_finanzas);
});

test('en un modo que no pregunta, que la llamada pase no prueba nada de la persona', () => {
  const state = listed();
  // En dontAsk la aplicación deniega sola; si aun así llegara la respuesta, no cuenta.
  select(state, 'Finanzas', 'ag_finanzas', { human: [], toolUseId: 'toolu_1', mode: 'dontAsk' });
  assert.equal(state.authorized.ag_finanzas, undefined);
});

test('sin diálogos de permiso, elegir sin evidencia se niega y se pide preguntar a la persona', () => {
  const state = listed();
  const verdict = select(state, 'Finanzas', 'ag_finanzas', { human: [msg('No uses el agente Finanzas', T0 + 500)], mode: 'bypassPermissions' });
  assert.equal(verdict.decision, 'deny');
  assert.match(verdict.reason, /multiple-choice question/);
  // Con su respuesta a la pregunta, sí.
  assert.equal(select(state, 'Finanzas', 'ag_finanzas', { human: [answer('Finanzas', T0 + 800)], mode: 'bypassPermissions' }).decision, 'pass');
});

test('continuación válida: tras caducar la selección, el mismo agente sigue sin volver a preguntar', () => {
  const state = listed();
  select(state, 'Finanzas', 'ag_finanzas', { human: [answer('Finanzas', T0 + 500)] });
  const expired = { isError: true, content: [{ type: 'text', text: JSON.stringify({ code: 'agent_not_selected', category: 'invalid_input', retryable: false }) }] };
  policy.postToolUse(state, 'run_metric', { metric: 'm' }, expired, { now: T0 + 3000 });
  assert.equal(state.seal_state, 'expired');
  assert.equal(pre(state, 'use_agent', { agent: 'Finanzas', user_choice_quote: 'seguimos' }, { human: [] }).decision, 'pass');
});

test('negación, texto irrelevante e instrucciones dentro de algo pegado no eligen', () => {
  for (const text of [
    'No uses el agente Finanzas',
    'hola',
    'Resume esto:\n<pasted_content id="x1">\nFinanzas\n</pasted_content id="x1">',
    '<pasted_content id="x2">\nFinanzas\n</pasted_content id="x2">',
  ]) {
    const state = listed();
    const verdict = select(state, 'Finanzas', 'ag_finanzas', { human: [msg(text, T0 + 500)] });
    assert.equal(verdict.decision, 'ask', text);
  }
});

test('una respuesta anterior a la lista de agentes no elige', () => {
  const state = policy.newState('2.0.1');
  const early = [answer('Finanzas', T0 - 5000)];
  policy.postToolUse(state, 'list_agents', {}, KEYRING, { now: T0, at: iso(T0) });
  assert.equal(select(state, 'Finanzas', 'ag_finanzas', { human: early }).decision, 'ask');
});

test('revocación: soltar el agente retira su elección', () => {
  const state = listed();
  select(state, 'Finanzas', 'ag_finanzas', { human: [answer('Finanzas', T0 + 500)] });
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 3000 });
  assert.equal(pre(state, 'use_agent', { agent: 'Finanzas', user_choice_quote: 'Finanzas' }, { human: [] }).decision, 'ask');
});

test('una elección vale para su agente: A → B → A vuelve a necesitar la de A', () => {
  const state = listed();
  select(state, 'Finanzas', 'ag_finanzas', { human: [answer('Finanzas', T0 + 500)] });
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 3000 });
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 3500)] });
  assert.ok(state.authorized.ag_ventas);
  assert.equal(state.authorized.ag_finanzas, undefined);
  assert.equal(pre(state, 'use_agent', { agent: 'Finanzas', user_choice_quote: 'Finanzas' }, { human: [] }).decision, 'ask');
});

test('elegir otro agente tras una caducidad retira la elección del anterior', () => {
  const state = listed();
  select(state, 'Finanzas', 'ag_finanzas', { human: [answer('Finanzas', T0 + 500)] });
  const expired = { isError: true, content: [{ type: 'text', text: JSON.stringify({ code: 'agent_not_selected', category: 'invalid_input', retryable: false }) }] };
  policy.postToolUse(state, 'run_metric', { metric: 'm' }, expired, { now: T0 + 3000 });
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 3500)] });
  assert.equal(state.authorized.ag_finanzas, undefined);
  assert.equal(pre(state, 'use_agent', { agent: 'Finanzas', user_choice_quote: 'Finanzas' }, { human: [] }).decision, 'ask');
});

test('si la aplicación deniega la llamada, la elección no queda registrada', () => {
  const state = listed();
  const input = { agent: 'Finanzas', user_choice_quote: 'Finanzas' };
  policy.preToolUse(state, 'use_agent', input, FACTS, { now: T0 + 1000, human: [], toolUseId: 'toolu_9', mode: 'auto' });
  policy.permissionDenied(state, 'use_agent', input, { now: T0 + 1500, toolUseId: 'toolu_9' });
  assert.deepEqual(state.pending, {});
  assert.equal(state.authorized.ag_finanzas, undefined);
});

// ── Borrados ────────────────────────────────────────────────────────────────────
test('borrado no autorizado: se le pregunta a la persona; sin diálogos, se niega', () => {
  const state = listed();
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 500)] });
  const input = { confirm: true, user_request_quote: 'hola' };
  assert.equal(pre(state, 'delete_my_memories', input, { mode: 'default' }).decision, 'ask');
  assert.equal(pre(state, 'delete_my_memories', input, { mode: 'bypassPermissions' }).decision, 'deny');
});

test('borrado autorizado: si falla por un límite, el reintento de esa misma operación no vuelve a preguntar', () => {
  const state = listed();
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 500)] });
  const input = { confirm: true, user_request_quote: 'borra todo lo que sabes de mí' };
  const ctx = { toolUseId: 'toolu_borrar', mode: 'default' };
  assert.equal(pre(state, 'delete_my_memories', input, ctx).decision, 'ask');
  const limited = JSON.stringify({ code: 'rate_limited', category: 'quota', retryable: true, retry_after: 3 });
  policy.postToolUseFailure(state, 'delete_my_memories', input, limited, { now: T0 + 11000, toolUseId: 'toolu_borrar' }, FACTS);
  assert.equal(pre(state, 'delete_my_memories', input, { now: T0 + 20000 }).decision, 'pass');
  // Otra operación de borrado no hereda esa aprobación.
  assert.equal(pre(state, 'workspace_purge', { frase: 'sí' }, { now: T0 + 20000, mode: 'default' }).decision, 'ask');
  // Y la aprobación caduca: pasado un rato, se vuelve a preguntar.
  assert.equal(pre(state, 'delete_my_memories', input, { now: T0 + 11000 + 16 * 60000, mode: 'default' }).decision, 'ask');
});

// ── Resultado de escrituras inciertas ───────────────────────────────────────────
const AVANCE = { kind: 'avance', slug: 'proyecto_a', title: 'Proyecto A · 2 de 3', body_md: '# Pasos\n- [x] Uno — @ana · 2026-10-05\n- [x] Dos — @ana · 2026-10-05\n- [ ] Tres' };
const TIMEOUT = 'MCP error -32001: Request timed out';
const missing = () => ({ isError: true, content: [{ type: 'text', text: JSON.stringify({ code: 'not_found', category: 'not_found', retryable: false }) }] });
const detail = (id, title, block, extra) => Object.assign({ mode: 'detail', memory_id: id, kind: 'avance', scope: 'personal', state: 'viva', title, block }, extra || {});

function withUncertain(prior) {
  const state = listed();
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 500)] });
  if (prior) policy.postToolUse(state, 'list_memories', { memory: 'proyecto_a' }, detail(prior, 'Proyecto A · 1 de 3', 'antes'), { now: T0 + 3000 });
  policy.postToolUseFailure(state, 'remember', AVANCE, TIMEOUT, { now: T0 + 4000 }, FACTS);
  return state;
}

test('la lectura confirma que se aplicó: se reconoce el éxito y no se repite', () => {
  const state = withUncertain('mem-1');
  const block = `# Proyecto A · 2 de 3\n\n${AVANCE.body_md}\n`;
  policy.postToolUse(state, 'list_memories', { memory: 'proyecto_a' }, detail('mem-2', AVANCE.title, block), { now: T0 + 5000 });
  const verdict = pre(state, 'remember', AVANCE, {});
  assert.equal(verdict.decision, 'deny');
  assert.match(verdict.reason, /already confirmed/);
});

test('la lectura demuestra que no se aplicó: un reintento, y sólo uno', () => {
  const state = withUncertain('mem-1');
  policy.postToolUse(state, 'list_memories', { memory: 'proyecto_a' }, detail('mem-1', 'Proyecto A · 1 de 3', 'antes'), { now: T0 + 5000 });
  assert.equal(pre(state, 'remember', AVANCE, {}).decision, 'pass');
  const second = pre(state, 'remember', AVANCE, { now: T0 + 11000 });
  assert.equal(second.decision, 'deny', 'mientras corre el reintento no se lanza otro');
  assert.match(second.reason, /already under way/);
});

test('si la memoria no existe, no se aplicó', () => {
  const state = withUncertain(null);
  policy.postToolUse(state, 'list_memories', { memory: 'proyecto_a' }, missing(), { now: T0 + 5000 });
  assert.equal(pre(state, 'remember', AVANCE, {}).decision, 'pass');
});

test('evidencia insuficiente: cortada, fallida o con otro contenido y otro id deja el resultado incierto', () => {
  const full = `# Proyecto A · 2 de 3\n\n${AVANCE.body_md}\n`;
  const cases = [
    // Cortada, aunque lo servido coincida con lo escrito.
    (s) => policy.postToolUse(s, 'list_memories', { memory: 'proyecto_a' }, detail('mem-2', AVANCE.title, full, { truncated: true }), { now: T0 + 5000 }),
    (s) => policy.postToolUse(s, 'list_memories', { memory: 'proyecto_a' }, detail('mem-2', AVANCE.title, full, { next_cursor: 'c2' }), { now: T0 + 5000 }),
    // Mismo título, otro cuerpo y otro id: alguien escribió algo, no se sabe qué.
    (s) => policy.postToolUse(s, 'list_memories', { memory: 'proyecto_a' }, detail('mem-2', AVANCE.title, 'otro cuerpo'), { now: T0 + 5000 }),
    (s) => policy.postToolUseFailure(s, 'list_memories', { memory: 'proyecto_a' }, TIMEOUT, { now: T0 + 5000 }, FACTS),
    (s) => policy.postToolUse(s, 'list_memories', { memory: 'proyecto_a' }, detail('mem-9', 'Otra cosa', 'otro cuerpo'), { now: T0 + 5000 }),
  ];
  for (const read of cases) {
    const state = withUncertain('mem-1');
    read(state);
    const verdict = pre(state, 'remember', AVANCE, { mode: 'default' });
    assert.equal(verdict.decision, 'ask', 'decide la persona');
    assert.match(verdict.reason, /duplicarlo/);
  }
});

test('una lectura anterior a la escritura no la resuelve', () => {
  const state = listed();
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 500)] });
  policy.postToolUseFailure(state, 'remember', AVANCE, TIMEOUT, { now: T0 + 9000 }, FACTS);
  policy.postToolUse(state, 'list_memories', { memory: 'proyecto_a' }, missing(), { now: T0 + 8000 });
  assert.equal(pre(state, 'remember', AVANCE, {}).decision, 'deny');
});

test('leer el índice no es comprobar el resultado', () => {
  const state = withUncertain('mem-1');
  policy.postToolUse(state, 'list_memories', {}, { mode: 'index', block: '- avance · Proyecto A · 2 de 3', total: 1 }, { now: T0 + 5000 });
  assert.equal(pre(state, 'remember', AVANCE, {}).decision, 'deny');
});

test('la memoria leída por su ruta en el cerebro también sirve de evidencia', () => {
  const state = withUncertain(null);
  const body = { concept_id: 'agents/ventas/memoria/proyecto_a', frontmatter: { title: AVANCE.title }, body: AVANCE.body_md };
  policy.postToolUse(state, 'brain_read', { concept_id: 'agents/ventas/memoria/proyecto_a' }, body, { now: T0 + 5000 });
  assert.equal(pre(state, 'remember', AVANCE, {}).decision, 'deny');
});

test('una lectura de otro agente no resuelve la escritura incierta de este', () => {
  const state = withUncertain('mem-1');
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 5000 });
  select(state, 'Finanzas', 'ag_finanzas', { human: [answer('Finanzas', T0 + 5500)] });
  // Finanzas lee una memoria con el mismo nombre: es la suya, no la de Ventas.
  policy.postToolUse(state, 'list_memories', { memory: 'proyecto_a' }, missing(), { now: T0 + 6000 });
  assert.equal(pre(state, 'remember', AVANCE, {}).decision, 'pass', 'Finanzas escribe su propia memoria');
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 7000 });
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 7500)] });
  assert.equal(pre(state, 'remember', AVANCE, { now: T0 + 12000 }).decision, 'deny', 'la de Ventas sigue incierta');
});

// ── Identidad de las operaciones ────────────────────────────────────────────────
const HECHO = { kind: 'hecho', slug: 'moneda', title: 'Moneda', body_md: 'Reporta en pesos.' };
const RECIBO = { outcome: 'escrita', memory_id: 'mem-7', slug: 'moneda' };

test('la misma operación confirmada en el mismo agente es un duplicado', () => {
  const state = listed();
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 500)] });
  policy.postToolUse(state, 'remember', HECHO, RECIBO, { now: T0 + 3000 }, FACTS);
  assert.equal(pre(state, 'remember', HECHO, {}).decision, 'deny');
});

test('renovar el contexto del mismo agente conserva la protección', () => {
  const state = listed();
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 500)], selection: 'ctx-1' });
  policy.postToolUse(state, 'remember', HECHO, RECIBO, { now: T0 + 3000 }, FACTS);
  const expired = { isError: true, content: [{ type: 'text', text: JSON.stringify({ code: 'agent_not_selected', category: 'invalid_input', retryable: false }) }] };
  policy.postToolUse(state, 'run_metric', { metric: 'm' }, expired, { now: T0 + 4000 });
  select(state, 'Ventas', 'ag_ventas', { human: [], selection: 'ctx-2' });
  assert.equal(state.seal.selection_context, 'ctx-2');
  assert.equal(pre(state, 'remember', HECHO, {}).decision, 'deny');
});

test('A → B → A: cada agente conserva su propio historial', () => {
  const state = listed();
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 500)] });
  policy.postToolUse(state, 'remember', HECHO, RECIBO, { now: T0 + 3000 }, FACTS);
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 4000 });
  select(state, 'Finanzas', 'ag_finanzas', { human: [answer('Finanzas', T0 + 4500)] });
  assert.equal(pre(state, 'remember', HECHO, {}).decision, 'pass', 'B no hereda el historial de A');
  policy.postToolUse(state, 'remember', HECHO, Object.assign({}, RECIBO, { memory_id: 'mem-8' }), { now: T0 + 6000 }, FACTS);
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 7000 });
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 7500)] });
  assert.equal(pre(state, 'remember', HECHO, { now: T0 + 12000 }).decision, 'deny', 'A conserva el suyo');
});

test('ámbitos distintos son operaciones distintas', () => {
  const state = listed();
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 500)] });
  const metric = (connector) => ({ connector, name: 'margen', sql: 'sum(m)' });
  policy.postToolUse(state, 'propose_metric', metric('norte'), { preview: true }, { now: T0 + 3000 }, FACTS);
  policy.postToolUse(state, 'propose_metric', Object.assign({ confirm: true }, metric('norte')), { status: 'propuesto' }, { now: T0 + 4000 }, FACTS);
  assert.equal(pre(state, 'propose_metric', Object.assign({ confirm: true }, metric('norte')), {}).decision, 'deny');
  policy.postToolUse(state, 'propose_metric', metric('sur'), { preview: true }, { now: T0 + 5000 }, FACTS);
  assert.equal(pre(state, 'propose_metric', Object.assign({ confirm: true }, metric('sur')), {}).decision, 'pass');
});

test('un cambio incierto en un objeto no frena otro objeto de la misma herramienta', () => {
  const state = listed();
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 500)] });
  const metric = (name) => ({ connector: 'norte', name, sql: 'sum(m)' });
  policy.postToolUse(state, 'propose_metric', metric('margen'), { preview: true }, { now: T0 + 3000 }, FACTS);
  policy.postToolUseFailure(state, 'propose_metric', Object.assign({ confirm: true }, metric('margen')), TIMEOUT, { now: T0 + 4000 }, FACTS);
  policy.postToolUse(state, 'propose_metric', metric('ventas'), { preview: true }, { now: T0 + 5000 }, FACTS);
  assert.equal(pre(state, 'propose_metric', Object.assign({ confirm: true }, metric('ventas')), { mode: 'default' }).decision, 'pass');
  assert.equal(pre(state, 'propose_metric', Object.assign({ confirm: true }, metric('margen')), { mode: 'default' }).decision, 'ask');
});

// Datalum R12 nombra el conector `connector`; el servidor publicado antes de R12, `tenant`.
// El cliente lee los dos, y el ámbito de un cambio es su conector con cualquiera de ellos.
function uncertainOnNorte(arg) {
  const state = listed();
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 500)] });
  const metric = (connector) => ({ [arg]: connector, name: 'margen', sql: 'sum(m)' });
  policy.postToolUse(state, 'propose_metric', metric('norte'), { preview: true }, { now: T0 + 3000 }, FACTS);
  policy.postToolUseFailure(state, 'propose_metric', Object.assign({ confirm: true }, metric('norte')), TIMEOUT, { now: T0 + 4000 }, FACTS);
  return state;
}

test('el ámbito de un cambio es su conector, nombrado `connector` como en R12', () => {
  const state = uncertainOnNorte('connector');
  const metric = (connector) => ({ connector, name: 'margen', sql: 'sum(m)' });
  policy.postToolUse(state, 'propose_metric', metric('sur'), { preview: true }, { now: T0 + 5000 }, FACTS);
  assert.equal(pre(state, 'propose_metric', Object.assign({ confirm: true }, metric('sur')), { mode: 'default' }).decision, 'pass', 'otro conector es otro cambio');
  assert.equal(pre(state, 'propose_metric', Object.assign({ confirm: true }, metric('norte')), { mode: 'default' }).decision, 'ask', 'el mismo conector espera a la persona');
});

test('el ámbito de un cambio es su conector, nombrado `tenant` como antes de R12, y sigue siéndolo con `connector`', () => {
  const state = uncertainOnNorte('tenant');
  const before = (tenant) => ({ tenant, name: 'margen', sql: 'sum(m)' });
  policy.postToolUse(state, 'propose_metric', before('sur'), { preview: true }, { now: T0 + 5000 }, FACTS);
  assert.equal(pre(state, 'propose_metric', Object.assign({ confirm: true }, before('sur')), { mode: 'default' }).decision, 'pass', 'otro conector es otro cambio');
  assert.equal(pre(state, 'propose_metric', Object.assign({ confirm: true }, before('norte')), { mode: 'default' }).decision, 'ask', 'el mismo conector espera a la persona');
  // El servidor pasa a R12 a mitad de la conversación: el cambio incierto sigue siendo el mismo.
  const after = { connector: 'norte', name: 'margen', sql: 'sum(m)' };
  policy.postToolUse(state, 'propose_metric', after, { preview: true }, { now: T0 + 6000 }, FACTS);
  assert.equal(pre(state, 'propose_metric', Object.assign({ confirm: true }, after), { mode: 'default' }).decision, 'ask', 'con el nombre de R12 tampoco se repite a ciegas');
});

test('una vista previa de un agente no autoriza aplicar con otro', () => {
  const state = listed();
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 500)] });
  const metric = { connector: 'norte', name: 'margen', sql: 'sum(m)' };
  policy.postToolUse(state, 'propose_metric', metric, { preview: true }, { now: T0 + 3000 }, FACTS);
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 4000 });
  select(state, 'Finanzas', 'ag_finanzas', { human: [answer('Finanzas', T0 + 4500)] });
  assert.equal(pre(state, 'propose_metric', Object.assign({ confirm: true }, metric), {}).decision, 'deny');
});

// ── Lo que guarda el estado ─────────────────────────────────────────────────────
test('el estado no guarda las palabras de la persona ni el texto de lo escrito', () => {
  const state = listed();
  const secret = 'Usa Ventas porque Marta Pérez lo pidió';
  policy.preToolUse(state, 'use_agent', { agent: 'Ventas', user_choice_quote: secret }, FACTS, { now: T0 + 1000, human: [msg(secret, T0 + 500)], toolUseId: 'toolu_1', mode: 'default' });
  policy.postToolUse(state, 'use_agent', { agent: 'Ventas', user_choice_quote: secret }, sealResponse('ag_ventas', 'Ventas'), { now: T0 + 2000, toolUseId: 'toolu_1' }, FACTS);
  const write = { kind: 'hecho', slug: 'cliente_estrella', title: 'Contrato con Acme Pérez', body_md: 'Firmó el 3 de octubre por 1,2 millones.' };
  policy.postToolUseFailure(state, 'remember', write, TIMEOUT, { now: T0 + 3000 }, FACTS);
  policy.postToolUse(state, 'remember', Object.assign({}, write, { slug: 'pedido_de_acme' }), { outcome: 'escrita', memory_id: 'mem-1', slug: 'pedido_de_acme' }, { now: T0 + 4000 }, FACTS);
  const saved = JSON.stringify(state).toLowerCase();
  for (const fragment of ['marta', 'pérez', 'perez', 'acme', 'millones', 'cliente_estrella', 'firmó']) {
    assert.equal(saved.includes(fragment), false, fragment);
  }
});

test('un estado de la 2.0.0 se migra sin la frase y sin perder lo pendiente', () => {
  const v1 = {
    v: 1,
    plugin_version: '2.0.0',
    server: 'plugin_datalum_datalum',
    seal: { agent_id: 'ag_ventas', agent_name: 'Ventas', version: 3, selection_context: 'ctx-1', quote: 'usa ventas, lo pidió Marta', sealed_at: iso(T0) },
    seal_state: 'sealed',
    newer_version: null,
    retired: ['run_query'],
    keyring: [{ id: 'ag_ventas', name: 'Ventas' }],
    reads: { 'agents/ventas/reglas': { complete: true, next_offset: null } },
    listings: {},
    previews: {},
    writes: {},
    failures: {},
  };
  // La llave de la 2.0.0 de una escritura confirmada.
  const crypto = require('crypto');
  const stable = (v) => (Array.isArray(v) ? '[' + v.map(stable).join(',') + ']' : v && typeof v === 'object' ? '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + stable(v[k])).join(',') + '}' : JSON.stringify(v));
  const oldKey = 'remember:' + crypto.createHash('sha256').update(stable(HECHO)).digest('hex').slice(0, 24);
  v1.writes[oldKey] = { status: 'confirmed', at: T0, tool: 'remember', name: 'moneda', proposed: false };

  const state = policy.migrate(v1, '2.0.1');
  assert.equal(state.v, policy.STATE_VERSION);
  assert.equal(JSON.stringify(state).includes('Marta'), false);
  assert.equal(state.seal.agent_id, 'ag_ventas');
  assert.equal(state.seal.selection_context, 'ctx-1');
  assert.deepEqual(state.retired, ['run_query']);
  assert.ok(state.reads['agents/ventas/reglas']);
  assert.ok(state.authorized.ag_ventas, 'la conversación sigue con su agente');
  // La escritura confirmada sigue bloqueando el duplicado para ese agente…
  assert.equal(policy.preToolUse(state, 'remember', HECHO, FACTS, { now: T0 + 1000 }).decision, 'deny');
  // …y no para otro.
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 2000 });
  policy.postToolUse(state, 'list_agents', {}, KEYRING, { now: T0 + 2500, at: iso(T0 + 2500) });
  select(state, 'Finanzas', 'ag_finanzas', { human: [answer('Finanzas', T0 + 3000)] });
  assert.equal(policy.preToolUse(state, 'remember', HECHO, FACTS, { now: T0 + 4000 }).decision, 'pass');
  // Migrar dos veces no cambia nada.
  assert.equal(policy.migrate(state, '2.0.1'), state);
});

// ── Arreglos de la revisión de código de la 2.0.1 ───────────────────────────────
test('proponer un agente por brain_write no se repite ni a ciegas', () => {
  const state = listed();
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 500)] });
  const propose = { concept_id: 'agents/analista/agente', title: 'Analista', documents: [{ kind: 'persona', title: 'Quién es', body_md: 'x' }] };
  policy.postToolUse(state, 'brain_write', propose, { written: 'agent', concept_id: 'agents/analista/agente' }, { now: T0 + 3000 }, FACTS);
  assert.equal(pre(state, 'brain_write', propose, {}).decision, 'deny');
  const other = Object.assign({}, propose, { concept_id: 'agents/auditor/agente', title: 'Auditor' });
  policy.postToolUseFailure(state, 'brain_write', other, TIMEOUT, { now: T0 + 4000 }, FACTS);
  assert.equal(pre(state, 'brain_write', other, { mode: 'default' }).decision, 'ask');
});

test('una memoria compartida servida con el mismo nombre no resuelve una escritura personal', () => {
  const state = listed();
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 500)] });
  // Aunque traiga el mismo título y el mismo cuerpo: es otra memoria.
  const shared = detail('mem-s', AVANCE.title, AVANCE.body_md, { scope: 'compartida' });
  policy.postToolUse(state, 'list_memories', { memory: 'proyecto_a' }, shared, { now: T0 + 3000 });
  policy.postToolUseFailure(state, 'remember', AVANCE, TIMEOUT, { now: T0 + 4000 }, FACTS);
  policy.postToolUse(state, 'list_memories', { memory: 'proyecto_a' }, shared, { now: T0 + 5000 });
  assert.equal(pre(state, 'remember', AVANCE, { mode: 'default' }).decision, 'ask', 'sigue incierta y decide la persona');
});

test('aprobada la repetición de una escritura migrada que falló, no se vuelve a preguntar', () => {
  const crypto = require('crypto');
  const stable = (v) => (Array.isArray(v) ? '[' + v.map(stable).join(',') + ']' : v && typeof v === 'object' ? '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + stable(v[k])).join(',') + '}' : JSON.stringify(v));
  const oldKey = 'remember:' + crypto.createHash('sha256').update(stable(HECHO)).digest('hex').slice(0, 24);
  const state = policy.migrate({
    v: 1, seal: { agent_id: 'ag_ventas', agent_name: 'Ventas', version: 1, selection_context: 'ctx-1', quote: 'x', sealed_at: iso(T0) },
    seal_state: 'sealed', retired: [], reads: {}, listings: {}, previews: {}, failures: {},
    writes: { [oldKey]: { status: 'uncertain', at: T0, tool: 'remember' } },
  }, '2.0.1');
  const ctx = { toolUseId: 'toolu_r', mode: 'default', now: T0 + 1000 };
  assert.equal(policy.preToolUse(state, 'remember', HECHO, FACTS, ctx).decision, 'ask');
  policy.postToolUseFailure(state, 'remember', HECHO, JSON.stringify({ code: 'rate_limited', category: 'quota', retry_after: 2 }), { now: T0 + 2000, toolUseId: 'toolu_r' }, FACTS);
  assert.equal(policy.preToolUse(state, 'remember', HECHO, FACTS, { now: T0 + 5000 }).decision, 'pass');
});

test('sin diálogos no queda nada pendiente de una pregunta que nadie vio', () => {
  const state = listed();
  select(state, 'Ventas', 'ag_ventas', { human: [answer('Ventas', T0 + 500)] });
  pre(state, 'delete_my_memories', { confirm: true, user_request_quote: 'x' }, { mode: 'bypassPermissions', toolUseId: 'toolu_b' });
  pre(state, 'use_agent', { agent: 'Finanzas', user_choice_quote: 'x' }, { mode: 'bypassPermissions', toolUseId: 'toolu_c', human: [] });
  assert.deepEqual(state.pending, {});
});
