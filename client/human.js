'use strict';
// Lo que dijo la persona en esta conversación, leído de la transcripción que entrega
// la aplicación. Sirve para comprobar que una cita «textual de la persona» lo es.
// No se copia a ningún lado: se lee, se usa para la comprobación y se descarta.

const fs = require('fs');

const MAX_BYTES = 8 * 1024 * 1024;

// Devuelve [{text, at}] en orden, o null si la transcripción no se puede leer.
function read(transcriptPath) {
  if (!transcriptPath) return null;
  let raw;
  try {
    const stat = fs.statSync(transcriptPath);
    const fd = fs.openSync(transcriptPath, 'r');
    const length = Math.min(stat.size, MAX_BYTES);
    const buffer = Buffer.alloc(length);
    fs.readSync(fd, buffer, 0, length, stat.size - length);
    fs.closeSync(fd);
    raw = buffer.toString('utf8');
  } catch (_) {
    return null;
  }
  const human = [];
  for (const line of raw.split('\n')) {
    if (!line.startsWith('{')) continue;
    let entry;
    try {
      entry = JSON.parse(line);
    } catch (_) {
      continue;
    }
    if (entry.type !== 'user' || entry.isSidechain || entry.isMeta) continue;
    const at = entry.timestamp || null;
    // Respuestas de la persona a una pregunta del asistente.
    const result = entry.toolUseResult;
    if (result && result.answers && typeof result.answers === 'object') {
      for (const answer of Object.values(result.answers)) {
        if (typeof answer === 'string') human.push({ text: answer, at });
      }
      continue;
    }
    // Sólo cuenta lo que escribió una persona: no lo que mandó otro agente, ni el texto
    // que la aplicación añade al cargar una skill o al devolver una herramienta.
    if (entry.origin && entry.origin.kind && entry.origin.kind !== 'human') continue;
    if (entry.sourceToolUseID) continue;
    const content = entry.message && entry.message.content;
    if (typeof content === 'string') {
      human.push({ text: content, at });
    } else if (Array.isArray(content)) {
      for (const block of content) {
        if (block && block.type === 'text' && typeof block.text === 'string') human.push({ text: block.text, at });
      }
    }
  }
  return human;
}

module.exports = { read };
