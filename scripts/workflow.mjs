import fs from 'node:fs';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const hash = data => createHash('sha256').update(data).digest('hex');
const json = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const fail = message => { throw new Error(message); };
const env = { ...process.env, OPENSPEC_TELEMETRY: '0', DO_NOT_TRACK: '1', NO_COLOR: '1' };
// A nested validation suite must be a fresh Node test process, not a child test worker.
for (const key of Object.keys(env)) if (key.startsWith('NODE_TEST_')) delete env[key];

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
}

// Refuse traversal and links rather than following paths outside the selected project.
function safe(root, relative) {
  const target = path.resolve(root, relative);
  if (target !== root && !target.startsWith(root + path.sep)) fail('Path escapes project');
  let at = root;
  for (const part of path.relative(root, target).split(path.sep).filter(Boolean)) {
    at = path.join(at, part);
    if (fs.existsSync(at) && fs.lstatSync(at).isSymbolicLink()) fail('Symbolic links are unsupported: ' + at);
  }
  return target;
}

function walk(root, relative = '', skip = () => false) {
  const directory = safe(root, relative);
  if (!fs.existsSync(directory)) return [];
  const result = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const name = relative ? relative + '/' + entry.name : entry.name;
    if (skip(name)) continue;
    safe(root, name);
    if (entry.isDirectory()) result.push(...walk(root, name, skip));
    else if (entry.isFile()) result.push(name);
    else fail('Unsupported filesystem entry: ' + name);
  }
  return result;
}

function cliLocation(root) {
  const require = createRequire(path.join(root, 'package.json'));
  const entry = require.resolve('@fission-ai/openspec');
  const packageRoot = path.resolve(path.dirname(entry), '..');
  return { bin: path.join(packageRoot, 'bin/openspec.js'), version: json(path.join(packageRoot, 'package.json')).version };
}

export function openspec(root, args) {
  const { bin } = cliLocation(root);
  const result = spawnSync(process.execPath, [bin, ...args], {
    cwd: root, env, encoding: 'utf8', timeout: 60000, maxBuffer: 8 * 1024 * 1024,
  });
  if (result.error || result.status !== 0) fail('OpenSpec failed: ' + args.join(' ') + '\n' + (result.error?.message ?? '') + result.stdout + result.stderr);
  return result.stdout;
}

function context(root, id) {
  root = fs.realpathSync(root);
  if (!/^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/.test(id ?? '')) fail('Use a flat kebab-case change name');
  const config = json(safe(root, 'workflow.config.json'));
  const installed = cliLocation(root).version;
  if (installed !== config.openspecVersion) fail('OpenSpec version mismatch: ' + installed);
  if (config.schema !== 'integrated') fail('Unsupported workflow schema');
  config.testRunner ??= 'node';
  if (!['node', 'python-unittest'].includes(config.testRunner)) fail('Unsupported test runner');
  if (config.testRunner === 'python-unittest' && (typeof config.pythonExecutable !== 'string' || !config.pythonExecutable.trim())) fail('Configure pythonExecutable');
  if (!Array.isArray(config.testFiles) || config.testFiles.length === 0) fail('Configure at least one test file');
  for (const file of config.testFiles) {
    const pattern = config.testRunner === 'node' ? /^test\/[a-zA-Z0-9_./-]+\.test\.m?js$/ : /^tests?\/(?:[a-zA-Z0-9_-]+\/)*test_[a-zA-Z0-9_]+\.py$/;
    if (typeof file !== 'string' || !pattern.test(file)) fail('Invalid test path');
    safe(root, file);
  }
  return { root, id, config, change: safe(root, 'openspec/changes/' + id),
    baseline: safe(root, '.workflow/baselines/' + id + '.json'),
    evidence: safe(root, '.workflow/evidence/' + id + '.json') };
}

function baseState(c) {
  return Object.fromEntries(walk(c.root, 'openspec/specs').map(file => [file, hash(fs.readFileSync(safe(c.root, file)))]));
}

function inputs(c) {
  const ignored = new Set(['node_modules', '.git', '.workflow', '.npm-cache', '.venv', 'venv', 'env']);
  const files = walk(c.root, '', file => ignored.has(file.split('/')[0]) || file.split('/').includes('__pycache__')
    || /\.py[cod]$/.test(file) || ['config.ini', '.env'].includes(file) || file === 'openspec/changes');
  files.push(...walk(c.root, 'openspec/changes/' + c.id));
  const manifest = Object.fromEntries(files.sort().map(file => [file, hash(fs.readFileSync(safe(c.root, file)))]));
  return { digest: hash(JSON.stringify(manifest)), manifest };
}

function deltaRequirements(root, relative) {
  const result = [];
  for (const file of walk(root, relative).filter(file => file.endsWith('/spec.md'))) {
    const content = fs.readFileSync(safe(root, file), 'utf8');
    if (/^## RENAMED Requirements/m.test(content)) fail('RENAMED is outside this starter version');
    const capability = file.slice(relative.length + 1, -'/spec.md'.length);
    for (const match of content.matchAll(/^### Requirement:\s*(.+)$/gm)) {
      const title = match[1].trim();
      const id = /^(R\d+) - .+/.exec(title)?.[1];
      if (!id) fail('Requirement title must start with R<number> - : ' + title);
      result.push({ id, title, capability });
    }
  }
  return result;
}

function assertNoConflicts(c, requirements) {
  const changes = safe(c.root, 'openspec/changes');
  const ours = new Set(requirements.map(r => r.capability + '/' + r.title));
  for (const item of fs.readdirSync(changes, { withFileTypes: true })) {
    if (!item.isDirectory() || item.name === c.id || item.name === 'archive') continue;
    for (const other of deltaRequirements(c.root, 'openspec/changes/' + item.name + '/specs')) {
      if (ours.has(other.capability + '/' + other.title)) fail('Active spec conflict with ' + item.name + ': ' + other.title);
    }
  }
}

function check(c, completed = false) {
  if (!fs.existsSync(c.change)) fail('Active change not found');
  if (!fs.existsSync(c.baseline)) fail('Missing baseline; create changes through workflow new');
  if (JSON.stringify(json(c.baseline).specs) !== JSON.stringify(baseState(c))) fail('Baseline changed; review and run rebase before re-verification');
  for (const name of ['proposal.md', 'design.md', 'tasks.md', 'review.md']) {
    const file = safe(c.root, 'openspec/changes/' + c.id + '/' + name);
    if (!fs.existsSync(file) || !fs.readFileSync(file, 'utf8').trim()) fail('Missing artifact: ' + name);
  }
  const reviewText = fs.readFileSync(path.join(c.change, 'review.md'), 'utf8');
  const blocks = [...reviewText.matchAll(/```json\s*\n([\s\S]*?)\n```/g)];
  if (blocks.length !== 1) fail('review.md must contain one JSON review block');
  const review = JSON.parse(blocks[0][1]);
  if (!['full', 'lite'].includes(review.mode)) fail('Invalid review mode');
  if (review.decision !== 'ready' || !review.reviewer?.trim() || !review.rationale?.trim()) fail('Substantive review is not marked ready');
  if (!Array.isArray(review.openQuestions) || review.openQuestions.length) fail('Unresolved questions block this change');
  const taskText = fs.readFileSync(path.join(c.change, 'tasks.md'), 'utf8');
  const checkboxes = taskText.split('\n').filter(line => /^\s*-\s*\[/.test(line));
  const tasks = checkboxes.map(line => {
    const match = /^\s*- \[([ xX])\] (\d+\.\d+)\s+\S/.exec(line);
    if (!match) fail('Task must be a numbered standard checkbox: ' + line);
    return { id: match[2], done: match[1].toLowerCase() === 'x' };
  });
  if (!tasks.length || new Set(tasks.map(t => t.id)).size !== tasks.length) fail('Missing or duplicate task IDs');
  if (completed && tasks.some(t => !t.done)) fail('Incomplete tasks');
  const requirements = deltaRequirements(c.root, 'openspec/changes/' + c.id + '/specs');
  if (!requirements.length) fail('This starter requires a behavior delta; documentation-only changes are not yet supported');
  const design = fs.readFileSync(path.join(c.change, 'design.md'), 'utf8');
  const references = [...requirements.map(r => r.id), ...[...design.matchAll(/^### Check: (D\d+) - .+$/gm)].map(m => m[1])];
  if (new Set(references).size !== references.length) fail('Use unique requirement/check IDs within a change');
  if (!Array.isArray(review.coverage) || !review.coverage.length) fail('Missing coverage map');
  for (const link of review.coverage) {
    if (!references.includes(link.requirement) || !tasks.some(t => t.id === link.task)) fail('Unknown coverage requirement or task');
    if (!c.config.testFiles.includes(link.test) || !fs.existsSync(safe(c.root, link.test))) fail('Coverage test is missing or not in configured test suite');
  }
  for (const ref of references) if (!review.coverage.some(l => l.requirement === ref)) fail('Uncovered requirement/check: ' + ref);
  for (const task of tasks) if (!review.coverage.some(l => l.task === task.id)) fail('Uncovered task: ' + task.id);
  assertNoConflicts(c, requirements);
  openspec(c.root, ['schema', 'validate', c.config.schema, '--json']);
  openspec(c.root, ['validate', c.id, '--type', 'change', '--strict', '--json', '--no-interactive']);
  return { mode: review.mode, tasks: tasks.length, requirements: requirements.length, requiredTestIds: references };
}

export function executeTests(root, config, requiredTestIds) {
  const python = config.testRunner === 'python-unittest';
  const token = randomUUID();
  const reportPath = safe(root, '.workflow/python-' + token + '.json');
  const command = python
    ? [config.pythonExecutable, '-B', 'scripts/unittest_runner.py', '--report', reportPath, '--token', token, ...config.testFiles]
    : [process.execPath, '--test', '--test-reporter=tap', ...config.testFiles];
  const result = spawnSync(command[0], command.slice(1), {
    cwd: root, env: { ...env, PYTHONDONTWRITEBYTECODE: '1', PYTHONUTF8: '1' }, encoding: 'utf8', timeout: 60000, maxBuffer: 8 * 1024 * 1024,
  });
  const output = (result.stdout ?? '') + (result.stderr ?? '');
  let report = null;
  try {
    if (python && fs.existsSync(reportPath)) report = json(reportPath);
  } finally {
    if (fs.existsSync(reportPath)) fs.unlinkSync(reportPath);
  }
  const count = python ? Number(report?.tests ?? 0) : Number(/^# tests (\d+)\s*$/m.exec(output)?.[1] ?? 0);
  const executedIds = python ? (report?.passedIds ?? [])
    : [...output.matchAll(/^\s*# Subtest: ([RD]\d+):\s+\S/gm)].map(match => match[1]);
  const clean = python
    ? report?.token === token && report.success === true && report.passed > 0
      && ['failures', 'errors', 'skipped', 'expectedFailures', 'unexpectedSuccesses'].every(key => report[key] === 0)
    : Number(/^# pass (\d+)\s*$/m.exec(output)?.[1] ?? 0) > 0
      && ['fail', 'cancelled', 'skipped', 'todo'].every(key => new RegExp('^# ' + key + ' 0\\s*$', 'm').test(output));
  const passed = !result.error && result.status === 0 && count > 0 && clean
    && requiredTestIds.every(id => executedIds.includes(id));
  return { passed: Boolean(passed), count, executedIds: [...new Set(executedIds)], command, output,
    exitCode: result.status, error: result.error?.message ?? null, runnerReport: report };
}

function verify(c) {
  // Replace old success before checking anything: a failed new attempt never leaves a valid receipt.
  writeJson(c.evidence, { change: c.id, passed: false, startedAt: new Date().toISOString() });
  const summary = check(c, true);
  const before = inputs(c);
  const result = executeTests(c.root, c.config, summary.requiredTestIds);
  const { output, passed, count, executedIds } = result;
  const log = safe(c.root, '.workflow/evidence/' + c.id + (c.config.testRunner === 'python-unittest' ? '.log' : '.tap'));
  fs.writeFileSync(log, output);
  const unchanged = before.digest === inputs(c).digest;
  const evidence = { change: c.id, passed: passed && unchanged, finishedAt: new Date().toISOString(),
    node: process.version, openspec: c.config.openspecVersion, command: result.command,
    testRunner: c.config.testRunner, runnerReport: result.runnerReport,
    exitCode: result.exitCode, error: result.error, tests: count, executedIds, summary,
    ...before, log: path.relative(c.root, log).replaceAll('\\', '/'), logHash: hash(output) };
  writeJson(c.evidence, evidence);
  if (!unchanged) fail('Inputs changed during verification');
  if (!passed) fail('Tests failed or no tests executed; see ' + evidence.log);
  return evidence;
}

export function runWorkflow(root, action, id) {
  const c = context(root, id);
  const lock = safe(c.root, '.workflow/lock');
  fs.mkdirSync(path.dirname(lock), { recursive: true });
  const fd = fs.openSync(lock, 'wx');
  try {
    if (action === 'new') {
      if (fs.existsSync(c.change) || fs.existsSync(c.baseline)) fail('Change name already used');
      const output = openspec(c.root, ['new', 'change', id, '--schema', c.config.schema, '--json']);
      writeJson(c.baseline, { change: id, capturedAt: new Date().toISOString(), specs: baseState(c) });
      return { action, id, output };
    }
    if (action === 'rebase') {
      if (!fs.existsSync(c.change)) fail('Active change not found');
      writeJson(c.evidence, { change: id, passed: false, reason: 'baseline explicitly refreshed; review and verify again' });
      const reviewFile = path.join(c.change, 'review.md');
      if (fs.existsSync(reviewFile)) {
        const text = fs.readFileSync(reviewFile, 'utf8');
        fs.writeFileSync(reviewFile, text.replace(/("decision"\s*:\s*)"[^"]*"/, '$1"pending"'));
      }
      writeJson(c.baseline, { change: id, capturedAt: new Date().toISOString(), specs: baseState(c) });
      return { action, id, decision: 'pending', note: 'Reconcile deltas with the new baseline before setting ready' };
    }
    if (action === 'check') return { action, id, ...check(c) };
    if (action === 'verify') return verify(c);
    if (action === 'archive') {
      check(c, true);
      if (!fs.existsSync(c.evidence)) fail('Missing verification evidence');
      const evidence = json(c.evidence);
      if (!evidence.passed || evidence.digest !== inputs(c).digest) fail('Missing, failed or stale verification evidence');
      const log = safe(c.root, evidence.log);
      if (!fs.existsSync(log) || hash(fs.readFileSync(log)) !== evidence.logHash) fail('Verification log changed');
      // Run the suite again at the delivery boundary; the evidence file alone is not trusted.
      const fresh = verify(c);
      const output = openspec(c.root, ['archive', id, '--yes', '--json']);
      if (fs.existsSync(c.change)) fail('OpenSpec did not archive the change');
      const archive = safe(c.root, 'openspec/changes/archive');
      const folder = fs.readdirSync(archive).find(name => name.endsWith('-' + id));
      if (!folder) fail('Archive receipt directory not found');
      // Upstream may accept a delta yet produce a main spec with strict warnings.
      // No success receipt is emitted until the synchronized specs pass too.
      // This check is post-mutation: failure requires inspecting the saved archive.
      const validation = JSON.parse(openspec(c.root, ['validate', '--specs', '--strict', '--json', '--no-interactive']));
      const receipt = { change: id, archivedAt: new Date().toISOString(), archive: 'openspec/changes/archive/' + folder,
        verifiedDigest: fresh.digest, specs: baseState(c), validation, output };
      writeJson(safe(c.root, '.workflow/receipts/' + id + '.json'), receipt);
      return receipt;
    }
    fail('Usage: node scripts/workflow.mjs new|check|verify|archive|rebase <change>');
  } finally {
    fs.closeSync(fd);
    fs.unlinkSync(lock);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try { console.log(JSON.stringify(runWorkflow(process.cwd(), process.argv[2], process.argv[3]), null, 2)); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
