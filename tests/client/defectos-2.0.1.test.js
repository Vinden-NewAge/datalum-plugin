'use strict';
// Defectos de la 2.0.1 encontrados en la auditoría, reproducidos tal como se
// reportaron. Contra la 2.0.1 fallan; con la corrección pasan.

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('crypto');
const policy = require('../../client/policy');

const FACTS = {
  citas_humanas: { use_agent: 'user_choice_quote', delete_my_memories: 'user_request_quote', workspace_purge: 'frase' },
  sin_selection_context: ['brain_import', 'list_agents'],
};
const T0 = Date.parse('2026-10-05T10:00:00Z');
const iso = (ms) => new Date(ms).toISOString();
const KEYRING = { agents: [{ agentId: 'ag_ventas', name: 'Ventas' }, { agentId: 'ag_finanzas', name: 'Finanzas' }], message: '' };
const answer = (text, ms) => ({ text, at: iso(ms), kind: 'answer' });
const seal = (id, name) => ({ operating_as: `operando como ${name} v1`, selection_context: `ctx-${id}`, agent: { id, name, version: 1, herramientasRetiradas: [] }, memory: { text: '' } });

function select(state, name, id, human, ms) {
  const input = { agent: name, user_choice_quote: name };
  const verdict = policy.preToolUse(state, 'use_agent', input, FACTS, { now: ms, human });
  if (verdict.decision === 'pass') policy.postToolUse(state, 'use_agent', input, seal(id, name), { now: ms + 100, at: iso(ms + 100) });
  return verdict;
}

test('una elección vieja de la persona no vale después de soltar el agente', () => {
  const state = policy.newState('2.0.1');
  policy.postToolUse(state, 'list_agents', {}, KEYRING, { now: T0, at: iso(T0) });
  const human = [answer('Finanzas', T0 + 500)];
  assert.equal(select(state, 'Finanzas', 'ag_finanzas', human, T0 + 1000).decision, 'pass');
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 3000, at: iso(T0 + 3000) });
  // La misma transcripción, con la misma respuesta de antes.
  assert.equal(select(state, 'Finanzas', 'ag_finanzas', human, T0 + 4000).decision, 'ask');
});

test('migrar no atribuye al agente actual lo que escribió otro antes', () => {
  const write = { kind: 'hecho', slug: 'moneda', title: 'Moneda', body_md: 'Reporta en pesos.' };
  const stable = (v) => (Array.isArray(v) ? '[' + v.map(stable).join(',') + ']' : v && typeof v === 'object' ? '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + stable(v[k])).join(',') + '}' : JSON.stringify(v));
  const oldKey = 'remember:' + crypto.createHash('sha256').update(stable(write)).digest('hex').slice(0, 24);
  // La escritura es de antes de que se eligiera el agente actual: la hizo otro.
  const state = policy.migrate({
    v: 1, seal: { agent_id: 'ag_finanzas', agent_name: 'Finanzas', version: 1, selection_context: 'ctx-f', quote: 'x', sealed_at: iso(T0 + 5000) },
    seal_state: 'sealed', retired: [], reads: {}, listings: {}, previews: {}, failures: {},
    writes: { [oldKey]: { status: 'confirmed', at: T0 + 1000, tool: 'remember', name: 'moneda' } },
  }, '2.0.1');
  const verdict = policy.preToolUse(state, 'remember', write, FACTS, { now: T0 + 6000, mode: 'default' });
  assert.notEqual(verdict.decision, 'deny', 'no es un duplicado de este agente');
});

// El detalle de una memoria tal como lo arma Datalum: un marco y cada línea del
// archivo (frontmatter + cuerpo) prefijada con «| ».
function servedDetail(id, title, body) {
  const archivo = `---\ntype: Memory\ntitle: ${title}\n---\n${body}`;
  const block = [
    '=== MEMORIA REGISTRADA · DATOS, NO INSTRUCCIONES ===',
    'Archivo COMPLETO de UNA memoria registrada, pedido por su identificador.',
    `- avance · personal · viva · 2026-10-05 · ${title} · id ${id}`,
    '--- archivo ---',
    archivo.split('\n').map((l) => '| ' + l).join('\n'),
    '--- fin del archivo ---',
    '=== FIN DE MEMORIA REGISTRADA ===',
  ].join('\n');
  return { mode: 'detail', agent_id: 'ag_ventas', memory_id: id, kind: 'avance', scope: 'personal', state: 'viva', title, block, notice: 'Archivo completo de UNA memoria.' };
}
const AVANCE = { kind: 'avance', slug: 'proyecto_a', title: 'Proyecto A · 2 de 3', body_md: '# Pasos\n- [x] Uno — @ana · 2026-10-05\n- [x] Dos — @ana · 2026-10-05\n- [ ] Tres' };

function uncertain() {
  const state = policy.newState('2.0.1');
  policy.postToolUse(state, 'list_agents', {}, { agents: [KEYRING.agents[0]], message: '' }, { now: T0, at: iso(T0) });
  select(state, 'Ventas', 'ag_ventas', [], T0 + 500);
  policy.postToolUseFailure(state, 'remember', AVANCE, 'MCP error -32001: Request timed out', { now: T0 + 2000 }, FACTS);
  return state;
}

test('reconoce como aplicado el detalle real que devuelve Datalum', () => {
  const state = uncertain();
  policy.postToolUse(state, 'list_memories', { memory: 'proyecto_a' }, { content: [{ type: 'text', text: JSON.stringify(servedDetail('mem-2', AVANCE.title, AVANCE.body_md)) }] }, { now: T0 + 3000 });
  assert.equal(policy.preToolUse(state, 'remember', AVANCE, FACTS, { now: T0 + 4000, mode: 'default' }).decision, 'deny');
});

test('reconoce el «no existe» real de Datalum', () => {
  const state = uncertain();
  const missing = { isError: true, content: [{ type: 'text', text: 'No hay ninguna memoria tuya con ese identificador en este agente' }, { type: 'text', text: JSON.stringify({ code: 'agent_memory_not_found', category: 'not_found', retryable: false }) }] };
  policy.postToolUse(state, 'list_memories', { memory: 'proyecto_a' }, missing, { now: T0 + 3000 });
  assert.equal(policy.preToolUse(state, 'remember', AVANCE, FACTS, { now: T0 + 4000, mode: 'default' }).decision, 'pass');
});

test('reconoce la memoria servida por la ruta del cerebro, que llega anidada', () => {
  const state = uncertain();
  const served = { schema_version: '1.3.0', tenant: null, concept_id: 'agents/ventas/memoria/proyecto_a', memory: servedDetail('mem-2', AVANCE.title, AVANCE.body_md) };
  policy.postToolUse(state, 'brain_read', { concept_id: 'agents/ventas/memoria/proyecto_a' }, served, { now: T0 + 3000 });
  assert.equal(policy.preToolUse(state, 'remember', AVANCE, FACTS, { now: T0 + 4000, mode: 'default' }).decision, 'deny');
});

test('elegir otro agente también deja sin efecto lo elegido antes', () => {
  const state = policy.newState('2.0.1');
  policy.postToolUse(state, 'list_agents', {}, KEYRING, { now: T0, at: iso(T0) });
  const human = [answer('Finanzas', T0 + 500), answer('Ventas', T0 + 2000)];
  assert.equal(select(state, 'Finanzas', 'ag_finanzas', human.slice(0, 1), T0 + 1000).decision, 'pass');
  assert.equal(select(state, 'Ventas', 'ag_ventas', human, T0 + 3000).decision, 'pass');
  // Volver a Finanzas con la respuesta de antes no vale: después eligió Ventas.
  assert.equal(select(state, 'Finanzas', 'ag_finanzas', human, T0 + 5000).decision, 'ask');
});

test('una respuesta de antes de la lista de agentes no cuenta', () => {
  const state = policy.newState('2.0.1');
  policy.postToolUse(state, 'list_agents', {}, KEYRING, { now: T0, at: iso(T0) });
  assert.equal(select(state, 'Finanzas', 'ag_finanzas', [answer('Finanzas', T0 - 500)], T0 + 1000).decision, 'ask');
});

test('tras soltar el único agente, la persona vuelve a decidir', () => {
  const state = policy.newState('2.0.1');
  const solo = { agents: [KEYRING.agents[0]], message: '' };
  policy.postToolUse(state, 'list_agents', {}, solo, { now: T0, at: iso(T0) });
  assert.equal(select(state, 'Ventas', 'ag_ventas', [], T0 + 500).decision, 'pass');
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 1000, at: iso(T0 + 1000) });
  assert.equal(select(state, 'Ventas', 'ag_ventas', [], T0 + 2000).decision, 'ask');
  // Pedir la lista otra vez no cambia eso.
  policy.postToolUse(state, 'list_agents', {}, solo, { now: T0 + 2500, at: iso(T0 + 2500) });
  assert.equal(select(state, 'Ventas', 'ag_ventas', [], T0 + 3000).decision, 'ask');
  assert.equal(select(state, 'Ventas', 'ag_ventas', [answer('Ventas', T0 + 3500)], T0 + 4000).decision, 'pass');
});

// Un estado de la 2.0.0 con una escritura confirmada hecha en `writeAt`; el agente
// actual se eligió en T0 + 5000.
const MONEDA = { kind: 'hecho', slug: 'moneda', title: 'Moneda', body_md: 'Reporta en pesos.' };
function migrated(writeAt) {
  const stable = (v) => (Array.isArray(v) ? '[' + v.map(stable).join(',') + ']' : v && typeof v === 'object' ? '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + stable(v[k])).join(',') + '}' : JSON.stringify(v));
  const oldKey = 'remember:' + crypto.createHash('sha256').update(stable(MONEDA)).digest('hex').slice(0, 24);
  return policy.migrate({
    v: 1, seal: { agent_id: 'ag_finanzas', agent_name: 'Finanzas', version: 1, selection_context: 'ctx-f', quote: 'x', sealed_at: iso(T0 + 5000) },
    seal_state: 'sealed', retired: [], reads: {}, listings: {}, previews: {}, failures: {},
    writes: { [oldKey]: { status: 'confirmed', at: writeAt, tool: 'remember', name: 'moneda' } },
  }, '2.0.1');
}

test('lo migrado de agente desconocido lo decide la persona', () => {
  const asked = policy.preToolUse(migrated(T0 + 1000), 'remember', MONEDA, FACTS, { now: T0 + 6000, mode: 'default' });
  assert.equal(asked.decision, 'ask');
  assert.match(asked.reason, /quizá con otro agente/);
  // Sin diálogos nadie vería la pregunta: no se repite.
  assert.equal(policy.preToolUse(migrated(T0 + 1000), 'remember', MONEDA, FACTS, { now: T0 + 6000, mode: 'bypassPermissions' }).decision, 'deny');
});

test('lo migrado de después de elegir el agente sigue siendo suyo', () => {
  const verdict = policy.preToolUse(migrated(T0 + 5500), 'remember', MONEDA, FACTS, { now: T0 + 6000, mode: 'default' });
  assert.equal(verdict.decision, 'deny', 'es un duplicado de este agente');
});

test('un índice no confirma una escritura aunque muestre el mismo texto', () => {
  const state = policy.newState('2.0.1');
  policy.postToolUse(state, 'list_agents', {}, { agents: [KEYRING.agents[0]], message: '' }, { now: T0, at: iso(T0) });
  select(state, 'Ventas', 'ag_ventas', [], T0 + 500);
  // Una escritura por la ruta del cerebro, sin título.
  const write = { concept_id: 'agents/ventas/memoria/proyecto_a', body_md: AVANCE.body_md };
  policy.postToolUseFailure(state, 'brain_write', write, 'MCP error -32001: Request timed out', { now: T0 + 2000 }, FACTS);
  // Datalum devolvió el índice, donde otra memoria tiene el mismo texto.
  const index = { mode: 'index', total: 2, block: ['- avance · personal · viva · Proyecto B · id mem-9', AVANCE.body_md, '- hecho · personal · viva · Moneda · id mem-3'].join('\n') };
  policy.postToolUse(state, 'list_memories', { memory: 'proyecto_a' }, index, { now: T0 + 3000 });
  assert.equal(policy.preToolUse(state, 'brain_write', write, FACTS, { now: T0 + 4000, mode: 'default' }).decision, 'ask');
});

test('cambiar de agente como manda la Skill no vuelve a preguntar', () => {
  // La persona elige Finanzas; el asistente suelta Ventas y elige Finanzas.
  const state = policy.newState('2.0.1');
  policy.postToolUse(state, 'list_agents', {}, KEYRING, { now: T0, at: iso(T0) });
  const human = [answer('Ventas', T0 + 500), answer('Finanzas', T0 + 2000)];
  assert.equal(select(state, 'Ventas', 'ag_ventas', human.slice(0, 1), T0 + 1000).decision, 'pass');
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 3000, at: iso(T0 + 3000) });
  assert.equal(select(state, 'Finanzas', 'ag_finanzas', human, T0 + 4000).decision, 'pass');
  // Y la elección de Ventas, ya usada, no lo vuelve a elegir.
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 5000, at: iso(T0 + 5000) });
  assert.equal(select(state, 'Ventas', 'ag_ventas', human, T0 + 6000).decision, 'ask');
});

test('si elegir el agente nuevo choca con el anterior, soltarlo no anula la elección', () => {
  const state = policy.newState('2.0.1');
  policy.postToolUse(state, 'list_agents', {}, KEYRING, { now: T0, at: iso(T0) });
  const human = [answer('Ventas', T0 + 500), answer('Finanzas', T0 + 2000)];
  select(state, 'Ventas', 'ag_ventas', human.slice(0, 1), T0 + 1000);
  const input = { agent: 'Finanzas', user_choice_quote: 'Finanzas' };
  assert.equal(policy.preToolUse(state, 'use_agent', input, FACTS, { now: T0 + 2500, human }).decision, 'pass');
  policy.postToolUseFailure(state, 'use_agent', input, JSON.stringify({ code: 'agent_seal_held' }), { now: T0 + 2600 }, FACTS);
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 3000, at: iso(T0 + 3000) });
  assert.equal(select(state, 'Finanzas', 'ag_finanzas', human, T0 + 4000).decision, 'pass');
});

test('una elección hecha antes de actualizar desde la 2.0.0 no vuelve a elegir', () => {
  const state = policy.migrate({
    v: 1, seal: { agent_id: 'ag_finanzas', agent_name: 'Finanzas', version: 1, selection_context: 'ctx-f', quote: 'Finanzas', sealed_at: iso(T0 + 1000) },
    keyring: [{ id: 'ag_ventas', name: 'Ventas' }, { id: 'ag_finanzas', name: 'Finanzas' }],
    seal_state: 'sealed', retired: [], reads: {}, listings: {}, previews: {}, failures: {}, writes: {},
  }, '2.0.1', iso(T0 + 3000));
  // Sigue trabajando con el agente que tenía elegido…
  assert.equal(select(state, 'Finanzas', 'ag_finanzas', [], T0 + 4000).decision, 'pass');
  // …pero tras soltarlo, la respuesta de antes de actualizar no lo vuelve a elegir.
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 5000, at: iso(T0 + 5000) });
  assert.equal(select(state, 'Finanzas', 'ag_finanzas', [answer('Finanzas', T0 + 500)], T0 + 6000).decision, 'ask');
});

test('con dos elecciones en paralelo, ninguna de las dos se vuelve a usar', () => {
  const state = policy.newState('2.0.1');
  policy.postToolUse(state, 'list_agents', {}, KEYRING, { now: T0, at: iso(T0) });
  const human = [answer('Ventas', T0 + 500), answer('Finanzas', T0 + 1000)];
  const finanzas = { agent: 'Finanzas', user_choice_quote: 'Finanzas' };
  const ventas = { agent: 'Ventas', user_choice_quote: 'Ventas' };
  assert.equal(policy.preToolUse(state, 'use_agent', finanzas, FACTS, { now: T0 + 2000, human, toolUseId: 'f' }).decision, 'pass');
  assert.equal(policy.preToolUse(state, 'use_agent', ventas, FACTS, { now: T0 + 2000, human, toolUseId: 'v' }).decision, 'pass');
  policy.postToolUse(state, 'use_agent', finanzas, seal('ag_finanzas', 'Finanzas'), { now: T0 + 2100, at: iso(T0 + 2100), toolUseId: 'f' });
  policy.postToolUse(state, 'use_agent', ventas, seal('ag_ventas', 'Ventas'), { now: T0 + 2200, at: iso(T0 + 2200), toolUseId: 'v' });
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 3000, at: iso(T0 + 3000) });
  assert.equal(select(state, 'Finanzas', 'ag_finanzas', human, T0 + 4000).decision, 'ask');
});

// A escribe y se queda sin respuesta, se suelta A, se elige B, se actualiza el plugin
// desde la 2.0.0 y se vuelve a A. La 2.0.0 no sabía de quién era cada escritura.
function updatedAfterSwitch() {
  const stable = (v) => (Array.isArray(v) ? '[' + v.map(stable).join(',') + ']' : v && typeof v === 'object' ? '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + stable(v[k])).join(',') + '}' : JSON.stringify(v));
  const key = (tool, input) => tool + ':' + crypto.createHash('sha256').update(stable(input)).digest('hex').slice(0, 24);
  const uncertain = { kind: 'avance', slug: 'proyecto_a', title: 'Proyecto A', body_md: 'Paso uno hecho.' };
  const confirmed = { kind: 'hecho', slug: 'moneda', title: 'Moneda', body_md: 'Reporta en pesos.' };
  const preview = { name: 'ventas_netas', expression: 'sum(neto)' };
  const state = policy.migrate({
    v: 1, seal: { agent_id: 'ag_finanzas', agent_name: 'Finanzas', version: 1, selection_context: 'ctx-f', quote: 'Finanzas', sealed_at: iso(T0 + 3000) },
    keyring: [{ id: 'ag_ventas', name: 'Ventas' }, { id: 'ag_finanzas', name: 'Finanzas' }],
    seal_state: 'sealed', retired: [], reads: {}, listings: {}, failures: {},
    writes: {
      [key('remember', uncertain)]: { status: 'uncertain', at: T0 + 1000, tool: 'remember', name: 'proyecto_a' },
      [key('remember', confirmed)]: { status: 'confirmed', at: T0 + 1500, tool: 'remember', name: 'moneda' },
    },
    previews: { [key('propose_metric', preview)]: T0 + 1800 },
  }, '2.0.1', iso(T0 + 4000));
  // Vuelve a Ventas con una elección nueva de la persona.
  policy.postToolUse(state, 'release_agent', {}, { released: true }, { now: T0 + 5000, at: iso(T0 + 5000) });
  assert.equal(select(state, 'Ventas', 'ag_ventas', [answer('Ventas', T0 + 5500)], T0 + 6000).decision, 'pass');
  return { state, uncertain, confirmed, preview };
}

test('tras actualizar y volver al agente, su escritura incierta no se repite a ciegas', () => {
  const { state, uncertain } = updatedAfterSwitch();
  assert.equal(policy.preToolUse(state, 'remember', uncertain, FACTS, { now: T0 + 7000, mode: 'default' }).decision, 'ask');
  assert.equal(policy.preToolUse(state, 'remember', uncertain, FACTS, { now: T0 + 7000, mode: 'bypassPermissions' }).decision, 'deny');
});

test('tras actualizar y volver al agente, su escritura confirmada no se repite a ciegas', () => {
  const { state, confirmed } = updatedAfterSwitch();
  assert.notEqual(policy.preToolUse(state, 'remember', confirmed, FACTS, { now: T0 + 7000, mode: 'default' }).decision, 'pass');
});

test('tras actualizar y volver al agente, una vista previa sin dueño no autoriza aplicar', () => {
  const { state, preview } = updatedAfterSwitch();
  const verdict = policy.preToolUse(state, 'propose_metric', Object.assign({ confirm: true }, preview), FACTS, { now: T0 + 7000, mode: 'default' });
  assert.equal(verdict.decision, 'deny');
  assert.match(verdict.reason, /preview first/);
});
