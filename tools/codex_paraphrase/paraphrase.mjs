#!/usr/bin/env node
// Optional paraphrase helper for OpticalNav instruction generation.
//
// Uses codex-as-api (ChatGPT-account OAuth, ~/.codex/auth.json) to rewrite
// grounded template instructions into more varied fluent English. It is a pure
// stdin→stdout filter so the Python side can call it as a subprocess and fall
// back to template-only on any failure.
//
//   --check                : print {"available":bool} and exit (auth probe only)
//   (default, stdin JSON)  : {instructions:[{type,level,text}], n_variants, model?}
//                            -> stdout JSON {results:[{type,level,variants:[str,...]}]}
import { ChatGPTOAuthProvider, isAuthLocallyAvailable, CHATGPT_OAUTH_DEFAULT_MODEL } from 'codex-as-api';

function readStdin() {
  return new Promise((resolve) => {
    let buf = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (c) => (buf += c));
    process.stdin.on('end', () => resolve(buf));
  });
}

async function main() {
  if (process.argv.includes('--check')) {
    let ok = false;
    try { ok = Boolean(isAuthLocallyAvailable()); } catch { ok = false; }
    process.stdout.write(JSON.stringify({ available: ok }));
    return;
  }
  const raw = await readStdin();
  const req = JSON.parse(raw || '{}');
  const instructions = Array.isArray(req.instructions) ? req.instructions : [];
  const n = Math.max(1, Math.min(5, Number(req.n_variants) || 2));
  if (!instructions.length) { process.stdout.write(JSON.stringify({ results: [] })); return; }

  const system =
    'You paraphrase robot navigation instructions into fluent, natural English. ' +
    'Strict rules: preserve every fact exactly — room names, object names, ' +
    'turn directions/angles, order of waypoints, and any mirror/glass warnings. ' +
    'Do NOT invent new landmarks, rooms, objects, or directions. Keep each variant ' +
    'one or two sentences. Reply with ONLY a JSON array, no prose.';
  const user =
    'For each instruction below, produce ' + n + ' alternative English phrasings.\n' +
    'Return a JSON array where element i is {"type": <type>, "level": <level>, "variants": [<' + n + ' strings>]}.\n' +
    'Instructions:\n' + JSON.stringify(instructions.map((x) => ({ type: x.type, level: x.level, text: x.text })));

  const provider = new ChatGPTOAuthProvider({});
  const res = await provider.chat(
    [ { role: 'system', content: system }, { role: 'user', content: user } ],
    { model: req.model || CHATGPT_OAUTH_DEFAULT_MODEL },
  );
  let content = (res && res.content) || '';
  // Strip ``` fences if the model added them.
  content = content.trim().replace(/^```(?:json)?/i, '').replace(/```$/, '').trim();
  let parsed;
  try { parsed = JSON.parse(content); } catch {
    const m = content.match(/\[[\s\S]*\]/);
    parsed = m ? JSON.parse(m[0]) : [];
  }
  const results = (Array.isArray(parsed) ? parsed : []).map((r) => ({
    type: String(r.type || ''),
    level: String(r.level || ''),
    variants: (Array.isArray(r.variants) ? r.variants : []).map((s) => String(s)).filter(Boolean),
  }));
  process.stdout.write(JSON.stringify({ results }));
}

main().catch((e) => {
  process.stderr.write(String((e && e.message) || e));
  process.exit(1);
});
