// Check readiness handoff and preserve the configured OFFBEAT entry.
import assert from 'node:assert/strict';
import { apply } from '../../dsh/mandifuel-shell-env.mjs';

const fakeSecret = 'not-for-the-system-prompt';
process.env.DEEPS_EVALUATION_KEY = fakeSecret;
process.env.MANDIFUEL_RAG_MAPPING_API_KEY_ENV = 'DEEPS_EVALUATION_KEY';
process.env.MANDIFUEL_PLUGIN_ROOT = '/configured/plugin';
process.env.MANDIFUEL_TASK_PYTHON = '/configured/python3';
process.env.MANDIFUEL_OFFBEAT_EXECUTABLE = '/configured/budget-wrapper/offbeat';

function mount() {
  const sections = [];
  let registration;
  apply({ on: () => () => {}, systemPrompt: { section: (s) => sections.push(s) },
          shellEnv: { register: (r) => { registration = r; } } });
  assert.equal(sections.length, 2);
  assert.ok(sections.every((s) => !s.text.includes(fakeSecret)));
  return { sections, env: registration.resolve() };
}
process.env.MANDIFUEL_ENVIRONMENT_READY = '1';
const ready = mount();
assert.equal(ready.env.DSH_MANDIFUEL_ENVIRONMENT_READY, '1');
assert.equal(ready.env.DSH_MANDIFUEL_OFFBEAT_EXECUTABLE, '/configured/budget-wrapper/offbeat');
assert.equal(ready.env.DSH_MANDIFUEL_TASK_PYTHON, '/configured/python3');
assert.ok(ready.sections.some((s) => s.text.includes('/configured/budget-wrapper/offbeat')));
assert.equal(ready.env.DSH_MANDIFUEL_TASK_OFFLINE, '1');
assert.ok(!Object.keys(ready.env).some(k => k.includes('API_KEY')));
delete process.env.MANDIFUEL_ENVIRONMENT_READY;
const absent = mount();
assert.equal(absent.env.DSH_MANDIFUEL_ENVIRONMENT_READY, '');
assert.ok(absent.sections.every((s) => !s.text.includes('/configured/budget-wrapper/offbeat')));
console.log('PASS: ready/absent handoff, wrapper entry retained, credentials excluded from prompt');
